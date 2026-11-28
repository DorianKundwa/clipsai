"""
Master rendering for short-form platforms.

Everything that makes a clip *deliverable* lives here: the platform export
profiles (size, frame rate, bitrate), the reframing fill that avoids black bars,
the colour grades, the punch-in cadence, audio loudness normalisation and a QA
pass that rejects a file which does not match the spec.

The module is deliberately ffmpeg-only: no model, no GPU, no browser. The Studio
and the web API call :func:`finish_clip` once per clip after captions/hooks are
known, so the final file is encoded once at delivery quality instead of three
times by successive burn steps.

Example
-------
>>> from clipsai.render import EXPORT_PROFILES, build_export_filter
>>> profile = EXPORT_PROFILES["shorts"]
>>> profile.width, profile.height, profile.fps
(1080, 1920, 60.0)
>>> "boxblur" in build_export_filter(profile, pad="blur")
True
"""

# standard library imports
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

# local package imports
from clipsai.captions.captions import escape_filter_path, fonts_dir

SUCCESS = 0

#: Loudness target for every short-form platform. A clip that plays quieter
#: than the feed gets skipped; louder than -14 LUFS gets turned down and
#: distorted by the platform.
LOUDNESS_TARGET = -14.0
TRUE_PEAK = -1.5

PAD_MODES = ("crop", "blur", "black")
PAD_LABELS = {
    "crop": "Fill the frame (crop the edges)",
    "blur": "Fill with a blurred copy (no black bars)",
    "black": "Fit inside a black frame",
}


class RenderError(Exception):
    """Raised when a master render or its verification fails."""


@dataclass(frozen=True)
class ExportProfile:
    """One delivery target."""

    key: str
    label: str
    width: int
    height: int
    fps: float
    video_bitrate: str = "12M"
    minrate: str = "8M"
    maxrate: str = "16M"
    bufsize: str = "24M"
    audio_bitrate: str = "192k"
    audio_rate: int = 48000
    loudness: float = LOUDNESS_TARGET
    true_peak: float = TRUE_PEAK
    level: str = "4.2"
    min_seconds: float = 1.0
    max_seconds: float = 180.0

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "video_bitrate": self.video_bitrate,
            "audio_bitrate": self.audio_bitrate,
            "audio_rate": self.audio_rate,
            "loudness": self.loudness,
            "max_seconds": self.max_seconds,
        }


#: Ordered profiles; ``shorts`` is the campaign master (1080x1920, 60 fps, 12M).
EXPORT_PROFILES = {
    "shorts": ExportProfile(
        key="shorts",
        label="YouTube Shorts — 1080×1920 · 60 fps · 12 Mbps",
        width=1080,
        height=1920,
        fps=60.0,
    ),
    "reels": ExportProfile(
        key="reels",
        label="Instagram Reels — 1080×1920 · 30 fps · 10 Mbps",
        width=1080,
        height=1920,
        fps=30.0,
        video_bitrate="10M",
        minrate="7M",
        maxrate="14M",
        bufsize="20M",
        max_seconds=90.0,
    ),
    "tiktok": ExportProfile(
        key="tiktok",
        label="TikTok — 1080×1920 · 30 fps · 10 Mbps",
        width=1080,
        height=1920,
        fps=30.0,
        video_bitrate="10M",
        minrate="7M",
        maxrate="14M",
        bufsize="20M",
        max_seconds=180.0,
    ),
    "youtube": ExportProfile(
        key="youtube",
        label="YouTube — 1920×1080 · 30 fps · 12 Mbps",
        width=1920,
        height=1080,
        fps=30.0,
        max_seconds=1800.0,
    ),
    "square": ExportProfile(
        key="square",
        label="Square feed — 1080×1080 · 30 fps · 8 Mbps",
        width=1080,
        height=1080,
        fps=30.0,
        video_bitrate="8M",
        minrate="5M",
        maxrate="11M",
        bufsize="16M",
        max_seconds=60.0,
    ),
}

EXPORT_PROFILE_NAMES = tuple(EXPORT_PROFILES)

#: Colour grades. Each value is a filter chain fragment.
GRADES = {
    "none": "",
    "warm": "colorbalance=rs=0.06:gs=0.01:bs=-0.05:rm=0.03:bm=-0.02",
    "cool": "colorbalance=rs=-0.05:gs=0.0:bs=0.06:rm=-0.02:bm=0.03",
    "punchy": "eq=contrast=1.09:saturation=1.18:brightness=0.005",
    "film": (
        "colorbalance=rs=0.03:gs=0.01:bs=-0.03,"
        "eq=contrast=1.05:saturation=0.92,"
        "vignette=angle=PI/5"
    ),
    "mono": "hue=s=0,eq=contrast=1.08",
}

