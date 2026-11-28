"""
AI hook text and hook overlays.

The hook is a short scroll-stopping line burned near the top (or bottom) of a
clip, often with a smaller "kicker" question above it. Text is rendered to a
transparent PNG with Pillow and overlaid by ffmpeg, which keeps emoji and
non-Latin scripts working without drawtext escaping nightmares.

DeepSeek writes the text (``generate_hook``); rendering is fully local.

Example
-------
>>> from clipsai.ai.hooks import render_hook_png
>>> image = render_hook_png("Coolest white boy since Mac Miller",
...                         kicker="Who knew Ad-Rock's son could rap?", style="card")
>>> image.size[0] <= 1080
True
"""

# standard library imports
from __future__ import annotations

import os
import subprocess

# current package imports
from .llm import LLMClient

# local package imports
from clipsai.captions.captions import probe_video_size
from clipsai.typography import load_font as _load_face

# 3rd party imports
from PIL import Image, ImageDraw

SUCCESS = 0

#: Card colours are authored in the same dark/yellow language as the captions.
HOOK_STYLES = {
    "box": {
        "bg": (255, 255, 255, 240),
        "fg": (12, 12, 14, 255),
        "radius": 18,
        "accent": None,
        "base_size": 64,
    },
    "dark": {
        "bg": (8, 8, 10, 225),
        "fg": (255, 255, 255, 255),
        "radius": 18,
        "accent": None,
        "base_size": 64,
    },
    "yellow": {
        "bg": (255, 212, 0, 245),
        "fg": (10, 10, 10, 255),
        "radius": 18,
        "accent": None,
        "base_size": 62,
    },
    "outline": {
        "bg": None,
        "fg": (255, 255, 255, 255),
        "radius": 0,
        "accent": None,
        "base_size": 72,
    },
    # The short-form card: a dark plate with a yellow rule, a white kicker
    # question and the payoff line in yellow.
    "card": {
        "bg": (12, 12, 16, 205),
        "fg": (255, 214, 10, 255),
        "kicker": (255, 255, 255, 255),
        "radius": 30,
        "accent": (255, 214, 10, 255),
        "base_size": 52,
    },
}

#: Anchor -> centre of the overlay as a fraction of the frame height.
HOOK_POSITIONS = {
    "top": 0.075,
    "upper": 0.17,
    "center": 0.5,
    "lower": 0.80,
    "bottom": 0.925,
}

