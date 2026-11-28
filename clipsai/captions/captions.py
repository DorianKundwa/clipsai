"""
Word-timed captions for clips.

Builds caption cues from a ClipsAI ``Transcription`` (whose word-level timings
come from WhisperX), writes ``.srt`` / ``.ass`` subtitle files, and burns the
captions onto a rendered clip with ffmpeg (libass).

Captions are timed relative to the start of the clip, so the same cues can be
burned on a trimmed clip or on a reframed (9:16) clip.

Example
-------
>>> from clipsai import Transcriber, build_cues, burn_captions
>>> transcription = Transcriber().transcribe(audio_file_path="talk.mp4")
>>> cues = build_cues(transcription, start_time=12.0, end_time=42.0, preset="kinetic")
>>> burn_captions("clip.mp4", cues, "clip_captioned.mp4", preset="kinetic")

Presets
-------
``bold``     white caps, yellow active word, heavy outline (default)
``kinetic``  the short-form look: Montserrat ExtraBold, 52 px, yellow active
             word that pops in, tight 5-word lines
``shorts``   bigger kinetic type for fast cuts
``clean``    sentence case, thin outline, no active-word highlight
``lime``     white caps, lime green active word
``pill``     white caps in a solid purple box
``boxed``    black caps in a yellow box
``impact``   Archivo Black caps, white on a thick black outline
``editorial`` Noto Serif Bold, sentence case, quiet and documentary
``oneword``  one giant word at a time

Every preset can be overridden per render (font, size, position, pop) from the
Studio, so one job can mix a kinetic TikTok cut and a quieter YouTube cut.
"""

# standard library imports
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, replace

# local package imports
from clipsai.typography import font_family, fonts_dir

# ffmpeg return code of 0 means success
SUCCESS = 0

# ASS colours are &HAABBGGRR (alpha, blue, green, red)
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
YELLOW = "&H0000FFFF"
LIME = "&H0000FFA3"
PURPLE = "&H00ED3A7C"
ORANGE = "&H00008CFF"

#: Vertical anchor of a caption block -> ASS alignment (numpad layout).
CAPTION_POSITIONS = {
    "bottom": 2,
    "center": 5,
    "top": 8,
}

#: Default distance from the frame edge for each anchor, in 1080x1920 pixels.
_POSITION_MARGIN = {"bottom": 110, "center": 0, "top": 120}


class CaptionError(Exception):
    """Raised when captions cannot be built, written, or burned."""


@dataclass(frozen=True)
class CaptionPreset:
    """Visual style and line-breaking rules for a caption preset."""

    font: str = "Montserrat ExtraBold"
    font_size: int = 72
    bold: bool = True
    primary_colour: str = WHITE
    outline_colour: str = BLACK
    back_colour: str = BLACK
    highlight_colour: "str | None" = YELLOW
    outline: float = 4.5
    shadow: float = 0.0
    border_style: int = 1
    uppercase: bool = True
    max_words: int = 4
    max_chars: int = 30
    max_duration: float = 4.0
    margin_v: int = 110
    spacing: float = 0.0
    align: str = "bottom"
    #: Scale the active word briefly, the "kinetic" pop. 1.0 disables it.
    pop_scale: float = 1.0
    pop_ms: int = 120


CAPTION_PRESETS: "dict[str, CaptionPreset]" = {
    "bold": CaptionPreset(),
    "kinetic": CaptionPreset(
        font_size=52,
        highlight_colour=YELLOW,
        outline=4.0,
        max_words=5,
        max_chars=26,
        max_duration=3.2,
        margin_v=560,
        pop_scale=1.12,
        pop_ms=110,
    ),
    "shorts": CaptionPreset(
        font_size=64,
        highlight_colour=YELLOW,
        outline=5.0,
        max_words=4,
        max_chars=22,
        max_duration=2.8,
        margin_v=620,
        pop_scale=1.16,
        pop_ms=90,
    ),
    "clean": CaptionPreset(
        font="Arial",
        font_size=64,
        bold=False,
        highlight_colour=None,
        outline=2.0,
        shadow=1.0,
        uppercase=False,
        max_words=6,
        max_chars=42,
        margin_v=90,
    ),
    "lime": CaptionPreset(
        font_size=72,
        highlight_colour=LIME,
        outline=4.5,
    ),
    "pill": CaptionPreset(
        border_style=3,
        outline_colour=PURPLE,
        back_colour=PURPLE,
        highlight_colour=None,
        outline=10.0,
        shadow=0.0,
        margin_v=100,
    ),
    "boxed": CaptionPreset(
        font="Archivo Black",
        font_size=56,
        primary_colour=BLACK,
        border_style=3,
        outline_colour=YELLOW,
        back_colour=YELLOW,
        highlight_colour=None,
        outline=12.0,
        max_words=4,
        max_chars=24,
        margin_v=100,
    ),
    "impact": CaptionPreset(
        font="Archivo Black",
        font_size=68,
        highlight_colour=None,
        outline=6.0,
        max_words=3,
        max_chars=20,
        margin_v=130,
    ),
    "editorial": CaptionPreset(
        font="Noto Serif",
        font_size=56,
        highlight_colour=None,
        outline=2.0,
        shadow=2.0,
        uppercase=False,
        max_words=7,
        max_chars=40,
        max_duration=5.0,
        margin_v=100,
    ),
    "oneword": CaptionPreset(
        font_size=120,
        highlight_colour=None,
        outline=6.0,
        max_words=1,
        max_chars=16,
        margin_v=300,
    ),
}