GRADE_NAMES = tuple(GRADES)


@dataclass(frozen=True)
class CropWindow:
    """Fraction of each edge to remove before reframing.

    Used for sources that carry their own burned-in captions or a padded band:
    cropping 28% off the bottom of an Instagram reel removes the app's subtitle
    strip, and a 4:5 master with blurred padding can be cut back to its sharp
    picture before it is scaled.
    """

    top: float = 0.0
    bottom: float = 0.0
    left: float = 0.0
    right: float = 0.0

    def validate(self) -> "CropWindow":
        for name in ("top", "bottom", "left", "right"):
            value = float(getattr(self, name))
            if not 0.0 <= value < 0.5:
                raise RenderError(
                    "crop {} must be between 0 and 0.5 (got {}).".format(name, value)
                )
        if self.left + self.right >= 0.6 or self.top + self.bottom >= 0.6:
            raise RenderError("The crop window leaves too little of the frame.")
        return self

    def filter(self) -> "str | None":
        if not any((self.top, self.bottom, self.left, self.right)):
            return None
        self.validate()
        return (
            "crop=w=trunc(iw*{kw}/2)*2:h=trunc(ih*{kh}/2)*2:"
            "x=trunc(iw*{x}/2)*2:y=trunc(ih*{y}/2)*2".format(
                kw=round(1.0 - self.left - self.right, 4),
                kh=round(1.0 - self.top - self.bottom, 4),
                x=round(self.left, 4),
                y=round(self.top, 4),
            )
        )

    def as_dict(self) -> dict:
        return {
            "top": self.top,
            "bottom": self.bottom,
            "left": self.left,
            "right": self.right,
        }


def parse_crop(value) -> "CropWindow | None":
    """Parse ``"top,bottom,left,right"`` (or a dict / CropWindow) into a window."""
    if value is None or value == "" or value == "off":
        return None
    if isinstance(value, CropWindow):
        return value.validate()
    if isinstance(value, dict):
        return CropWindow(
            top=float(value.get("top") or 0),
            bottom=float(value.get("bottom") or 0),
            left=float(value.get("left") or 0),
            right=float(value.get("right") or 0),
        ).validate()
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = [part for part in re.split(r"[,:; ]+", str(value)) if part]
    if len(parts) != 4:
        raise RenderError(
            "crop must have four fractions (top,bottom,left,right), got {!r}".format(
                value
            )
        )
    try:
        return CropWindow(*(float(part) for part in parts)).validate()
    except (TypeError, ValueError) as exc:
        raise RenderError("crop fractions must be numbers.") from exc


def _profile(profile: "str | ExportProfile") -> ExportProfile:
    if isinstance(profile, ExportProfile):
        return profile
    key = str(profile or "").strip().lower()
    if key not in EXPORT_PROFILES:
        raise RenderError(
            "Unknown export profile '{}'. Choose one of: {}.".format(
                profile, ", ".join(EXPORT_PROFILES)
            )
        )
    return EXPORT_PROFILES[key]


def _grade(value: "str | None") -> str:
    key = str(value or "none").strip().lower()
    if key not in GRADES:
        raise RenderError(
            "Unknown grade '{}'. Choose one of: {}.".format(value, ", ".join(GRADES))
        )
    return GRADES[key]


