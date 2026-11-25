"""
AI hook text and hook overlays.

The hook is a short scroll-stopping line burned at the top (or bottom) of a
clip. Text is rendered to a transparent PNG with Pillow and overlaid by ffmpeg,
which keeps emoji and non-Latin scripts working without drawtext escaping
nightmares.

DeepSeek writes the text (``generate_hook``); rendering is fully local.
"""

# standard library imports
from __future__ import annotations

import os
import subprocess

# current package imports
from .llm import LLMClient

# local package imports
from clipsai.captions.captions import probe_video_size

# 3rd party imports
from PIL import Image, ImageDraw, ImageFont

SUCCESS = 0

HOOK_STYLES = {
    "box": {"bg": (255, 255, 255, 240), "fg": (12, 12, 14, 255), "radius": 18},
    "dark": {"bg": (8, 8, 10, 225), "fg": (255, 255, 255, 255), "radius": 18},
    "yellow": {"bg": (255, 212, 0, 245), "fg": (10, 10, 10, 255), "radius": 18},
    "outline": {"bg": None, "fg": (255, 255, 255, 255), "radius": 0},
}

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size: int) -> "ImageFont.FreeTypeFont":
    """Load a bold font at ``size``, falling back to Pillow's default."""
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        from matplotlib import font_manager

        path = font_manager.findfont(
            font_manager.FontProperties(family="DejaVu Sans", weight="bold")
        )
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 - last resort below
        pass
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
    style: str = "box",
    max_lines: int = 3,
) -> "Image.Image":
    """
    Render hook text as a tightly cropped RGBA image for a ``width``-wide video.

    The image is transparent outside the text box so it can be overlaid directly.
    """
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("Hook text is empty.")
    if style not in HOOK_STYLES:
        raise ValueError(
            "Unknown hook style '{}'. Choose from: {}".format(
                style, ", ".join(HOOK_STYLES)
            )
        )

    width = max(320, int(width))
    max_box_width = width * 0.86
    base_size = max(30, int(round(96 * width / 1080.0)))

    font_size = base_size
    font = load_font(font_size)
    pad = max(10, int(font_size * 0.42))
    lines = wrap_text(text, font, max_box_width - 2 * pad)
    while len(lines) > max_lines and font_size > 26:
        font_size -= 4
        font = load_font(font_size)
        pad = max(10, int(font_size * 0.42))
        lines = wrap_text(text, font, max_box_width - 2 * pad)

    measure = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    line_widths = [measure.textlength(line, font=font) for line in lines]
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    box_width = int(min(max_box_width, max(line_widths) + 2 * pad))
    box_height = int(line_height * len(lines) + 2 * pad)

    config = HOOK_STYLES[style]
    image = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if config["bg"] is not None:
        draw.rounded_rectangle(
            [(0, 0), (box_width - 1, box_height - 1)],
            radius=config["radius"],
            fill=config["bg"],
        )

    stroke_width = 0 if config["bg"] is not None else max(2, font_size // 13)
    y = pad
    for line, line_width in zip(lines, line_widths):
        x = max(pad, int((box_width - line_width) / 2))
        draw.text(
            (x, y),
            line,
            font=font,
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


def burn_hook(
    video_file_path: str,
    text: str,
    output_file_path: str,
    style: str = "box",
    position: str = "top",
    crf: "str | int" = "20",
    preset: str = "veryfast",
) -> str:
    """Overlay a hook onto a video. Returns the output path."""
    if position not in {"top", "center", "bottom"}:
        raise ValueError("position must be 'top', 'center' or 'bottom'")

    width, _ = probe_video_size(video_file_path)
    hook_image = render_hook_png(text, width=width, style=style)
    png_path = os.path.splitext(output_file_path)[0] + ".hook.png"
    hook_image.save(png_path)

    if position == "top":
        y = "H*0.06"
    elif position == "center":
        y = "(H-h)/2"
    else:
        y = "H-h-H*0.12"

    filter_complex = (
        "[1:v]format=rgba[hook];"
        "[0:v][hook]overlay=(W-w)/2:{y}:eof_action=repeat[v]".format(y=y)
    )
    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_file_path,
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
        output_file_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS or not os.path.isfile(output_file_path):
        raise RuntimeError(
            "Burning the hook failed. ffmpeg said:\n{}".format(
                (result.stderr or "").strip()[-1200:]
            )
        )
    return output_file_path
