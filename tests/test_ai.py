from datetime import datetime

import pytest

from clipsai.ai import (
    AIClipFinder,
    EffectsError,
    LLMClient,
    MissingAPIKeyError,
    build_filter_string,
    build_windows,
    dedupe_overlaps,
    generate_metadata,
    normalize_edits,
    normalize_metadata,
    normalize_spans,
    parse_json,
    render_hook_png,
    snap_span,
    translate_cues,
)
from clipsai.ai.thumbnails import generate_thumbnail_text
from clipsai.captions import CaptionCue, CaptionWord
from clipsai.transcribe.transcription import Transcription

SENTENCES = [
    "Most people get this completely wrong about editing short videos.",
    "The first three seconds decide whether anyone keeps watching.",
    "I tested forty clips last month and the data was brutal.",
    "Hooks with a number in them held twice as many viewers.",
    "So put the payoff in the first sentence, not the last.",
]


class StubClient:
    """Stands in for LLMClient; returns canned JSON payloads in order."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    def assert_ready(self):
        return None

    def complete_json(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if not self.payloads:
            raise AssertionError("StubClient ran out of payloads")
        return self.payloads.pop(0)

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "ready"


def _transcription(sentences=SENTENCES, char_duration=0.08, gap=0.12):
    char_info = []
    clock = 0.0
    for sentence in sentences:
        for word in sentence.split(" "):
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


# --------------------------------------------------------------------------- #
# LLM client
# --------------------------------------------------------------------------- #


def test_client_without_key_is_not_ready(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = LLMClient(api_key="")
    assert client.is_configured() is False
    with pytest.raises(MissingAPIKeyError):
        client.complete("ping")


def test_client_reads_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    client = LLMClient()
    assert client.api_key == "test-key"
    assert client.base_url == "https://example.test"
    assert client.model == "deepseek-reasoner"


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure: {"a": 2} hope that helps') == {"a": 2}


# --------------------------------------------------------------------------- #
# Clip selection
# --------------------------------------------------------------------------- #


def test_build_windows_covers_transcript():
    transcription = _transcription()
    windows = build_windows(transcription)
    assert windows
    assert windows[0]["start"] == 0.0
    assert windows[-1]["end"] <= transcription.end_time + 0.001
    assert all(window["text"] for window in windows)
    ids = [window["id"] for window in windows]
    assert ids == sorted(ids)


def test_snap_span_stays_on_word_boundaries():
    words = [(0.0, 0.8), (1.0, 1.8), (2.2, 3.0), (3.4, 4.6), (5.0, 6.2)]
    start, end = snap_span(words, 1.05, 4.5, duration=10.0, min_duration=2.0, max_duration=6.0)
    assert start <= 1.05
    assert end >= 4.5
    assert 2.0 <= end - start <= 6.0
    assert any(abs(start - s) < 0.4 for s, _ in words)


def test_finder_returns_snapped_scored_clip():
    transcription = _transcription()
    stub = StubClient(
        [
            {"scores": [{"id": "window_001", "score": 91, "reason": "strong"}]},
            {
                "shorts": [
                    {
                        "start": 2.0,
                        "end": 18.0,
                        "predicted_score": 88,
                        "viral_hook_text": "40 clips, 2x viewers",
                        "video_title_for_youtube_short": "The hook data",
                        "why": "concrete test result",
                    }
                ]
            },
        ]
    )
    finder = AIClipFinder(
        client=stub, min_clip_duration=15, max_clip_duration=30, max_clips=4
    )
    clips = finder.find_clips(transcription)
    assert len(clips) == 1
    clip = clips[0]
    assert clip.score == 88
    assert clip.hook == "40 clips, 2x viewers"
    assert 0.0 <= clip.start_time < clip.end_time <= transcription.end_time
    assert 15 <= clip.duration <= 30.5
    assert clip.start_char < clip.end_char
    assert isinstance(clip.to_clip().start_char, int)


def test_normalize_spans_dedupes_overlapping_clips():
    transcription = _transcription()
    raw = [
        {"start": 1.0, "end": 20.0, "predicted_score": 90},
        {"start": 2.0, "end": 19.0, "predicted_score": 40},
    ]
    clips = normalize_spans(raw, transcription, min_duration=10, max_duration=30)
    assert len(clips) == 1
    assert clips[0].score == 90


def test_dedupe_keeps_non_overlapping():
    transcription = _transcription()
    raw = [
        {"start": 1.0, "end": 12.0, "predicted_score": 90},
        {"start": 20.0, "end": 31.0, "predicted_score": 80},
    ]
    clips = normalize_spans(raw, transcription, min_duration=8, max_duration=30)
    assert len(dedupe_overlaps(clips)) == len(clips)


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


def test_normalize_metadata_clamps_and_dedupes():
    payload = {
        "title": "x" * 200,
        "youtube_titles": ["First", "first", "Second", "Third", "Fourth", "Fifth"],
        "hashtags": ["editing", "#editing", "#Shorts!", "bad tag"],
        "hook": "  a   hook  ",
        "summary": "s" * 900,
    }
    metadata = normalize_metadata(payload)
    assert len(metadata["title"]) <= 100
    assert len(metadata["youtube_titles"]) <= 5
    assert metadata["hashtags"][0] == "#editing"
    assert metadata["hashtags"].count("#editing") == 1
    assert metadata["hashtags"][-1].startswith("#")
    assert metadata["hook"] == "a hook"
    assert len(metadata["summary"]) <= 400


def test_generate_metadata_uses_model_copy():
    stub = StubClient(
        [
            {
                "title": "The 3-second rule",
                "hook": "Most editors lose viewers here",
                "youtube_titles": ["The 3-second rule", "Fix your first three seconds"],
                "tiktok_caption": "Watch the first 3 seconds. #editing",
                "instagram_caption": "Retention starts immediately.",
                "hashtags": ["#editing", "#shorts"],
                "summary": "Why the opening seconds decide retention.",
            }
        ]
    )
    metadata = generate_metadata(stub, "some transcript", language="en")
    assert metadata["hook"] == "Most editors lose viewers here"
    assert metadata["youtube_titles"][0] == "The 3-second rule"


# --------------------------------------------------------------------------- #
# Effects
# --------------------------------------------------------------------------- #


def test_normalize_edits_caps_strength_and_drops_zoom_with_captions():
    edits = [
        {"type": "zoom_in", "start": 1, "end": 4, "strength": 5.0},
        {"type": "zoom_in", "start": 2, "end": 5, "strength": 0.1},
        {"type": "bw_moment", "start": 6, "end": 7.5},
        {"type": "nonsense", "start": 1, "end": 2},
    ]
    normal = normalize_edits(edits, duration=30)
    assert normal[0]["strength"] <= 0.15
    assert all(e["type"] != "nonsense" for e in normal)
    assert [e["type"] for e in normalize_edits(edits, 30, has_captions=True)] == [
        "bw_moment"
    ]


def test_build_filter_string_returns_none_without_edits():
    assert build_filter_string([], 30, 30, 1080, 1920) == (None, [])
    filter_string, applied = build_filter_string(
        [{"type": "color_pop", "start": 3, "end": 5, "strength": 0.5}],
        30,
        30,
        1080,
        1920,
    )
    assert "eq=contrast" in filter_string
    assert len(applied) == 1


def test_apply_edits_rejects_empty_plan():
    from clipsai.ai import apply_edits

    with pytest.raises(EffectsError):
        apply_edits("missing.mp4", [], "out.mp4")


# --------------------------------------------------------------------------- #
# Translation / hooks / thumbnails
# --------------------------------------------------------------------------- #


def test_translate_cues_preserves_timings():
    cues = [
        CaptionCue([CaptionWord("Hello", 0.0, 1.0)]),
        CaptionCue([CaptionWord("World", 1.5, 2.5)]),
    ]
    stub = StubClient([{"lines": [{"i": 1, "text": "Hola"}, {"i": 2, "text": "Mundo"}]}])
    translated = translate_cues(stub, cues, "Spanish")
    assert [c.text for c in translated] == ["Hola", "Mundo"]
    assert translated[0].start == 0.0
    assert translated[1].end == 2.5


def test_render_hook_png_is_transparent_rgba():
    image = render_hook_png("40 clips, 2x viewers", width=1080, style="box")
    assert image.mode == "RGBA"
    assert image.width > 0 and image.height > 0
    with pytest.raises(ValueError):
        render_hook_png("", width=1080)


def test_generate_thumbnail_text_trims():
    stub = StubClient([{"thumbnail_text": "The 3 second rule"}])
    assert generate_thumbnail_text(stub, "transcript") == "The 3 second rule"