@dataclass
class CaptionWord:
    """A single spoken word, timed relative to the clip start."""

    text: str
    start: float
    end: float


@dataclass
class CaptionCue:
    """One on-screen caption line."""

    words: "list[CaptionWord]" = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


def _resolve_preset(preset: "str | CaptionPreset") -> CaptionPreset:
    if isinstance(preset, CaptionPreset):
        return preset
    key = str(preset).strip().lower()
    if key not in CAPTION_PRESETS:
        raise CaptionError(
            "Unknown caption preset '{}'. Choose one of: {}".format(
                preset, ", ".join(CAPTION_PRESETS)
            )
        )
    return CAPTION_PRESETS[key]


def caption_preset_names() -> "tuple[str, ...]":
    """Preset names in menu order."""
    return tuple(CAPTION_PRESETS)


def caption_preset(
    preset: "str | CaptionPreset" = "bold",
    *,
    font: "str | None" = None,
    font_size: "int | None" = None,
    position: "str | None" = None,
    pop: "bool | None" = None,
) -> CaptionPreset:
    """Resolve a preset and apply per-render overrides.

    ``position`` moves the caption block (bottom / center / top) and swaps in
    that anchor's default margin, unless the preset already chose one.
    """
    config = _resolve_preset(preset)
    changes = {}
    if font:
        changes["font"] = font
    if font_size:
        changes["font_size"] = max(16, int(font_size))
    if position:
        key = str(position).strip().lower()
        if key not in CAPTION_POSITIONS:
            raise CaptionError(
                "Unknown caption position '{}'. Choose one of: {}.".format(
                    position, ", ".join(CAPTION_POSITIONS)
                )
            )
        changes["align"] = key
        if key != config.align:
            changes["margin_v"] = _POSITION_MARGIN[key]
    if pop is not None:
        changes["pop_scale"] = 1.12 if pop else 1.0
    return replace(config, **changes) if changes else config


def _ends_sentence(text: str) -> bool:
    stripped = text.rstrip("\"'”’)]}")
    return bool(stripped) and stripped[-1] in ".!?…"


def _clip_words(
    word_info: "list[dict]", start_time: float, end_time: float
) -> "list[CaptionWord]":
    """Convert transcript word info into clip-relative, clamped words."""
    words = []
    for info in word_info:
        text = str(info.get("word", "")).strip()
        if not text:
            continue
        word_start = info.get("start_time")
        word_end = info.get("end_time")
        word_start = start_time if word_start is None else float(word_start)
        word_end = word_start + 0.2 if word_end is None else float(word_end)
        word_start = max(start_time, min(word_start, end_time))
        word_end = max(start_time, min(word_end, end_time))
        if word_end <= word_start:
            # WhisperX occasionally reports zero-length words at boundaries
            continue
        words.append(
            CaptionWord(
                text=text,
                start=round(word_start - start_time, 3),
                end=round(word_end - start_time, 3),
            )
        )
    return words


def _group_words(
    words: "list[CaptionWord]", preset: CaptionPreset, max_gap: float
) -> "list[CaptionCue]":
    cues: "list[CaptionCue]" = []
    current: "list[CaptionWord]" = []

    def flush() -> None:
        nonlocal current
        if current:
            cues.append(CaptionCue(current))
            current = []

    for word in words:
        if current:
            candidate = " ".join([w.text for w in current] + [word.text])
            too_long = (
                len(current) >= preset.max_words
                or len(candidate) > preset.max_chars
                or word.start - current[-1].end > max_gap
                or word.end - current[0].start > preset.max_duration
            )
            if too_long:
                flush()
        current.append(word)
        if _ends_sentence(word.text):
            flush()

    flush()
    return cues


