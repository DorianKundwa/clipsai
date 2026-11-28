"""
AI edit decision lists (subtle effects) rendered by ffmpeg.

The model only decides WHAT to do and WHEN. This module validates those
decisions with hard caps and turns them into a safe ``-vf`` filter string, so a
bad model response can never produce a broken ffmpeg command or an absurd zoom.
"""

# standard library imports
from __future__ import annotations

import json
import subprocess

# current package imports
from .llm import LLMClient

SUCCESS = 0

EFFECT_LIMITS = {
    "zoom_in": {"zoom": True, "max_strength": 0.15, "default_strength": 0.10},
    "punch_in": {"zoom": True, "max_strength": 0.15, "default_strength": 0.09},
    "zoom_out": {"zoom": True, "max_strength": 0.15, "default_strength": 0.10},
    "zoom_pulse": {"zoom": True, "max_strength": 0.10, "default_strength": 0.07},
    "color_pop": {"zoom": False, "max_strength": 1.0, "default_strength": 0.5},
    "warm": {"zoom": False, "max_strength": 1.0, "default_strength": 0.5},
    "cool": {"zoom": False, "max_strength": 1.0, "default_strength": 0.5},
    "grain": {"zoom": False, "max_strength": 1.0, "default_strength": 0.35},
    "shake": {"zoom": False, "max_strength": 1.0, "default_strength": 0.5},
    "bw_moment": {"zoom": False, "max_strength": 1.0, "default_strength": 1.0},
    "flash": {"zoom": False, "max_strength": 1.0, "default_strength": 1.0},
    "vignette": {"zoom": False, "max_strength": 1.0, "default_strength": 1.0},
}

MAX_EDITS = 12
MIN_EFFECT_SECONDS = 0.15
MAX_ZOOM_SECONDS = 8.0
FLASH_SECONDS = 0.15
ZOOM_CENTER_Y = 0.45

_EFFECTS_PROMPT = """You are a video editor adding subtle emphasis to a short clip.

Transcript of the clip ({language}):
{transcript}

Clip duration: {duration:.2f} seconds.

Pick 0-7 moments where a SMALL effect supports the edit. Allowed types:
- "zoom_in": slow push in on a key sentence (strength 0.05-0.15)
- "punch_in": instantly tighter framing for a punchline (strength 0.05-0.15)
- "zoom_out": release the frame after tension (strength 0.05-0.15)
- "zoom_pulse": quick in-and-out accent (strength 0.04-0.10)
- "color_pop": boost contrast and saturation briefly (strength 0.2-1.0)
- "warm": warm the colour balance for a nostalgic beat (strength 0.2-1.0)
- "cool": cool the colour balance for a serious beat (strength 0.2-1.0)
- "grain": film grain for a raw, documentary beat (strength 0.2-1.0)
- "shake": a short camera shake on an impact (strength 0.3-1.0)
- "bw_moment": black and white for a beat (strength 1.0)
- "flash": one-frame brightness flash on a hit (strength 1.0)
- "vignette": vignette for a serious or reflective beat (strength 1.0)

Rules:
- Times are seconds from the start of THIS clip: 0 <= start < end <= {duration:.2f}.
- Keep each effect 0.3-4 seconds (zooms at most 8).
- Do not overlap effects. Do not add an effect at 0.0 unless it is the hook.
- Fewer is better. An empty list is a valid answer.
- {caption_rule}

Return JSON only:
{{"edits": [{{"type": "zoom_in", "start": 1.2, "end": 3.4, "strength": 0.08}}]}}
"""


class EffectsError(Exception):
    """Raised when an edit plan cannot be applied."""


