"""
AI clip selection with DeepSeek (two passes, transcript-only).

Pass 1 scores ~90-second transcript windows for short-form potential.
Pass 2 reads the best windows in full and proposes clips with a hook, title and
descriptions. Clip boundaries are then snapped onto real word timings, overlaps
are removed, and each clip is converted to a ``clipsai.Clip``.

Unlike vision-based pickers this needs no frames, so it works with DeepSeek's
text API and costs only transcript tokens.

Example
-------
>>> from clipsai import Transcriber
>>> from clipsai.ai import AIClipFinder
>>> transcription = Transcriber().transcribe(audio_file_path="talk.mp4")
>>> clips = AIClipFinder().find_clips(transcription)
>>> clips[0].hook, clips[0].start_time, clips[0].end_time
"""

# standard library imports
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

# current package imports
from .llm import LLMClient

# local package imports
from clipsai.clip.clip import Clip


class AIClipError(Exception):
    """Raised when AI clip selection cannot produce clips."""


@dataclass
class AIClip:
    """A clip proposed by the model, with its packaging copy."""

    start_time: float
    end_time: float
    start_char: int = 0
    end_char: int = 0
    score: float = 0.0
    hook: str = ""
    title: str = ""
    tiktok_description: str = ""
    instagram_description: str = ""
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def to_clip(self) -> Clip:
        return Clip(
            self.start_time, self.end_time, self.start_char, self.end_char
        )

    def to_dict(self) -> dict:
        return {
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "start_char": self.start_char,
            "end_char": self.end_char,
            "predicted_score": self.score,
            "viral_hook_text": self.hook,
            "video_title_for_youtube_short": self.title,
            "tiktok_description": self.tiktok_description,
            "instagram_description": self.instagram_description,
            "why": self.reason,
        }


# --------------------------------------------------------------------------- #
# Pure helpers (testable without an LLM)
# --------------------------------------------------------------------------- #


def build_windows(
    transcription,
    window_seconds: float = 90.0,
    overlap_seconds: float = 30.0,
) -> "list[dict]":
    """
    Split a transcription into scoring windows aligned to sentence boundaries.

    Windows grow sentence by sentence to roughly ``window_seconds``; the next
    window starts ``overlap_seconds`` before the previous end so a moment is
    never lost on a window edge.
    """
    segments = []
    for sentence in transcription.get_sentence_info():
        text = str(sentence.get("sentence") or "").strip()
        start = sentence.get("start_time")
        end = sentence.get("end_time")
        if not text or start is None or end is None or end <= start:
            continue
        segments.append((float(start), float(end), text))

    if not segments:
        return [
            {
                "id": "window_001",
                "start": 0.0,
                "end": round(float(transcription.end_time), 3),
                "text": str(transcription.text or ""),
            }
        ]

    windows = []
    index = 0
    while index < len(segments):
        window_start = segments[index][0]
        last = index
        while last + 1 < len(segments):
            candidate_end = segments[last + 1][1]
            if candidate_end - window_start > window_seconds * 1.25:
                break
            last += 1
            if segments[last][1] - window_start >= window_seconds:
                break
        window_end = segments[last][1]
        windows.append(
            {
                "id": "window_{:03d}".format(len(windows) + 1),
                "start": round(window_start, 3),
                "end": round(window_end, 3),
                "text": " ".join(segment[2] for segment in segments[index : last + 1]),
            }
        )
        if last >= len(segments) - 1:
            break
        target = window_end - overlap_seconds
        next_index = index + 1
        while next_index <= last and segments[next_index][0] < target:
            next_index += 1
        index = max(next_index, index + 1)

    return windows