def build_cues(
    transcription,
    start_time: float = 0.0,
    end_time: "float | None" = None,
    preset: "str | CaptionPreset" = "bold",
    max_gap: float = 0.8,
) -> "list[CaptionCue]":
    """
    Build caption cues for a time range of a transcription.

    Parameters
    ----------
    transcription: clipsai.Transcription
        A transcription with word-level timings.
    start_time: float
        Start of the clip in seconds; cue times are returned relative to it.
    end_time: float or None
        End of the clip in seconds. None uses the end of the transcription.
    preset: str or CaptionPreset
        A preset name from ``CAPTION_PRESETS`` (or a custom preset).
    max_gap: float
        A pause longer than this (seconds) starts a new cue.

    Returns
    -------
    list[CaptionCue]
    """
    config = _resolve_preset(preset)
    start = max(0.0, float(start_time))
    transcript_end = float(transcription.end_time)
    end = transcript_end if end_time is None else min(float(end_time), transcript_end)

    if end <= start:
        raise CaptionError(
            "Caption end time ({:.2f}s) must be greater than the start time "
            "({:.2f}s).".format(end, start)
        )

    words = _clip_words(transcription.get_word_info(start, end), start, end)
    return _group_words(words, config, max_gap=max_gap)


def _srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return "{:02d}:{:02d}:{:02d},{:03d}".format(hours, minutes, secs, millis)


def _ass_time(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return "{}:{:02d}:{:02d}.{:02d}".format(hours, minutes, secs, centis)


def _ass_text(text: str, uppercase: bool) -> str:
    if uppercase:
        text = text.upper()
    # braces start ASS override blocks; newlines would break the event line
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _inline_colour(colour: str) -> str:
    return "{\\c" + colour.strip().rstrip("&") + "&}"


def _pop_tags(scale: float, milliseconds: int) -> str:
    if scale <= 1.0:
        return ""
    return "{{\\fscx{scale}\\fscy{scale}\\t(0,{ms},\\fscx100\\fscy100)".format(
        scale=int(round(scale * 100)), ms=int(milliseconds)
    )


def to_srt(cues: "list[CaptionCue]") -> str:
    """Render cues as an SRT subtitle document."""
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "{}\n{} --> {}\n{}\n".format(
                index, _srt_time(cue.start), _srt_time(cue.end), cue.text.strip()
            )
        )
    return "\n".join(blocks)


