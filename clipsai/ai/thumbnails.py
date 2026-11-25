"""
Thumbnails: AI-written thumbnail text, rendered onto a real video frame.

DeepSeek writes the short text (2-5 words); the image is composed locally from
a frame of the video with Pillow, so no image-generation API is needed.
"""

# standard library imports
from __future__ import annotations

import os
import subprocess

# current package imports
from .effects import probe_video_info
from .hooks import load_font, wrap_text
from .llm import LLMClient

# 3rd party imports
from PIL import Image, ImageDraw

SUCCESS = 0
THUMB_WIDTH, THUMB_HEIGHT = 1280, 720
TEXT_POSITIONS = ("left", "right", "top", "bottom")


def _scrim(image: "Image.Image", position: str) -> "Image.Image":
    """Darken one side of the frame so text stays readable."""
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if position in ("left", "right"):
        span = width // 2
        for i in range(span):
            alpha = int(190 * (1 - i / float(span)))
            x = i if position == "left" else width - 1 - i
            draw.line([(x, 0), (x, height)], fill=(0, 0, 0, alpha))
    else:
        span = height // 2
        for i in range(span):
            alpha = int(190 * (1 - i / float(span)))
            y = i if position == "top" else height - 1 - i
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def extract_frame(video_file_path: str, frame_file_path: str, time_seconds: float) -> str:
    """Extract one frame, cropped to 1280x720."""
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        "{:.3f}".format(max(0.0, float(time_seconds))),
        "-i",
        video_file_path,
        "-frames:v",
        "1",
        "-vf",
        "scale={}:{}:force_original_aspect_ratio=increase,crop={}:{}".format(
            THUMB_WIDTH, THUMB_HEIGHT, THUMB_WIDTH, THUMB_HEIGHT
        ),
        "-q:v",
        "2",
        frame_file_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS or not os.path.isfile(frame_file_path):
        raise RuntimeError(
            "Could not extract a thumbnail frame. ffmpeg said:\n{}".format(
                (result.stderr or "").strip()[-800:]
            )
        )
    return frame_file_path


def create_thumbnail(
    video_file_path: str,
    text: str,
    output_file_path: str,
    position: str = "left",
    time_ratio: float = 0.35,
) -> str:
    """
    Compose a 1280x720 thumbnail from a frame plus ``text``.

    ``position`` places the text block: left, right, top or bottom.
    ``time_ratio`` selects the frame (0 = first frame, 1 = last).
    """
    if position not in TEXT_POSITIONS:
        raise ValueError(
            "position must be one of: {}".format(", ".join(TEXT_POSITIONS))
        )
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("Thumbnail text is empty.")

    info = probe_video_info(video_file_path)
    timestamp = max(0.0, info["duration"] * float(time_ratio))
    frame_path = os.path.splitext(output_file_path)[0] + ".frame.jpg"
    extract_frame(video_file_path, frame_path, timestamp)

    base = Image.open(frame_path).convert("RGB")
    composed = _scrim(base, position).convert("RGB")
    draw = ImageDraw.Draw(composed)

    margin = 64
    if position in ("left", "right"):
        max_width = int(THUMB_WIDTH * 0.48)
        max_height = THUMB_HEIGHT - 2 * margin
    else:
        max_width = THUMB_WIDTH - 2 * margin
        max_height = int(THUMB_HEIGHT * 0.45)

    font_size = 132
    font = load_font(font_size)
    lines = wrap_text(text, font, max_width)
    while font_size > 34 and (
        len(lines) > 3
        or (font.getmetrics()[0] + font.getmetrics()[1]) * len(lines) > max_height
    ):
        font_size -= 8
        font = load_font(font_size)
        lines = wrap_text(text, font, max_width)

    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    block_height = line_height * len(lines)

    if position == "left":
        x, y = margin, (THUMB_HEIGHT - block_height) // 2
    elif position == "right":
        widest = max(draw.textlength(line, font=font) for line in lines)
        x, y = THUMB_WIDTH - margin - int(widest), (THUMB_HEIGHT - block_height) // 2
    elif position == "top":
        widest = max(draw.textlength(line, font=font) for line in lines)
        x, y = max(margin, int((THUMB_WIDTH - widest) / 2)), margin
    else:
        widest = max(draw.textlength(line, font=font) for line in lines)
        x = max(margin, int((THUMB_WIDTH - widest) / 2))
        y = THUMB_HEIGHT - margin - block_height

    stroke = max(3, font_size // 16)
    for line in lines:
        draw.text(
            (x, y),
            line.upper(),
            font=font,
            fill=(255, 255, 255),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0),
        )
        y += line_height

    composed.save(output_file_path, format="JPEG", quality=92)
    try:
        os.remove(frame_path)
    except OSError:
        pass
    return output_file_path


def generate_thumbnail_text(
    client: LLMClient,
    transcript: str,
    language: str = "en",
) -> str:
    """Ask DeepSeek for 2-5 words to put on the thumbnail."""
    prompt = (
        "Write the text for a video thumbnail, in the same language as the "
        "transcript ({language}). 2-5 words, maximum 40 characters, no emoji, "
        "no punctuation at the end, no clickbait the transcript does not pay off.\n\n"
        "Transcript:\n{transcript}\n\n"
        "Return JSON only: {{\"thumbnail_text\": \"...\"}}"
    ).format(
        language=language or "the transcript language",
        transcript=str(transcript)[:8000],
    )
    payload = client.complete_json(prompt, temperature=0.7, max_tokens=128)
    text = ""
    if isinstance(payload, dict):
        text = " ".join(str(payload.get("thumbnail_text") or "").split())
    if not text:
        raise ValueError("DeepSeek did not return thumbnail text.")
    return text[:40]
