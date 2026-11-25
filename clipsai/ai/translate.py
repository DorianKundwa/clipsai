"""
Caption translation with DeepSeek.

DeepSeek translates text only; it cannot dub audio. Translated captions keep the
original timing of each cue and replace the words with one translated line, so
they can be burned with the normal caption pipeline.
"""

# standard library imports
from __future__ import annotations

# current package imports
from .llm import LLMClient

# local package imports
from clipsai.captions.captions import CaptionCue, CaptionWord


class TranslationError(Exception):
    """Raised when captions cannot be translated."""


_TRANSLATE_PROMPT = """Translate these subtitle cues into {target_language}.

Rules:
- Keep the meaning and tone; keep each line short enough to read on screen
  (aim for the same length as the source line, never longer than ~2x).
- Do not merge or split cues: return exactly one translation per input number.
- Do not add explanations, quotes, numbering or notes inside the text.
- Keep names, numbers and hashtags unchanged.

Cues:
{cues}

Return JSON only:
{{"lines": [{{"i": 1, "text": "..."}}]}}
"""


def translate_cues(
    client: LLMClient,
    cues: "list[CaptionCue]",
    target_language: str,
    batch_size: int = 25,
) -> "list[CaptionCue]":
    """
    Translate caption cue text, preserving each cue's start/end times.

    Returns cues with a single word per cue (translated text no longer maps onto
    the original word timings, so per-word highlighting is dropped).
    """
    cues = list(cues or [])
    if not cues:
        return []
    target = str(target_language or "").strip()
    if not target:
        raise TranslationError("A target language is required.")

    translated: "dict[int, str]" = {}
    size = max(1, int(batch_size))
    for offset in range(0, len(cues), size):
        batch = cues[offset : offset + size]
        numbered = "\n".join(
            "{}. {}".format(offset + index + 1, cue.text.strip())
            for index, cue in enumerate(batch)
        )
        payload = client.complete_json(
            _TRANSLATE_PROMPT.format(
                target_language=target,
                cues=numbered,
            ),
            temperature=0.2,
            max_tokens=4096,
        )
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if not isinstance(lines, list):
            raise TranslationError("DeepSeek returned no 'lines' for the translation.")
        for entry in lines:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("i"))
            except (TypeError, ValueError):
                continue
            text = " ".join(str(entry.get("text") or "").split())
            if text:
                translated[index] = text

    result = []
    for index, cue in enumerate(cues, start=1):
        text = translated.get(index, cue.text).strip()
        if not text:
            continue
        result.append(
            CaptionCue([CaptionWord(text=text, start=cue.start, end=cue.end)])
        )
    if not result:
        raise TranslationError("The translation produced no usable captions.")
    return result