DEFAULT_HOOK_STYLE = "card"
DEFAULT_HOOK_FONT = "Montserrat ExtraBold"
DEFAULT_HOOK_SECONDS = 4.0

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size: int, font: "str | None" = None) -> "object":
    """Load a bold font at ``size``, falling back to Pillow's default.

    ``font`` is a catalog key or family name (see :mod:`clipsai.typography`);
    when it cannot be resolved the host's Arial/DejaVu is used.
    """
    try:
        return _load_face(int(size), font)
    except Exception:  # noqa: BLE001 - rendering must not depend on a font file
        pass
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                from PIL import ImageFont

                return ImageFont.truetype(path, int(size))
            except OSError:
                continue
    try:
        from matplotlib import font_manager
        from PIL import ImageFont

        path = font_manager.findfont(
            font_manager.FontProperties(family="DejaVu Sans", weight="bold")
        )
        return ImageFont.truetype(path, int(size))
    except Exception:  # noqa: BLE001 - last resort below
        pass
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def wrap_text(text: str, font, max_width: float) -> "list[str]":
    """Greedy word wrap measured with the real font."""
    measure = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines: "list[str]" = []
    current = ""
    for word in str(text).split():
        trial = (current + " " + word).strip()
        if not current or measure.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_hook_png(
    text: str,
    width: int = 1080,
    style: str = DEFAULT_HOOK_STYLE,
    max_lines: int = 3,
    *,
    font: "str | None" = DEFAULT_HOOK_FONT,
    kicker: str = "",
    uppercase: bool = False,
    max_width_ratio: float = 0.86,
) -> "Image.Image":
    """
    Render hook text as a tightly cropped RGBA image for a ``width``-wide video.

    The image is transparent outside the text box so it can be overlaid directly.
    ``kicker`` is an optional smaller line above the hook (a question or a
    label); it is what makes the "card" style read as a designed plate.
    """
    text = " ".join(str(text or "").split())
    kicker = " ".join(str(kicker or "").split())
    if not text:
        raise ValueError("Hook text is empty.")
    if style not in HOOK_STYLES:
        raise ValueError(
            "Unknown hook style '{}'. Choose from: {}".format(
                style, ", ".join(HOOK_STYLES)
            )
        )

    width = max(320, int(width))
    max_box_width = width * float(max_width_ratio)
    config = HOOK_STYLES[style]
    base_size = max(30, int(round(config["base_size"] * width / 1080.0)))

    if uppercase:
        text = text.upper()
        kicker = kicker.upper()

    font_size = base_size
    face = load_font(font_size, font)
    pad = max(10, int(font_size * 0.42))
    lines = wrap_text(text, face, max_box_width - 2 * pad)
    while len(lines) > max_lines and font_size > 26:
        font_size -= 4
        face = load_font(font_size, font)
        pad = max(10, int(font_size * 0.42))
        lines = wrap_text(text, face, max_box_width - 2 * pad)

    kicker_size = max(20, int(round(font_size * 0.88)))
    kicker_face = load_font(kicker_size, font)
    kicker_lines = wrap_text(kicker, kicker_face, max_box_width - 2 * pad) if kicker else []

    measure = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    widths = [measure.textlength(line, font=face) for line in lines]
    widths += [measure.textlength(line, font=kicker_face) for line in kicker_lines]
    ascent, descent = face.getmetrics()
    line_height = ascent + descent
    kicker_ascent, kicker_descent = kicker_face.getmetrics()
    kicker_height = kicker_ascent + kicker_descent
    gap = max(4, int(font_size * 0.18)) if kicker_lines else 0

    box_width = int(min(max_box_width, max(widths) + 2 * pad))
    box_width = max(box_width, 2 * pad + 2)
    box_height = int(
        line_height * len(lines) + kicker_height * len(kicker_lines) + 2 * pad + gap
    )

    image = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if config["bg"] is not None:
        draw.rounded_rectangle(
            [(0, 0), (box_width - 1, box_height - 1)],
            radius=config["radius"],
            fill=config["bg"],
        )
    accent = config.get("accent")
    if accent and config["bg"] is not None:
        draw.rounded_rectangle(
            [(0, 0), (box_width - 1, max(3, int(round(font_size * 0.11))))],
            radius=3,
            fill=accent,
        )

    stroke_width = 0 if config["bg"] is not None else max(2, font_size // 13)
    y = pad
    kicker_colour = config.get("kicker", config["fg"])
    for line in kicker_lines:
        line_width = measure.textlength(line, font=kicker_face)
        x = max(pad, int((box_width - line_width) / 2))
        draw.text(
            (x, y),
            line,
            font=kicker_face,
            fill=kicker_colour,
            stroke_width=max(2, font_size // 18) if stroke_width else 0,
            stroke_fill=(0, 0, 0, 255),
        )
        y += kicker_height
    y += gap
    for line, line_width in zip(lines, widths[: len(lines)]):
        x = max(pad, int((box_width - line_width) / 2))
        draw.text(
            (x, y),
            line,
            font=face,
            fill=config["fg"],
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, 255),
        )
        y += line_height
    return image


def generate_hook(
    client: LLMClient,
    transcript: str,
    language: str = "en",
    title: str = "",
) -> str:
    """Ask DeepSeek for a hook of at most 10 words."""
    prompt = (
        "Write one scroll-stopping hook for this short video clip, in the same "
        "language as the transcript ({language}). At most 10 words. It must name "
        "the concrete payoff (a number, name, result or claim) and must not be "
        "clickbait the clip does not pay off. No quotation marks, no emoji.\n\n"
        "Existing title (optional): {title}\n\nTranscript:\n{transcript}\n\n"
        "Return JSON only: {{\"hook\": \"...\"}}"
    ).format(
        language=language or "the transcript language",
        title=title or "(none)",
        transcript=str(transcript)[:8000],
    )
    payload = client.complete_json(prompt, temperature=0.8, max_tokens=256)
    hook = ""
    if isinstance(payload, dict):
        hook = " ".join(str(payload.get("hook") or "").split())
    if not hook:
        raise ValueError("DeepSeek did not return a hook.")
    return " ".join(hook.split()[:10])


def _probe_video(video_file_path: str) -> "dict":
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "default=noprint_wrappers=1",
        video_file_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    values = {}
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    try:
        return {
            "width": int(values["width"]),
            "height": int(values["height"]),
            "duration": float(values.get("duration") or 0.0),
        }
    except (KeyError, ValueError):
        # size probing is enough for the overlay; duration is optional
        width, height = probe_video_size(video_file_path)
        return {"width": width, "height": height, "duration": 0.0}


def burn_hook(
    video_file_path: str,
    text: str,
    output_file_path: str,
    style: str = DEFAULT_HOOK_STYLE,
    position: str = "upper",
    crf: "str | int" = "20",
    preset: str = "veryfast",
    *,
    font: "str | None" = DEFAULT_HOOK_FONT,
    kicker: str = "",
    start: float = 0.0,
    end: "float | None" = None,
    fade: float = 0.0,
    uppercase: bool = False,
) -> str:
    """Overlay a hook onto a video. Returns the output path.

    ``start`` / ``end`` limit when the card is visible (``end`` defaults to the
    clip end, or ``start + 4s`` when ``start`` is given), which is how a hook
    stays an opening card instead of covering the whole clip.
    """
    if position not in HOOK_POSITIONS:
        raise ValueError(
            "position must be one of: {}".format(", ".join(HOOK_POSITIONS))
        )

    info = _probe_video(video_file_path)
    width, height = info["width"], info["height"]
    duration = info["duration"]
    hook_image = render_hook_png(
        text,
        width=width,
        style=style,
        font=font,
        kicker=kicker,
        uppercase=uppercase,
    )
    png_path = os.path.splitext(output_file_path)[0] + ".hook.png"
    hook_image.save(png_path)

    start = max(0.0, float(start or 0.0))
    if end is None:
        end = start + DEFAULT_HOOK_SECONDS if start > 0 else duration
    end = float(end)
    if duration:
        end = min(end, duration)
    if end <= start:
        end = start + 0.5

    anchor = HOOK_POSITIONS[position]
    y = int(max(0, min(height - hook_image.height, anchor * height - hook_image.height / 2)))
    enable = "between(t,{:.3f},{:.3f})".format(start, end)

    layers = ["format=rgba"]
    if fade and fade > 0:
        layers.append(
            "fade=t=in:st={:.3f}:d={:.3f}:alpha=1".format(start, float(fade))
        )
        layers.append(
            "fade=t=out:st={:.3f}:d={:.3f}:alpha=1".format(max(start, end - fade), float(fade))
        )
    filter_complex = "[1:v]{}[hook]".format(",".join(layers))
    filter_complex += (
        ";[0:v][hook]overlay=x=(W-w)/2:y={y}:enable='{enable}':eof_action=pass[v]"
    ).format(y=y, enable=enable)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_file_path,
        "-loop",
        "1",
        "-i",
        png_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
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
    ]
    # The looped PNG would otherwise outlast the clip; cut at the video's end.
    if duration:
        command += ["-t", "{:.3f}".format(duration)]
    command.append(output_file_path)

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS or not os.path.isfile(output_file_path):
        raise RuntimeError(
            "Burning the hook failed. ffmpeg said:\n{}".format(
                (result.stderr or "").strip()[-1200:]
            )
        )
    return output_file_path