def normalize_edits(edits, duration: float, has_captions: bool = False) -> "list[dict]":
    """Validate and clamp a raw edit list into a start-sorted, safe plan."""
    if not isinstance(edits, list) or duration <= 0:
        return []

    cleaned = []
    for entry in edits:
        if not isinstance(entry, dict):
            continue
        effect_type = str(entry.get("type", "")).strip().lower()
        limits = EFFECT_LIMITS.get(effect_type)
        if not limits:
            continue
        if has_captions and limits["zoom"]:
            # burning captions already re-frames the picture; a zoom would crop them
            continue
        try:
            start = float(entry.get("start", 0.0))
            end = float(entry.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        start = max(0.0, min(start, duration))
        end = max(0.0, min(end, duration))
        if end - start < MIN_EFFECT_SECONDS:
            continue
        if limits["zoom"] and end - start > MAX_ZOOM_SECONDS:
            end = start + MAX_ZOOM_SECONDS
        try:
            strength = float(entry.get("strength") or 0.0)
        except (TypeError, ValueError):
            strength = 0.0
        if strength <= 0.0:
            strength = limits["default_strength"]
        strength = min(strength, limits["max_strength"])
        cleaned.append(
            {"type": effect_type, "start": start, "end": end, "strength": strength}
        )

    cleaned.sort(key=lambda e: (e["start"], e["end"]))

    result = []
    last_zoom_end = -1.0
    flash_count = 0
    for entry in cleaned:
        if EFFECT_LIMITS[entry["type"]]["zoom"]:
            if entry["start"] < last_zoom_end:
                continue
            last_zoom_end = entry["end"]
        if entry["type"] == "flash":
            if flash_count >= 2:
                continue
            flash_count += 1
        result.append(entry)
        if len(result) >= MAX_EDITS:
            break
    return result


def _zoom_term(entry: dict, fps: float) -> str:
    start_frame = int(round(entry["start"] * fps))
    end_frame = max(start_frame + 2, int(round(entry["end"] * fps)))
    span = end_frame - start_frame
    strength = entry["strength"]
    gate = "between(on,{},{})".format(start_frame, end_frame)
    if entry["type"] == "zoom_in":
        return "{:.4f}*clip((on-{})/{},0,1)*{}".format(
            strength, start_frame, span, gate
        )
    if entry["type"] == "zoom_pulse":
        mid = (start_frame + end_frame) / 2.0
        half = max(span / 2.0, 1.0)
        return "{:.4f}*(1-abs((on-{:.1f})/{:.1f}))*{}".format(
            strength, mid, half, gate
        )
    if entry["type"] == "zoom_out":
        return "{:.4f}*(1-clip((on-{})/{},0,1))*{}".format(
            strength, start_frame, span, gate
        )
    return "{:.4f}*{}".format(strength, gate)


def build_filter_string(
    edits,
    duration: float,
    fps: float,
    width: int,
    height: int,
    has_captions: bool = False,
) -> "tuple[str | None, list[dict]]":
    """Build a ``-vf`` string. Returns ``(None, [])`` when nothing is usable."""
    applied = normalize_edits(edits, duration, has_captions=has_captions)
    if not applied:
        return None, []

    fps = float(fps) if fps and fps > 0 else 30.0
    width = int(width or 1080)
    height = int(height or 1920)

    color_filters = []
    prefix_filters = []
    zoom_terms = []
    for entry in applied:
        start, end, strength = entry["start"], entry["end"], entry["strength"]
        if EFFECT_LIMITS[entry["type"]]["zoom"]:
            zoom_terms.append(_zoom_term(entry, fps))
        elif entry["type"] == "shake":
            # A hand-held jolt: crop a little larger and slide the window on a
            # sine wave, then restore the frame size for the layers after it.
            amplitude = 0.006 + 0.014 * strength
            prefix_filters.append(
                "crop=w=iw*0.92:h=ih*0.92:"
                "x='(iw-ow)/2+iw*{:.4f}*sin(2*PI*t*11)*between(t,{:.2f},{:.2f})':"
                "y='(ih-oh)/2+ih*{:.4f}*sin(2*PI*t*7.7+1)*between(t,{:.2f},{:.2f})',"
                "scale={}:{}".format(
                    amplitude, start, end, amplitude, start, end, width, height
                )
            )
        elif entry["type"] == "grain":
            amount = max(2, int(round(8 + 30 * strength)))
            color_filters.append(
                "noise=alls={}:allf=t+u:enable='between(t,{:.2f},{:.2f})'".format(
                    amount, start, end
                )
            )
        elif entry["type"] in ("warm", "cool"):
            sign = 1.0 if entry["type"] == "warm" else -1.0
            amount = 0.12 * strength * sign
            color_filters.append(
                "colorbalance=rs={:.2f}:gs={:.2f}:bs={:.2f}:enable='between(t,{:.2f},{:.2f})'".format(
                    amount * 0.5, amount * 0.15, -amount * 0.5, start, end
                )
            )
        elif entry["type"] == "color_pop":
            contrast = 1.0 + 0.15 * strength
            saturation = 1.0 + 0.6 * strength
            color_filters.append(
                "eq=contrast={:.2f}:saturation={:.2f}:enable='between(t,{:.2f},{:.2f})'".format(
                    contrast, saturation, start, end
                )
            )
        elif entry["type"] == "bw_moment":
            color_filters.append(
                "hue=s=0:enable='between(t,{:.2f},{:.2f})'".format(start, end)
            )
        elif entry["type"] == "flash":
            flash_end = min(start + FLASH_SECONDS, end)
            color_filters.append(
                "eq=brightness=0.35:enable='between(t,{:.2f},{:.2f})'".format(
                    start, flash_end
                )
            )
        elif entry["type"] == "vignette":
            color_filters.append(
                "vignette=angle=PI/4.5:enable='between(t,{:.2f},{:.2f})'".format(
                    start, end
                )
            )

    parts = prefix_filters + color_filters
    if zoom_terms:
        z_expression = "1+" + "+".join(zoom_terms)
        parts.append(
            "zoompan=z='{}':x='iw/2-(iw/zoom)/2':y='ih*{}-(ih/zoom)/2'"
            ":d=1:fps={:g}:s={}x{}".format(
                z_expression, ZOOM_CENTER_Y, fps, width, height
            )
        )

    if not parts:
        return None, []
    return ",".join(parts), applied


def build_punch_in_filter(
    times,
    fps: float = 60.0,
    width: int = 1080,
    height: int = 1920,
    base: float = 1.02,
    strength: float = 0.06,
    hold: float = 2.5,
) -> "str | None":
    """The campaign punch-in cadence: 102% -> 108% on each beat.

    ``times`` are seconds relative to the clip; each one starts a rapid push
    from ``base`` to ``base + strength`` that holds for ``hold`` seconds. This is
    the edit used on talking-head cuts, independent of the AI edit plan.
    """
    usable = sorted({round(float(t), 3) for t in (times or ()) if float(t) >= 0})
    if not usable:
        return None
    fps = float(fps) if fps and fps > 0 else 30.0
    terms = []
    for moment in usable:
        start_frame = int(round(moment * fps))
        ramp = max(4.0, fps * 0.12)
        hold_frames = max(2, int(round(hold * fps)))
        gate = "between(on,{}, {})".format(start_frame, start_frame + hold_frames)
        terms.append(
            "{:.4f}*clip((on-{})/{:.1f},0,1)*{}".format(
                strength, start_frame, ramp, gate
            )
        )
    expression = "{:.4f}+".format(base) + "+".join(terms)
    return (
        "zoompan=z='{}':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'"
        ":d=1:fps={:g}:s={}x{}".format(expression, fps, int(width), int(height))
    )


def probe_video_info(video_file_path: str) -> "dict":
    """Return width, height, fps and duration of a video via ffprobe."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate:format=duration",
        "-of",
        "json",
        video_file_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS:
        raise EffectsError(
            "Could not probe '{}': {}".format(
                video_file_path, (result.stderr or "").strip()[:300]
            )
        )
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        numerator, _, denominator = str(stream.get("r_frame_rate") or "30/1").partition(
            "/"
        )
        fps = float(numerator) / float(denominator or 1)
        return {
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "fps": fps if fps > 0 else 30.0,
            "duration": float(payload.get("format", {}).get("duration") or 0.0),
        }
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise EffectsError("Unexpected ffprobe output: {}".format(result.stdout[:300])) from exc


def suggest_edits(
    client: LLMClient,
    transcript: str,
    duration: float,
    language: str = "en",
    has_captions: bool = False,
) -> "list[dict]":
    """Ask DeepSeek for an edit list, then validate it."""
    if not str(transcript or "").strip():
        return []
    caption_rule = (
        "This clip has burned-in captions, so zoom effects are NOT allowed; use "
        "colour, flash or vignette only."
        if has_captions
        else "Zoom effects are allowed."
    )
    payload = client.complete_json(
        _EFFECTS_PROMPT.format(
            transcript=str(transcript)[:8000],
            duration=max(0.1, float(duration)),
            language=language or "the transcript language",
            caption_rule=caption_rule,
        ),
        temperature=0.3,
        max_tokens=1024,
    )
    edits = payload.get("edits") if isinstance(payload, dict) else None
    return normalize_edits(edits, duration, has_captions=has_captions)


def apply_edits(
    video_file_path: str,
    edits,
    output_file_path: str,
    has_captions: bool = False,
    crf: "str | int" = "20",
    preset: str = "veryfast",
) -> "tuple[str, list[dict]]":
    """Render an edit plan onto a video. Returns (output path, applied edits)."""
    info = probe_video_info(video_file_path)
    filter_string, applied = build_filter_string(
        edits,
        info["duration"],
        info["fps"],
        info["width"],
        info["height"],
        has_captions=has_captions,
    )
    if not filter_string:
        raise EffectsError("The AI edit plan contained no usable effects.")

    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_file_path,
        "-vf",
        filter_string,
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        output_file_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS:
        raise EffectsError(
            "Applying the AI effects failed. ffmpeg said:\n{}".format(
                (result.stderr or "").strip()[-1200:]
            )
        )
    return output_file_path, applied
