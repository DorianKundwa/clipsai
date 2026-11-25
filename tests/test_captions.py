from datetime import datetime

import pytest

from clipsai.captions import (
    CAPTION_PRESETS,
    CaptionError,
    build_cues,
    to_ass,
    to_srt,
)
from clipsai.transcribe.transcription import Transcription

WORDS = ["Hello", "there", "friend.", "This", "is", "a", "caption", "test"]


def _transcription(words=WORDS, char_duration=0.08, gap=0.12):
    """Build a transcription where each character is timed sequentially."""
    char_info = []
    clock = 0.0
    for word in words:
        for char in word:
            char_info.append(
                {
                    "char": char,
                    "start_time": round(clock, 3),
                    "end_time": round(clock + char_duration, 3),
                    "speaker": 0,
                }
            )
            clock += char_duration
        char_info.append(
            {"char": " ", "start_time": None, "end_time": None, "speaker": 0}
        )
        clock += gap
    return Transcription(
        {
            "source_software": "TestSoftware",
            "time_created": datetime.now(),
            "language": "en",
            "num_speakers": 1,
            "char_info": char_info,
        }
    )


def test_preset_names():
    assert set(CAPTION_PRESETS) == {"bold", "clean", "lime", "pill", "oneword"}


def test_build_cues_from_full_transcript():
    transcription = _transcription()
    cues = build_cues(transcription)
    assert cues
    assert " ".join(cue.text for cue in cues) == " ".join(WORDS)


def test_cues_are_relative_to_clip_start():
    transcription = _transcription()
    start = 0.5
    end = 2.0
    cues = build_cues(transcription, start_time=start, end_time=end)
    assert cues
    for cue in cues:
        assert cue.start >= 0.0
        assert cue.end <= end - start + 0.001
        assert cue.start < cue.end


def test_oneword_preset_emits_single_word_cues():
    transcription = _transcription()
    cues = build_cues(transcription, preset="oneword")
    assert all(len(cue.words) == 1 for cue in cues)


def test_unknown_preset_raises():
    with pytest.raises(CaptionError):
        build_cues(_transcription(), preset="nope")


def test_invalid_time_range_raises():
    with pytest.raises(CaptionError):
        build_cues(_transcription(), start_time=2.0, end_time=1.0)


def test_srt_has_numbered_timed_blocks():
    srt = to_srt(build_cues(_transcription()))
    assert srt.startswith("1\n")
    assert " --> " in srt
    assert ",000" in srt.splitlines()[1] or "," in srt.splitlines()[1]


def test_ass_highlights_active_word_and_escapes_braces():
    transcription = _transcription(words=["Listen", "{now}", "please"])
    cues = build_cues(transcription)
    ass = to_ass(cues, preset="bold", width=1080, height=1920)

    assert "PlayResX: 1080" in ass
    assert "Style: Default,Arial" in ass
    assert "Dialogue: 0," in ass
    assert "\\c&H0000FFFF&" in ass  # yellow active word
    # literal braces in the text are escaped; only override blocks remain
    events = ass.split("[Events]")[1]
    assert "(NOW)" in events
    assert "{NOW}" not in events


def test_ass_scales_for_horizontal_video():
    ass = to_ass(build_cues(_transcription()), preset="bold", width=1920, height=1080)
    assert "PlayResY: 1080" in ass
    # font size is authored for 1920px tall video and scaled down
    assert "Default,Arial,44," in ass
