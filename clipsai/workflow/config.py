"""Configuration for the guided ClipsAI Studio pipeline."""

# standard library imports
from __future__ import annotations

from dataclasses import dataclass, field

ASPECT_RATIOS = ("9:16", "3:4", "4:5", "1:1", "16:9")
SELECTION_METHODS = ("texttiling", "deepseek")


class PipelineConfigError(Exception):
    """Raised when pipeline settings are invalid."""


@dataclass
class PipelineConfig:
    """Every setting the pipeline stages need."""

    # source
    source_path: str = ""
    transcript_path: str = ""

    # transcription
    model_size: "str | None" = None
    device: "str | None" = None
    precision: "str | None" = None
    language: "str | None" = None
    batch_size: int = 16

    # clip selection
    method: str = "texttiling"
    min_clip_duration: int = 15
    max_clip_duration: int = 60
    top_n: int = 3
    cutoff_policy: str = "high"

    # output
    aspect_ratio: str = "9:16"
    render_vertical: bool = True
    keep_trimmed: bool = True
    crf: int = 18
    preset: str = "veryfast"

    # captions
    captions: bool = False
    caption_preset: str = "bold"
    translate_to: str = "off"
    # look: fonts and caption placement (the campaign typography)
    font: str = "montserrat-extrabold"
    caption_size: int = 0
    caption_position: str = "bottom"
    caption_pop: bool = False

    # master export
    export_profile: str = "off"
    grade: str = "none"
    punch_ins: bool = False
    source_crop: str = ""

    # packaging
    package: bool = False
    hook: bool = False
    thumbnail: bool = False
    effects: bool = False
    hook_style: str = "card"
    hook_position: str = "upper"
    hook_font: str = "montserrat-extrabold"
    hook_kicker: str = ""
    hook_seconds: float = 4.0

    # publishing
    publish: bool = False
    platforms: tuple = field(default_factory=tuple)
    publish_caption: str = ""
    youtube_title: str = ""
    youtube_format: str = "short"
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"
    ai_generated: bool = False
    when: str = "now"

    def normalized(self) -> "PipelineConfig":
        """Coerce UI-style values ('auto', lists) into canonical ones."""
        self.method = str(self.method or "texttiling").strip().lower()
        self.model_size = _auto_to_none(self.model_size)
        self.device = _auto_to_none(self.device)
        self.precision = _auto_to_none(self.precision)
        self.language = _auto_to_none(self.language)
        if isinstance(self.platforms, str):
            self.platforms = tuple(
                part.strip() for part in self.platforms.split(",") if part.strip()
            )
        else:
            self.platforms = tuple(str(p).strip() for p in (self.platforms or ()))
        self.platforms = tuple(dict.fromkeys(p for p in self.platforms if p))
        self.when = str(self.when or "now").strip() or "now"
        return self

    def validate(self) -> "PipelineConfig":
        """Validate settings and return the normalized config."""
        self.normalized()
        errors = []

        if self.method not in SELECTION_METHODS:
            errors.append(
                "Selection method must be one of: {}.".format(
                    ", ".join(SELECTION_METHODS)
                )
            )

        try:
            min_duration = int(self.min_clip_duration)
            max_duration = int(self.max_clip_duration)
            if min_duration <= 0 or max_duration <= 0:
                errors.append("Clip durations must be positive.")
            elif min_duration >= max_duration:
                errors.append(
                    "Max clip duration must be greater than the min duration."
                )
            elif max_duration > 1800:
                errors.append("Max clip duration cannot exceed 1800 seconds.")
        except (TypeError, ValueError):
            errors.append("Clip durations must be whole numbers.")

        try:
            if not 1 <= int(self.top_n) <= 50:
                errors.append("Number of clips must be between 1 and 50.")
        except (TypeError, ValueError):
            errors.append("Number of clips must be a whole number.")

        if self.aspect_ratio not in ASPECT_RATIOS:
            errors.append(
                "Aspect ratio must be one of: {}.".format(", ".join(ASPECT_RATIOS))
            )

        if self.caption_preset not in _caption_presets():
            errors.append(
                "Unknown caption preset '{}'. Choose one of: {}.".format(
                    self.caption_preset, ", ".join(_caption_presets())
                )
            )

        if self.translate_to and self.translate_to != "off" and not str(
            self.translate_to
        ).strip():
            errors.append("Translation language is empty.")

        if not str(self.font or "").strip():
            errors.append("A caption font is required.")
        try:
            self.caption_size = int(self.caption_size or 0)
            if not 0 <= self.caption_size <= 200:
                errors.append("Caption size must be between 0 (preset) and 200.")
        except (TypeError, ValueError):
            errors.append("Caption size must be a whole number.")

        from clipsai.captions.captions import CAPTION_POSITIONS

        if self.caption_position not in CAPTION_POSITIONS:
            errors.append(
                "Caption position must be one of: {}.".format(
                    ", ".join(CAPTION_POSITIONS)
                )
            )

        from clipsai.ai.hooks import HOOK_POSITIONS, HOOK_STYLES
        from clipsai.render import EXPORT_PROFILES, GRADE_NAMES, parse_crop, RenderError

        if self.hook_style not in HOOK_STYLES:
            errors.append(
                "Hook style must be one of: {}.".format(", ".join(HOOK_STYLES))
            )
        if self.hook_position not in HOOK_POSITIONS:
            errors.append(
                "Hook position must be one of: {}.".format(
                    ", ".join(HOOK_POSITIONS)
                )
            )
        try:
            self.hook_seconds = float(self.hook_seconds)
            if not 0.5 <= self.hook_seconds <= 60:
                errors.append("Hook duration must be between 0.5 and 60 seconds.")
        except (TypeError, ValueError):
            errors.append("Hook duration must be a number.")
        if not str(self.hook_font or "").strip():
            errors.append("A hook font is required.")

        if self.export_profile not in ("off",) + tuple(EXPORT_PROFILES):
            errors.append(
                "Export profile must be 'off' or one of: {}.".format(
                    ", ".join(EXPORT_PROFILES)
                )
            )
        if self.grade not in GRADE_NAMES:
            errors.append(
                "Grade must be one of: {}.".format(", ".join(GRADE_NAMES))
            )
        try:
            parse_crop(self.source_crop)
        except RenderError as exc:
            errors.append(str(exc))

        if self.publish:
            from clipsai.publish.models import TIKTOK_PRIVACY_LEVELS, validate_platforms
            from clipsai.publish.models import PlatformOptions

            if not self.platforms:
                errors.append("Publishing needs at least one platform.")
            if not self.when:
                errors.append("Publish time is required ('now' or an ISO timestamp).")
            if self.platforms:
                try:
                    validate_platforms(
                        self.platforms,
                        PlatformOptions(
                            youtube_title=self.youtube_title or "placeholder title",
                            youtube_format=self.youtube_format,
                            tiktok_privacy=self.tiktok_privacy,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - surfaced as validation
                    errors.append(str(exc))
                if self.tiktok_privacy not in TIKTOK_PRIVACY_LEVELS:
                    errors.append("Invalid TikTok privacy level.")

        if errors:
            raise PipelineConfigError(" ".join(errors))
        return self


def _auto_to_none(value):
    if value in (None, "", "auto"):
        return None
    return value


def _caption_presets():
    from clipsai.captions.captions import CAPTION_PRESETS

    return tuple(CAPTION_PRESETS)