def score_batches(windows: "list[dict]", batch_size: int = 8) -> "list[list[dict]]":
    """Split windows into near-equal batches (scores are comparable within one)."""
    windows = list(windows or [])
    if not windows:
        return []
    size = max(1, int(batch_size or 1))
    count = max(1, -(-len(windows) // size))
    base, extra = divmod(len(windows), count)
    batches = []
    start = 0
    for i in range(count):
        take = base + (1 if i < extra else 0)
        batch = windows[start : start + take]
        start += take
        if batch:
            batches.append(batch)
    return batches


def clip_target(n_windows: int, max_clips: int = 8) -> int:
    """How many clips to ask the detail pass for."""
    return max(1, min(int(max_clips), 1 + max(0, int(n_windows)) // 2))


def pick_shortlist(scored: "list[dict]", target: int) -> "list[dict]":
    """Return the highest-scoring windows, back in transcript order."""
    ranked = sorted(scored, key=lambda w: float(w.get("score") or 0), reverse=True)
    shortlist = ranked[: max(1, int(target))]
    return sorted(shortlist, key=lambda w: float(w["start"]))


def word_times(transcription) -> "list[tuple[float, float]]":
    """Valid (start, end) pairs from the transcript's word timings."""
    words = []
    for info in transcription.get_word_info():
        start, end = info.get("start_time"), info.get("end_time")
        if start is None or end is None:
            continue
        if float(end) <= float(start):
            continue
        words.append((float(start), float(end)))
    return words


def snap_span(
    words: "list[tuple[float, float]]",
    start: float,
    end: float,
    duration: float,
    min_duration: float,
    max_duration: float,
    search_window: float = 1.5,
    max_lead: float = 0.35,
    max_tail: float = 0.45,
) -> "tuple[float, float]":
    """
    Snap a proposed span onto real word boundaries, plus a little of the silence
    around them, then repair the duration bounds.

    Falls back to the clamped input when no words are close enough.
    """
    original_start = max(0.0, min(float(start), duration))
    original_end = max(0.0, min(float(end), duration))
    if original_end <= original_start:
        original_start, original_end = 0.0, min(duration, max_duration)
    original = (round(original_start, 3), round(original_end, 3))
    if not words:
        return original

    starts = [w[0] for w in words]
    ends = [w[1] for w in words]

    new_start = original_start
    candidates = [s for s in starts if abs(s - original_start) <= search_window]
    if candidates:
        word_start = min(candidates, key=lambda s: abs(s - original_start))
        previous_ends = [e for e in ends if e <= word_start]
        if previous_ends:
            gap = max(0.0, word_start - max(previous_ends))
            lead = min(max_lead, gap / 2.0)
        else:
            lead = max_lead
        new_start = max(0.0, word_start - lead)

    new_end = original_end
    candidates = [e for e in ends if abs(e - original_end) <= search_window]
    if candidates:
        word_end = min(candidates, key=lambda e: abs(e - original_end))
        next_starts = [s for s in starts if s >= word_end]
        if next_starts:
            gap = max(0.0, min(next_starts) - word_end)
            tail = min(max_tail, gap / 2.0)
        else:
            tail = max_tail
        new_end = min(duration, word_end + tail)

    if new_end - new_start < min_duration:
        target = new_start + min_duration
        later = sorted(e for e in ends if e >= target)
        if later and later[0] - new_start <= max_duration:
            new_end = min(duration, later[0] + 0.2)
        else:
            return original
    if new_end - new_start > max_duration:
        target = new_start + max_duration
        earlier = [e for e in ends if new_start < e <= target]
        new_end = (max(earlier) + 0.2) if earlier else target
        new_end = min(new_end, new_start + max_duration, duration)

    if new_end <= new_start or new_end - new_start < min_duration:
        return original
    return (round(new_start, 3), round(new_end, 3))


def dedupe_overlaps(clips: "list[AIClip]", ratio: float = 0.25) -> "list[AIClip]":
    """Drop clips that overlap a better clip by ``ratio`` of the shorter one."""
    ranked = sorted(clips, key=lambda c: (-c.score, c.start_time))
    kept: "list[AIClip]" = []
    for clip in ranked:
        clash = False
        for other in kept:
            overlap = min(clip.end_time, other.end_time) - max(
                clip.start_time, other.start_time
            )
            shorter = max(
                1e-6,
                min(clip.duration, other.duration),
            )
            if overlap > 0 and overlap / shorter >= ratio:
                clash = True
                break
        if not clash:
            kept.append(clip)
    return sorted(kept, key=lambda c: c.start_time)


def char_bounds(transcription, start: float, end: float) -> "tuple[int, int]":
    """Approximate (start_char, end_char) for a time span, from char timings."""
    char_info = transcription.get_char_info()
    start_index = 0
    for i, info in enumerate(char_info):
        if info.get("start_time") is not None and float(info["start_time"]) >= start:
            start_index = i
            break
    end_index = len(char_info)
    for i, info in enumerate(char_info):
        if info.get("end_time") is not None and float(info["end_time"]) > end:
            end_index = i
            break
    return start_index, max(start_index + 1, end_index)


def normalize_spans(
    raw_clips: "list[dict]",
    transcription,
    min_duration: float,
    max_duration: float,
    words: "list[tuple[float, float]] | None" = None,
) -> "list[AIClip]":
    """Validate, clamp, snap and de-duplicate model-proposed clips."""
    duration = float(transcription.end_time)
    words = word_times(transcription) if words is None else words
    clips = []
    for entry in raw_clips or []:
        if not isinstance(entry, dict):
            continue
        try:
            start = float(entry.get("start", entry.get("start_time", 0.0)))
            end = float(entry.get("end", entry.get("end_time", 0.0)))
        except (TypeError, ValueError):
            continue
        start, end = snap_span(
            words, start, end, duration, min_duration, max_duration
        )
        if end - start < min_duration - 0.01:
            continue
        start_char, end_char = char_bounds(transcription, start, end)
        try:
            score = float(entry.get("predicted_score", entry.get("score", 0)) or 0)
        except (TypeError, ValueError):
            score = 0.0
        clips.append(
            AIClip(
                start_time=start,
                end_time=end,
                start_char=start_char,
                end_char=end_char,
                score=score,
                hook=str(
                    entry.get("viral_hook_text") or entry.get("hook") or ""
                ).strip()[:120],
                title=str(
                    entry.get("video_title_for_youtube_short")
                    or entry.get("title")
                    or ""
                ).strip()[:140],
                tiktok_description=str(
                    entry.get("tiktok_description") or ""
                ).strip()[:600],
                instagram_description=str(
                    entry.get("instagram_description") or ""
                ).strip()[:600],
                reason=str(entry.get("why") or entry.get("reason") or "").strip()[:300],
            )
        )
    return dedupe_overlaps(clips)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_SCORE_PROMPT = """You are a senior short-form video editor choosing moments for \
TikTok, Reels and Shorts from a long transcript.

Score every window below for how likely it is to stop a viewer scrolling.
90-100: a self-contained story, hot take, surprising fact, number or payoff.
70-89: strong moment that needs a little trimming.
40-69: usable but ordinary.
0-39: setup, filler, housekeeping, ads, greetings.

Rules:
- Judge only from the text; you cannot see the video.
- A window scores high only if it makes sense with no other context.
- Prefer concrete claims, numbers, names, conflict, emotion, punchlines.
- Score every window. Do not invent ids.

Windows (JSON):
{windows}

Return JSON only, in this shape:
{{"scores": [{{"id": "window_001", "score": 82, "reason": "one short sentence"}}]}}
"""

_DETAIL_PROMPT = """You are a senior short-form video editor cutting clips from a \
long transcript for TikTok, Reels and Shorts.

From the transcript windows below, pick {min_clips} to {max_clips} of the most \
compelling moments and write their packaging copy.

HARD RULES:
- Times are ABSOLUTE seconds from the start of the source video, 0 <= start < \
end <= {video_duration:.2f}.
- Each clip must be {min_duration:g} to {max_duration:g} seconds long.
- Start and end inside one of the listed windows.
- Start and end on the first/last word of the moment; never mid-sentence.
- No two clips may cover the same moment.
- The clip must stand alone: no "as I said earlier", no unresolved setup.
- Write all copy in the transcript's language ({language}).
- The hook is at most 10 words and must name the concrete payoff.
- The YouTube short title is at most 100 characters, no clickbait the clip \
does not pay off.
- Descriptions are 1-2 sentences with 2-4 relevant hashtags.

Windows (JSON):
{windows}

Return JSON only, in this shape:
{{"shorts": [{{"start": 12.5, "end": 42.0, "predicted_score": 88, \
"viral_hook_text": "...", "video_title_for_youtube_short": "...", \
"tiktok_description": "...", "instagram_description": "...", "why": "..."}}]}}
"""


def _windows_payload(windows: "list[dict]", text_limit: int = 1400) -> str:
    payload = [
        {
            "id": window["id"],
            "start": window["start"],
            "end": window["end"],
            "text": str(window.get("text") or "")[:text_limit],
        }
        for window in windows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=1)


def score_windows(
    client: LLMClient,
    windows: "list[dict]",
    batch_size: int = 8,
) -> "list[dict]":
    """Pass 1: score every window in batches, returning windows with ``score``."""
    scores: "dict[str, float]" = {}
    reasons: "dict[str, str]" = {}
    for batch in score_batches(windows, batch_size):
        payload = client.complete_json(
            _SCORE_PROMPT.format(windows=_windows_payload(batch)),
            temperature=0.2,
            max_tokens=2048,
        )
        entries = payload.get("scores") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            logging.warning("DeepSeek scoring pass returned no 'scores' list")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            window_id = str(entry.get("id") or "").strip()
            if not window_id:
                continue
            try:
                score = float(entry.get("score") or 0)
            except (TypeError, ValueError):
                score = 0.0
            scores[window_id] = max(0.0, min(100.0, score))
            reasons[window_id] = str(entry.get("reason") or "").strip()[:200]

    scored = []
    for window in windows:
        item = dict(window)
        item["score"] = scores.get(window["id"], 0.0)
        item["reason"] = reasons.get(window["id"], "")
        scored.append(item)
    return scored


def detail_clips(
    client: LLMClient,
    windows: "list[dict]",
    transcription,
    min_duration: float,
    max_duration: float,
    language: str,
    max_clips: int,
) -> "list[dict]":
    """Pass 2: read the shortlisted windows and return raw clip proposals."""
    min_clips = max(1, min(3, max_clips))
    payload = client.complete_json(
        _DETAIL_PROMPT.format(
            windows=_windows_payload(windows, text_limit=6000),
            min_clips=min_clips,
            max_clips=max_clips,
            video_duration=float(transcription.end_time),
            min_duration=min_duration,
            max_duration=max_duration,
            language=language or "the transcript language",
        ),
        temperature=0.5,
        max_tokens=4096,
    )
    shorts = payload.get("shorts") if isinstance(payload, dict) else None
    if not isinstance(shorts, list):
        raise AIClipError("DeepSeek returned no 'shorts' list for the detail pass.")
    return [entry for entry in shorts if isinstance(entry, dict)]


def _fallback_raw(scored: "list[dict]", max_duration: float) -> "list[dict]":
    """If the detail pass fails, at least cut the best windows."""
    ranked = sorted(scored, key=lambda w: float(w.get("score") or 0), reverse=True)
    return [
        {
            "start": window["start"],
            "end": min(window["end"], window["start"] + max_duration),
            "predicted_score": window.get("score", 0),
            "why": window.get("reason", ""),
        }
        for window in ranked[:3]
    ]


class AIClipFinder:
    """
    Find short-form clips with DeepSeek's two-pass transcript analysis.

    Parameters
    ----------
    client: LLMClient
        A configured client. Defaults to ``LLMClient()`` (reads env vars).
    min_clip_duration, max_clip_duration: int
        Clip length band in seconds.
    language: str
        Language for the hook/title/description copy.
    max_clips: int
        Upper bound on returned clips.
    """

    def __init__(
        self,
        client: "LLMClient | None" = None,
        min_clip_duration: int = 15,
        max_clip_duration: int = 60,
        language: str = "en",
        max_clips: int = 8,
        window_seconds: float = 90.0,
    ) -> None:
        if int(max_clip_duration) <= int(min_clip_duration):
            raise ValueError("max_clip_duration must be greater than min_clip_duration")
        self._client = client or LLMClient()
        self._client.assert_ready()
        self._min = float(min_clip_duration)
        self._max = float(max_clip_duration)
        self._language = language
        self._max_clips = max(1, int(max_clips))
        self._window_seconds = window_seconds

    def find_clips(self, transcription) -> "list[AIClip]":
        """Run both passes and return de-duplicated, snapped, scored clips."""
        windows = build_windows(transcription, window_seconds=self._window_seconds)
        if not windows:
            return []

        scored = score_windows(self._client, windows)
        target = clip_target(len(scored), self._max_clips)
        shortlist = pick_shortlist(scored, target)

        try:
            raw = detail_clips(
                self._client,
                shortlist,
                transcription,
                self._min,
                self._max,
                self._language,
                self._max_clips,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to scored windows
            logging.warning("AI detail pass failed (%s); using scored windows", exc)
            raw = _fallback_raw(scored, self._max)

        clips = normalize_spans(raw, transcription, self._min, self._max)
        if not clips:
            raise AIClipError(
                "DeepSeek did not return any usable clips. Try a longer clip band "
                "or a different model."
            )
        return clips[: self._max_clips]
