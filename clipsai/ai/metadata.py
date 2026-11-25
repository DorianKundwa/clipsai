"""
AI packaging copy (titles, hooks, descriptions, hashtags) with DeepSeek.

The model only writes text: there is no image or video understanding, so the
input is the transcript of the clip (plus the source language).
"""

# standard library imports
from __future__ import annotations

import json

# current package imports
from .llm import LLMClient

MAX_TITLES = 5
MAX_TITLE_CHARS = 100
MAX_HOOK_CHARS = 90
MAX_CAPTION_CHARS = 600


_PACKAGE_PROMPT = """You are a short-form video packaging expert (TikTok, Reels, \
YouTube Shorts). Read the transcript of ONE clip and write its packaging copy.

Transcript ({language}):
{transcript}

Rules:
- Write everything in the same language as the transcript ({language}).
- title: the single best title, at most 100 characters, specific to this moment.
- hook: at most 10 words, must name the concrete payoff (number, name, result).
- youtube_titles: {max_titles} alternatives, each at most 100 characters, \
different angles (outcome, curiosity, contrarian, how-to, number).
- tiktok_caption: 1-2 sentences, conversational, 2-4 hashtags.
- instagram_caption: 1-2 sentences, slightly more polished, 2-4 hashtags.
- hashtags: 6-8 lowercase hashtags including the # sign, no duplicates.
- summary: one sentence describing what the clip is about.
- Never invent facts that are not in the transcript.

Return JSON only:
{{"title": "...", "hook": "...", "youtube_titles": ["..."], \
"tiktok_caption": "...", "instagram_caption": "...", "hashtags": ["#..."], \
"summary": "..."}}
"""


def transcript_text(
    transcription,
    start_time: float = None,
    end_time: float = None,
    limit: int = 12000,
) -> str:
    """Plain text of a transcription (optionally one time range), length-capped."""
    char_info = transcription.get_char_info(start_time, end_time)
    text = "".join(str(info.get("char") or "") for info in char_info).strip()
    text = " ".join(text.split())
    return text[:limit]


def _clean(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_metadata(payload: dict, max_titles: int = MAX_TITLES) -> dict:
    """Clamp and de-duplicate raw model output into a stable dict."""
    payload = payload if isinstance(payload, dict) else {}

    titles = []
    raw_titles = payload.get("youtube_titles")
    if not isinstance(raw_titles, list):
        raw_titles = []
    for title in raw_titles:
        cleaned = _clean(title, MAX_TITLE_CHARS)
        if cleaned and cleaned.lower() not in {t.lower() for t in titles}:
            titles.append(cleaned)
        if len(titles) >= max_titles:
            break

    title = _clean(payload.get("title"), MAX_TITLE_CHARS)
    if title and title.lower() not in {t.lower() for t in titles}:
        titles.insert(0, title)
        titles = titles[:max_titles]
    elif not title and titles:
        title = titles[0]

    hashtags = []
    raw_tags = payload.get("hashtags")
    if not isinstance(raw_tags, list):
        raw_tags = []
    for tag in raw_tags:
        cleaned = _clean(tag, 40)
        if not cleaned:
            continue
        if not cleaned.startswith("#"):
            cleaned = "#" + cleaned
        cleaned = "#" + "".join(
            ch for ch in cleaned[1:] if ch.isalnum() or ch in "_-"
        )
        if len(cleaned) > 1 and cleaned.lower() not in {h.lower() for h in hashtags}:
            hashtags.append(cleaned)
        if len(hashtags) >= 8:
            break

    return {
        "title": title,
        "hook": _clean(payload.get("hook"), MAX_HOOK_CHARS),
        "youtube_titles": titles,
        "tiktok_caption": _clean(payload.get("tiktok_caption"), MAX_CAPTION_CHARS),
        "instagram_caption": _clean(
            payload.get("instagram_caption"), MAX_CAPTION_CHARS
        ),
        "hashtags": hashtags,
        "summary": _clean(payload.get("summary"), 400),
    }


def generate_metadata(
    client: LLMClient,
    text: str,
    language: str = "en",
    max_titles: int = MAX_TITLES,
    max_tokens: int = 2048,
) -> dict:
    """Ask DeepSeek for titles, hook, descriptions and hashtags for one clip."""
    if not str(text or "").strip():
        raise ValueError("Cannot generate metadata for an empty transcript range.")
    payload = client.complete_json(
        _PACKAGE_PROMPT.format(
            transcript=str(text)[:12000],
            language=language or "the transcript language",
            max_titles=int(max_titles),
        ),
        temperature=0.7,
        max_tokens=max_tokens,
    )
    return normalize_metadata(payload, max_titles=max_titles)


def package_clip(
    client: LLMClient,
    transcription,
    start_time: float,
    end_time: float,
    language: str = "en",
) -> dict:
    """Metadata for one clip range, plus its timings and transcript."""
    text = transcript_text(transcription, start_time, end_time)
    metadata = generate_metadata(client, text, language=language)
    metadata.update(
        {
            "start_time": round(float(start_time), 3),
            "end_time": round(float(end_time), 3),
            "duration": round(float(end_time) - float(start_time), 3),
            "transcript": text,
        }
    )
    return metadata


def metadata_as_json(metadata: dict) -> str:
    return json.dumps(metadata, ensure_ascii=False, indent=2)