def build_export_filter(
    profile: "str | ExportProfile" = "shorts",
    *,
    pad: str = "blur",
    grade: str = "none",
    crop: "CropWindow | str | None" = None,
    punch_ins=(),
) -> str:
    """Build the filter_complex graph for one master render.

    The graph starts at ``[0:v]`` and always ends at ``[v]``. ``pad`` decides
    what happens to a source whose aspect does not match the profile: fill and
    crop, fill with a blurred copy of itself behind the picture (the no-black-bar
    default), or fit inside a black frame. ``punch_ins`` are clip-relative
    seconds for the 102%→108% cadence.
    """
    target = _profile(profile)
    pad_key = str(pad or "blur").strip().lower()
    if pad_key not in PAD_MODES:
        raise RenderError(
            "Unknown pad mode '{}'. Choose one of: {}.".format(pad, ", ".join(PAD_MODES))
        )
    grade_filter = _grade(grade)
    window = parse_crop(crop)
    fps = "{:g}".format(target.fps)

    segments = []
    label = "0:v"
    crop_filter = window.filter() if window else None
    if crop_filter:
        segments.append("[{}]{}[cropped]".format(label, crop_filter))
        label = "cropped"

    width, height = target.width, target.height
    if pad_key == "blur":
        segments.append("[{}]split=2[bg][fg]".format(label))
        segments.append(
            "[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            "crop={w}:{h},boxblur=28:2,eq=brightness=-0.20[backdrop]".format(
                w=width, h=height
            )
        )
        segments.append(
            "[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[sharp]".format(
                w=width, h=height
            )
        )
        segments.append(
            "[backdrop][sharp]overlay={x}:{y}:format=auto[framed]".format(
                x="(W-w)/2", y="(H-h)/2"
            )
        )
        label = "framed"
    elif pad_key == "crop":
        segments.append(
            "[{}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            "crop={w}:{h}[framed]".format(label, w=width, h=height)
        )
        label = "framed"
    else:
        segments.append(
            "[{}]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black[framed]".format(
                label, w=width, h=height
            )
        )
        label = "framed"

    follow = ["fps={}".format(fps), "setsar=1"]
    if grade_filter:
        follow.append(grade_filter)
    follow.append("unsharp=5:5:0.25")
    segments.append("[{}]{}[graded]".format(label, ",".join(follow)))
    label = "graded"

    if punch_ins:
        # imported lazily: clipsai.ai.effects pulls in the LLM client module
        from clipsai.ai.effects import build_punch_in_filter

        zoom = build_punch_in_filter(
            punch_ins,
            fps=target.fps,
            width=width,
            height=height,
            base=1.02,
            strength=0.06,
        )
        if zoom:
            segments.append("[{}]{}[punched]".format(label, zoom))
            label = "punched"

    segments.append("[{}]format=yuv420p[v]".format(label))
    return ";".join(segments)


def _probe(path: str) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,"
        "sample_rate,channels,bit_rate:format=duration,bit_rate",
        "-of",
        "json",
        path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS:
        raise RenderError(
            "ffprobe could not read '{}': {}".format(
                path, (result.stderr or "").strip()[:400]
            )
        )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise RenderError("Unexpected ffprobe output for '{}'.".format(path)) from exc

    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    numerator, _, denominator = str(video.get("r_frame_rate") or "0/1").partition("/")
    try:
        fps = float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "video_codec": video.get("codec_name") or "",
        "audio_codec": audio.get("codec_name") or "",
        "audio_rate": int(audio.get("sample_rate") or 0),
        "audio_channels": int(audio.get("channels") or 0),
        "has_audio": bool(audio),
        "duration": float(payload.get("format", {}).get("duration") or 0.0),
    }


def _audio_args(target: ExportProfile, loudness, has_audio: bool) -> "list[str]":
    if not has_audio:
        return ["-an"]
    loud = target.loudness if loudness is None else float(loudness)
    return [
        "-map",
        "0:a:0?",
        "-af",
        "loudnorm=I={:g}:TP={:g}:LRA=11".format(loud, target.true_peak),
        "-c:a",
        "aac",
        "-b:a",
        target.audio_bitrate,
        "-ar",
        str(target.audio_rate),
        "-ac",
        "2",
    ]


def _video_args(target: ExportProfile, preset: str) -> "list[str]":
    return [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-profile:v",
        "high",
        "-level",
        target.level,
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        target.video_bitrate,
        "-minrate",
        target.minrate,
        "-maxrate",
        target.maxrate,
        "-bufsize",
        target.bufsize,
        "-x264-params",
        "nal-hrd=cbr:force-cfr=1",
        "-g",
        str(int(round(target.fps * 2))),
        "-movflags",
        "+faststart",
    ]


def build_export_command(
    video_file_path: str,
    output_file_path: str,
    profile: "str | ExportProfile" = "shorts",
    *,
    pad: str = "blur",
    grade: str = "none",
    crop: "CropWindow | str | None" = None,
    punch_ins=(),
    loudness: "float | None" = None,
    preset: str = "medium",
    duration: "float | None" = None,
    has_audio: bool = True,
) -> "list[str]":
    """ffmpeg arguments for a master render (no ``ffmpeg`` executable)."""
    target = _profile(profile)
    graph = build_export_filter(target, pad=pad, grade=grade, crop=crop, punch_ins=punch_ins)
    argv = [
        "-i",
        video_file_path,
        "-filter_complex",
        graph,
        "-map",
        "[v]",
    ]
    argv += _audio_args(target, loudness, has_audio)
    argv += _video_args(target, preset)
    if duration:
        argv += ["-t", "{:.3f}".format(float(duration))]
    argv.append(output_file_path)
    return argv


