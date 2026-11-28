from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai.clips import AIClip, AIClipError, AIClipFinder
    from .ai.llm import LLMClient, LLMError, MissingAPIKeyError
    from .ai.translate import translate_cues
    from .captions.captions import (
        CAPTION_PRESETS,
        CaptionCue,
        CaptionError,
        CaptionPreset,
        CaptionWord,
        build_cues,
        burn_captions,
        to_ass,
        to_srt,
        write_ass,
        write_srt,
    )
    from .clip.clip import Clip
    from .clip.clipfinder import ClipFinder
    from .media.audio_file import AudioFile
    from .media.audiovideo_file import AudioVideoFile
    from .media.editor import MediaEditor
    from .media.video_file import VideoFile
    from .render import (
        EXPORT_PROFILES,
        EXPORT_PROFILE_NAMES,
        GRADE_NAMES,
        GRADES,
        PAD_MODES,
        CropWindow,
        assert_output,
        export_clip,
        finish_clip,
        measure_loudness,
        parse_crop,
        verify_output,
    )
    from .resize.crops import Crops
    from .resize.resize import resize
    from .resize.segment import Segment
    from .transcribe.transcriber import Transcriber
    from .transcribe.transcription import Transcription
    from .transcribe.transcription_element import Character, Sentence, Word
    from .typography import (
        available_fonts,
        font_family,
        fonts_dir,
        load_font,
        resolve_font,
    )

_LAZY_EXPORTS = {
    "AIClip": (".ai.clips", "AIClip"),
    "AIClipError": (".ai.clips", "AIClipError"),
    "AIClipFinder": (".ai.clips", "AIClipFinder"),
    "AudioFile": (".media.audio_file", "AudioFile"),
    "AudioVideoFile": (".media.audiovideo_file", "AudioVideoFile"),
    "CAPTION_PRESETS": (".captions.captions", "CAPTION_PRESETS"),
    "CaptionCue": (".captions.captions", "CaptionCue"),
    "CaptionError": (".captions.captions", "CaptionError"),
    "CaptionPreset": (".captions.captions", "CaptionPreset"),
    "CaptionWord": (".captions.captions", "CaptionWord"),
    "Character": (".transcribe.transcription_element", "Character"),
    "Clip": (".clip.clip", "Clip"),
    "ClipFinder": (".clip.clipfinder", "ClipFinder"),
    "CropWindow": (".render", "CropWindow"),
    "Crops": (".resize.crops", "Crops"),
    "EXPORT_PROFILES": (".render", "EXPORT_PROFILES"),
    "EXPORT_PROFILE_NAMES": (".render", "EXPORT_PROFILE_NAMES"),
    "GRADES": (".render", "GRADES"),
    "GRADE_NAMES": (".render", "GRADE_NAMES"),
    "PAD_MODES": (".render", "PAD_MODES"),
    "assert_output": (".render", "assert_output"),
    "export_clip": (".render", "export_clip"),
    "finish_clip": (".render", "finish_clip"),
    "measure_loudness": (".render", "measure_loudness"),
    "parse_crop": (".render", "parse_crop"),
    "verify_output": (".render", "verify_output"),
    "LLMClient": (".ai.llm", "LLMClient"),
    "LLMError": (".ai.llm", "LLMError"),
    "MediaEditor": (".media.editor", "MediaEditor"),
    "MissingAPIKeyError": (".ai.llm", "MissingAPIKeyError"),
    "Segment": (".resize.segment", "Segment"),
    "Sentence": (".transcribe.transcription_element", "Sentence"),
    "Transcriber": (".transcribe.transcriber", "Transcriber"),
    "Transcription": (".transcribe.transcription", "Transcription"),
    "VideoFile": (".media.video_file", "VideoFile"),
    "Word": (".transcribe.transcription_element", "Word"),
    "available_fonts": (".typography", "available_fonts"),
    "build_cues": (".captions.captions", "build_cues"),
    "font_family": (".typography", "font_family"),
    "fonts_dir": (".typography", "fonts_dir"),
    "load_font": (".typography", "load_font"),
    "resolve_font": (".typography", "resolve_font"),
    "burn_captions": (".captions.captions", "burn_captions"),
    "resize": (".resize.resize", "resize"),
    "to_ass": (".captions.captions", "to_ass"),
    "to_srt": (".captions.captions", "to_srt"),
    "translate_cues": (".ai.translate", "translate_cues"),
    "write_ass": (".captions.captions", "write_ass"),
    "write_srt": (".captions.captions", "write_srt"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals()) + list(_LAZY_EXPORTS))


__all__ = [
    "AIClip",
    "AIClipError",
    "AIClipFinder",
    "AudioFile",
    "AudioVideoFile",
    "CAPTION_PRESETS",
    "CaptionCue",
    "CaptionError",
    "CaptionPreset",
    "CaptionWord",
    "Character",
    "LLMClient",
    "LLMError",
    "MissingAPIKeyError",
    "ClipFinder",
    "Clip",
    "available_fonts",
    "build_cues",
    "burn_captions",
    "font_family",
    "fonts_dir",
    "load_font",
    "resolve_font",
    "to_ass",
    "to_srt",
    "translate_cues",
    "write_ass",
    "write_srt",
    "CropWindow",
    "Crops",
    "EXPORT_PROFILES",
    "EXPORT_PROFILE_NAMES",
    "GRADES",
    "GRADE_NAMES",
    "PAD_MODES",
    "MediaEditor",
    "assert_output",
    "export_clip",
    "finish_clip",
    "measure_loudness",
    "parse_crop",
    "verify_output",
    "Segment",
    "Sentence",
    "Transcriber",
    "Transcription",
    "VideoFile",
    "Word",
    "resize",
]
