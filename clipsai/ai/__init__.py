"""
AI features for ClipsAI, powered by the DeepSeek API.

Everything text-based is here: two-pass clip selection, packaging copy, hook
text/overlays, edit plans, caption translation and thumbnail text. Vision-only
features (layout picking, burned-subtitle detection, frame grounding) are not
possible with DeepSeek's text API and are intentionally absent.
"""

from .clips import (
    AIClip,
    AIClipError,
    AIClipFinder,
    build_windows,
    char_bounds,
    clip_target,
    dedupe_overlaps,
    normalize_spans,
    pick_shortlist,
    score_windows,
    snap_span,
    word_times,
)
from .effects import (
    EFFECT_LIMITS,
    EffectsError,
    apply_edits,
    build_filter_string,
    normalize_edits,
    probe_video_info,
    suggest_edits,
)
from .hooks import (
    HOOK_STYLES,
    burn_hook,
    generate_hook,
    load_font,
    render_hook_png,
    wrap_text,
)
from .llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMClient,
    LLMError,
    LLMResponseError,
    MissingAPIKeyError,
    parse_json,
)
from .metadata import (
    generate_metadata,
    metadata_as_json,
    normalize_metadata,
    package_clip,
    transcript_text,
)
from .thumbnails import (
    TEXT_POSITIONS,
    create_thumbnail,
    extract_frame,
    generate_thumbnail_text,
)
from .translate import TranslationError, translate_cues

__all__ = [
    "AIClip",
    "AIClipError",
    "AIClipFinder",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "EFFECT_LIMITS",
    "EffectsError",
    "HOOK_STYLES",
    "LLMClient",
    "LLMError",
    "LLMResponseError",
    "MissingAPIKeyError",
    "TEXT_POSITIONS",
    "TranslationError",
    "apply_edits",
    "build_filter_string",
    "build_windows",
    "burn_hook",
    "char_bounds",
    "clip_target",
    "create_thumbnail",
    "dedupe_overlaps",
    "extract_frame",
    "generate_hook",
    "generate_metadata",
    "generate_thumbnail_text",
    "load_font",
    "metadata_as_json",
    "normalize_edits",
    "normalize_metadata",
    "normalize_spans",
    "package_clip",
    "parse_json",
    "pick_shortlist",
    "probe_video_info",
    "render_hook_png",
    "score_windows",
    "snap_span",
    "suggest_edits",
    "transcript_text",
    "translate_cues",
    "word_times",
    "wrap_text",
]