def to_ass(
    cues: "list[CaptionCue]",
    preset: "str | CaptionPreset" = "bold",
    width: int = 1080,
    height: int = 1920,
    *,
    font: "str | None" = None,
    font_size: "int | None" = None,
    position: "str | None" = None,
    pop: "bool | None" = None,
) -> str:
    """Render cues as an ASS subtitle document sized for the target video."""
    config = caption_preset(
        preset, font=font, font_size=font_size, position=position, pop=pop
    )

    # preset values are authored for a 1080x1920 canvas
    scale = float(height) / 1920.0
    size = max(12, int(round(config.font_size * scale)))
    outline = round(config.outline * scale, 2)
    shadow = round(config.shadow * scale, 2)
    margin_v = max(0, int(round(config.margin_v * scale)))
    alignment = CAPTION_POSITIONS.get(config.align, 2)
    family = font_family(config.font)

    header = [
        "[Script Info]",
        "; Generated by ClipsAI",
        "ScriptType: v4.00+",
        "PlayResX: {}".format(int(width)),
        "PlayResY: {}".format(int(height)),
        # smart wrapping: a long cue wraps to a second line instead of
        # running off the frame when libass has no manual line breaks
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        (
            "Style: Default,{font},{size},{primary},{primary},{outline_colour},"
            "{back_colour},{bold},0,0,0,100,100,{spacing},0,{border_style},{outline},"
            "{shadow},{alignment},40,40,{margin_v},1"
        ).format(
            font=family,
            size=size,
            primary=config.primary_colour,
            outline_colour=config.outline_colour,
            back_colour=config.back_colour,
            bold=-1 if config.bold else 0,
            spacing=config.spacing,
            border_style=config.border_style,
            outline=outline,
            shadow=shadow,
            alignment=alignment,
            margin_v=margin_v,
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]

    pop_tags = _pop_tags(config.pop_scale, config.pop_ms)
    events = []
    for cue in cues:
        if not cue.words:
            continue
        highlight = config.highlight_colour
        active_word = highlight is not None or config.pop_scale > 1.0
        if not active_word or len(cue.words) == 1:
            text = " ".join(_ass_text(w.text, config.uppercase) for w in cue.words)
            events.append(
                "Dialogue: 0,{},{},Default,,0,0,0,,{}".format(
                    _ass_time(cue.start), _ass_time(cue.end), text
                )
            )
            continue

        # one event per active word so only the word being spoken is highlighted
        for i, word in enumerate(cue.words):
            event_start = word.start
            if i + 1 < len(cue.words):
                event_end = cue.words[i + 1].start
            else:
                event_end = cue.end
            if event_end <= event_start:
                event_end = min(cue.end, event_start + 0.2)
            if event_end <= event_start:
                continue

            parts = []
            for j, token in enumerate(cue.words):
                rendered = _ass_text(token.text, config.uppercase)
                if j == i:
                    rendered = (
                        (_inline_colour(highlight) if highlight else "")
                        + (pop_tags + "}" if pop_tags else "")
                        + rendered
                        + (_inline_colour(config.primary_colour) if highlight else "")
                    )
                parts.append(rendered)

            events.append(
                "Dialogue: 0,{},{},Default,,0,0,0,,{}".format(
                    _ass_time(event_start), _ass_time(event_end), " ".join(parts)
                )
            )

    return "\n".join(header + events) + "\n"


def write_srt(cues: "list[CaptionCue]", file_path: str) -> str:
    """Write cues to ``file_path`` as SRT and return the path."""
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write(to_srt(cues))
    return file_path


def write_ass(
    cues: "list[CaptionCue]",
    file_path: str,
    preset: "str | CaptionPreset" = "bold",
    width: int = 1080,
    height: int = 1920,
    *,
    font: "str | None" = None,
    font_size: "int | None" = None,
    position: "str | None" = None,
    pop: "bool | None" = None,
) -> str:
    """Write cues to ``file_path`` as ASS and return the path."""
    with open(file_path, "w", encoding="utf-8-sig") as handle:
        handle.write(
            to_ass(
                cues,
                preset=preset,
                width=width,
                height=height,
                font=font,
                font_size=font_size,
                position=position,
                pop=pop,
            )
        )
    return file_path


def probe_video_size(video_file_path: str) -> "tuple[int, int]":
    """Return ``(width, height)`` of the first video stream via ffprobe."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        video_file_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == SUCCESS:
        try:
            width, height = result.stdout.strip().split("x")[:2]
            return int(width), int(height)
        except (ValueError, IndexError):
            pass
    raise CaptionError(
        "Could not read the video size of '{}'. ffprobe output: {}".format(
            video_file_path, (result.stderr or result.stdout).strip()[:400]
        )
    )


def escape_filter_path(path: str) -> str:
    """Escape a path for a ``subtitles=`` / ``ass=`` filter argument."""
    # ffmpeg filter paths need forward slashes and an escaped drive colon on Windows
    path = os.path.abspath(path).replace("\\", "/")
    return path.replace(":", "\\:").replace("'", "\\'")


def _subtitles_filter(ass_file_path: str, fontsdir: "str | None" = None) -> str:
    parts = ["filename='{}'".format(escape_filter_path(ass_file_path))]
    # Without fontsdir libass silently falls back to DejaVu for a bundled face
    # and the burned captions do not match the previewed style.
    directory = fontsdir if fontsdir is not None else fonts_dir()
    if directory and os.path.isdir(directory):
        parts.append("fontsdir='{}'".format(escape_filter_path(directory)))
    return "subtitles=" + ":".join(parts)


def burn_captions(
    video_file_path: str,
    cues: "list[CaptionCue]",
    output_file_path: str,
    preset: "str | CaptionPreset" = "bold",
    crf: "str | int" = "20",
    preset_ffmpeg: str = "veryfast",
    *,
    font: "str | None" = None,
    font_size: "int | None" = None,
    position: "str | None" = None,
    pop: "bool | None" = None,
    fontsdir: "str | None" = None,
    audio_codec: str = "copy",
) -> str:
    """
    Burn cues onto a video with ffmpeg and write the result to ``output_file_path``.

    The matching ``.ass`` file is written next to the output so it can be reused
    or re-burned at a different quality.

    Returns the output path. Raises ``CaptionError`` on failure.
    """
    if not cues:
        raise CaptionError("There are no caption cues to burn.")
    if not os.path.isfile(video_file_path):
        raise CaptionError("Video file '{}' does not exist.".format(video_file_path))

    width, height = probe_video_size(video_file_path)
    ass_path = os.path.splitext(output_file_path)[0] + ".ass"
    write_ass(
        cues,
        ass_path,
        preset=preset,
        width=width,
        height=height,
        font=font,
        font_size=font_size,
        position=position,
        pop=pop,
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_file_path,
        "-vf",
        _subtitles_filter(ass_path, fontsdir=fontsdir),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset_ffmpeg,
        "-c:a",
        audio_codec,
        "-movflags",
        "+faststart",
        output_file_path,
    ]
    if audio_codec == "aac":
        command[-4:-4] = ["-b:a", "192k", "-ar", "48000"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != SUCCESS or not os.path.isfile(output_file_path):
        raise CaptionError(
            "Burning captions onto '{}' failed. ffmpeg said:\n{}".format(
                video_file_path, (result.stderr or result.stdout).strip()[-1500:]
            )
        )
    return output_file_path