def _hook_overlay(
    graph: str,
    label: str,
    hook_png: str,
    target: ExportProfile,
    hook_seconds: float,
    next_index: int,
) -> "tuple[str, str]":
    """Append the hook overlay to ``graph``, returning the new graph and label."""
    try:
        from PIL import Image

        with Image.open(hook_png) as image:
            hook_height = image.height
    except Exception:  # noqa: BLE001 - a broken PNG is caught by ffmpeg
        hook_height = int(target.height * 0.12)

    # Center the card on the upper band anchor (17% of the frame height).
    y = max(0, int(round(0.17 * target.height - hook_height / 2)))
    limit = float(hook_seconds or target.max_seconds)
    graph += (
        ";[{idx}:v]format=rgba,scale={w}:-2[hook]"
        ";[{label}][hook]overlay=x=(W-w)/2:y={y}:"
        "enable='between(t,0,{limit:.3f})':eof_action=pass[hooked]"
    ).format(idx=next_index, w=target.width, label=label, y=y, limit=limit)
    return graph, "hooked"


def finish_clip(
    video_file_path: str,
    output_file_path: str,
    profile: "str | ExportProfile" = "shorts",
    *,
    pad: str = "blur",
    grade: str = "none",
    crop: "CropWindow | str | None" = None,
    punch_ins=(),
    cues=None,
    caption_preset: str = "kinetic",
    caption_font: "str | None" = None,
    caption_position: "str | None" = None,
    caption_pop: "bool | None" = None,
    hook_png: "str | None" = None,
    hook_seconds: float = 4.0,
    loudness: "float | None" = None,
    preset: str = "medium",
) -> str:
    """Encode one layer-ordered master: grade → punch-ins → hook → captions.

    Doing every layer in one pass is both faster and visibly cleaner than
    burning the hook and the captions onto an already-compressed file. Returns
    the output path; raises :class:`RenderError` on failure.
    """
    if not os.path.isfile(video_file_path):
        raise RenderError("Video file '{}' does not exist.".format(video_file_path))
    target = _profile(profile)
    info = _probe(video_file_path)

    ass_path = None
    if cues:
        from clipsai.captions.captions import write_ass

        ass_path = os.path.splitext(output_file_path)[0] + ".ass"
        write_ass(
            cues,
            ass_path,
            preset=caption_preset,
            width=target.width,
            height=target.height,
            font=caption_font,
            position=caption_position,
            pop=caption_pop,
        )

    graph = build_export_filter(target, pad=pad, grade=grade, crop=crop, punch_ins=punch_ins)
    label = "v"
    inputs = ["-i", video_file_path]
    next_index = 1

    if hook_png and os.path.isfile(hook_png):
        inputs += ["-loop", "1", "-i", hook_png]
        graph, label = _hook_overlay(
            graph, label, hook_png, target, hook_seconds, next_index
        )
        next_index += 1

    if ass_path:
        graph += ";[{}]subtitles=filename='{}':fontsdir='{}'[captioned]".format(
            label,
            escape_filter_path(ass_path),
            escape_filter_path(fonts_dir()),
        )
        label = "captioned"

    argv = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph,
            "-map", "[{}]".format(label)]
    argv += _audio_args(target, loudness, info["has_audio"])
    argv += _video_args(target, preset)
    if info["duration"]:
        argv += ["-t", "{:.3f}".format(info["duration"])]
    argv.append(output_file_path)

    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != SUCCESS or not os.path.isfile(output_file_path):
        raise RenderError(
            "Rendering the master failed. ffmpeg said:\n{}".format(
                (result.stderr or "").strip()[-2000:]
            )
        )
    return output_file_path


def export_clip(
    video_file_path: str,
    output_file_path: str,
    profile: "str | ExportProfile" = "shorts",
    *,
    pad: str = "blur",
    grade: str = "none",
    crop: "CropWindow | str | None" = None,
    punch_ins=(),
    loudness: "float | None" = None,
    preset: str = "medium",
) -> str:
    """Re-encode a clip to a platform profile with normalized audio."""
    if not os.path.isfile(video_file_path):
        raise RenderError("Video file '{}' does not exist.".format(video_file_path))
    target = _profile(profile)
    info = _probe(video_file_path)
    argv = ["ffmpeg", "-y", "-v", "error"]
    argv += build_export_command(
        video_file_path,
        output_file_path,
        target,
        pad=pad,
        grade=grade,
        crop=crop,
        punch_ins=punch_ins,
        loudness=loudness,
        preset=preset,
        duration=info["duration"] or None,
        has_audio=info["has_audio"],
    )
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != SUCCESS or not os.path.isfile(output_file_path):
        raise RenderError(
            "Exporting the clip failed. ffmpeg said:\n{}".format(
                (result.stderr or "").strip()[-2000:]
            )
        )
    return output_file_path


def measure_loudness(video_file_path: str) -> dict:
    """Integrated loudness, true peak and LRA of a finished file (LUFS)."""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        video_file_path,
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    stderr = result.stderr or ""
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not match:
        raise RenderError(
            "Could not measure loudness of '{}'. ffmpeg said:\n{}".format(
                video_file_path, stderr[-800:]
            )
        )
    try:
        payload = json.loads(match.group(0))
        return {
            "integrated": float(payload.get("input_i")),
            "true_peak": float(payload.get("input_tp")),
            "lra": float(payload.get("input_lra")),
        }
    except (ValueError, TypeError) as exc:
        raise RenderError("Unexpected loudness output: {}".format(match.group(0))) from exc


def verify_output(
    video_file_path: str,
    profile: "str | ExportProfile" = "shorts",
    *,
    loudness_tolerance: float = 1.0,
    check_loudness: bool = True,
) -> dict:
    """Check a rendered file against its platform profile.

    Returns ``{"ok": bool, "checks": [...], "stats": {...}, "loudness": {...}}``.
    Each check records what was expected and what was found, so the Studio can
    show a real QA table instead of claiming success.
    """
    target = _profile(profile)
    info = _probe(video_file_path)
    checks = []

    def check(name, expected, actual, passed):
        checks.append(
            {
                "name": name,
                "expected": expected,
                "actual": actual,
                "ok": bool(passed),
            }
        )

    check(
        "resolution",
        "{}×{}".format(target.width, target.height),
        "{}×{}".format(info["width"], info["height"]),
        info["width"] == target.width and info["height"] == target.height,
    )
    check(
        "frame rate",
        target.fps,
        round(info["fps"], 3),
        abs(info["fps"] - target.fps) < 0.05,
    )
    check("video codec", "h264", info["video_codec"], info["video_codec"] == "h264")
    if info["has_audio"]:
        check("audio codec", "aac", info["audio_codec"], info["audio_codec"] == "aac")
        check(
            "sample rate",
            target.audio_rate,
            info["audio_rate"],
            info["audio_rate"] == target.audio_rate,
        )
        check("channels", 2, info["audio_channels"], info["audio_channels"] == 2)
    check(
        "duration",
        "{}–{}s".format(target.min_seconds, target.max_seconds),
        round(info["duration"], 2),
        target.min_seconds <= info["duration"] <= target.max_seconds,
    )

    loudness = None
    if check_loudness and info["has_audio"]:
        try:
            loudness = measure_loudness(video_file_path)
            check(
                "loudness (LUFS)",
                target.loudness,
                round(loudness["integrated"], 1),
                abs(loudness["integrated"] - target.loudness) <= loudness_tolerance,
            )
            check(
                "true peak (dBTP)",
                "< {:g}".format(target.true_peak),
                round(loudness["true_peak"], 1),
                loudness["true_peak"] <= target.true_peak + 0.5,
            )
        except RenderError as exc:
            check("loudness (LUFS)", target.loudness, str(exc), False)

    return {
        "ok": all(item["ok"] for item in checks),
        "checks": checks,
        "stats": info,
        "loudness": loudness,
        "profile": target.key,
    }


def assert_output(video_file_path: str, profile: "str | ExportProfile" = "shorts") -> dict:
    """Verify a render and raise :class:`RenderError` if any check fails."""
    report = verify_output(video_file_path, profile)
    if not report["ok"]:
        failed = [
            "{}: expected {}, got {}".format(
                item["name"], item["expected"], item["actual"]
            )
            for item in report["checks"]
            if not item["ok"]
        ]
        raise RenderError(
            "'{}' does not meet the {} profile: {}".format(
                video_file_path, report["profile"], "; ".join(failed)
            )
        )
    return report
