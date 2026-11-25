"""
IndiePost publishing models: validation, payload building, idempotency.

Pure functions only (no HTTP), so the publishing rules are unit-testable
without a key or network access.
"""

# standard library imports
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")
TIKTOK_PRIVACY_LEVELS = (
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "SELF_ONLY",
)
YOUTUBE_FORMATS = ("short", "long")
FEED_FORMATS = ("reel", "post")
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


class PublishError(Exception):
    """Base error for publishing."""


class PublishValidationError(PublishError):
    """The post would be rejected by the platform rules."""


@dataclass
class PlatformOptions:
    """Per-platform options accepted by IndiePost's post endpoint."""

    youtube_title: str = ""
    youtube_format: str = "short"
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"
    tiktok_commercial_enabled: bool = False
    tiktok_commercial_your_brand: bool = False
    tiktok_branded_content: bool = False
    instagram_format: "str | None" = None
    facebook_format: "str | None" = None
    ai_generated: bool = False


@dataclass
class PublishItem:
    """One media file to publish."""

    path: str
    caption: str = ""
    youtube_title: str = ""
    index: int = 0
    options: PlatformOptions = field(default_factory=PlatformOptions)


def _clean_platforms(platforms) -> "list[str]":
    if isinstance(platforms, str):
        platforms = [platforms]
    cleaned = []
    for platform in platforms or []:
        name = str(platform).strip().lower()
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def validate_platforms(platforms, options: PlatformOptions) -> "list[str]":
    """
    Validate a platform selection against the documented rules.

    X is not supported by the API and is rejected explicitly.
    """
    names = _clean_platforms(platforms)
    if not names:
        raise PublishValidationError("Select at least one platform to publish to.")

    for name in names:
        if name == "x":
            raise PublishValidationError(
                "X (Twitter) is not available through the IndiePost API."
            )
        if name not in PLATFORMS:
            raise PublishValidationError(
                "Unknown platform '{}'. Choose from: {}.".format(
                    name, ", ".join(PLATFORMS)
                )
            )

    if "youtube" in names:
        if not str(options.youtube_title or "").strip():
            raise PublishValidationError(
                "YouTube requires youtube.title (max 100 characters)."
            )
        if len(options.youtube_title) > 100:
            raise PublishValidationError("youtube.title must be 100 characters or fewer.")
        if options.youtube_format not in YOUTUBE_FORMATS:
            raise PublishValidationError(
                "youtube.format must be 'short' or 'long'."
            )

    if "tiktok" in names:
        if options.tiktok_privacy not in TIKTOK_PRIVACY_LEVELS:
            raise PublishValidationError(
                "tiktok.privacyLevel must be one of: {}.".format(
                    ", ".join(TIKTOK_PRIVACY_LEVELS)
                )
            )
        if (
            options.tiktok_branded_content
            and options.tiktok_privacy == "SELF_ONLY"
        ):
            raise PublishValidationError(
                "A paid-partnership TikTok post cannot use SELF_ONLY privacy."
            )

    for platform, fmt in (
        ("instagram", options.instagram_format),
        ("facebook", options.facebook_format),
    ):
        if fmt is not None and fmt not in FEED_FORMATS:
            raise PublishValidationError(
                "{} format must be 'reel' or 'post' when set.".format(platform)
            )

    return names


def build_post_payload(
    media_ids,
    platforms,
    caption: str = "",
    when: str = "now",
    options: "PlatformOptions | None" = None,
    idempotency_key: "str | None" = None,
) -> dict:
    """Build the body for ``POST /api/v1/posts``."""
    options = options or PlatformOptions()
    names = validate_platforms(platforms, options)
    ids = [str(media_id) for media_id in media_ids or []]
    if not ids:
        raise PublishValidationError("At least one uploaded media id is required.")

    payload = {
        "mediaIds": ids,
        "platforms": names,
        "caption": str(caption or "").strip(),
        "when": str(when or "now").strip() or "now",
    }
    if idempotency_key:
        payload["idempotencyKey"] = idempotency_key

    if "youtube" in names:
        payload["youtube"] = {
            "title": str(options.youtube_title).strip()[:100],
            "format": options.youtube_format,
            "aiGenerated": bool(options.ai_generated),
        }
    if "tiktok" in names:
        tiktok = {
            "privacyLevel": options.tiktok_privacy,
            "aiGenerated": bool(options.ai_generated),
        }
        if options.tiktok_commercial_enabled:
            tiktok["commercialEnabled"] = True
        if options.tiktok_commercial_your_brand:
            tiktok["commercialYourBrand"] = True
        if options.tiktok_branded_content:
            tiktok["commercialBrandedContent"] = True
        payload["tiktok"] = tiktok
    if "instagram" in names and options.instagram_format:
        payload["instagram"] = {
            "format": options.instagram_format,
            "aiGenerated": bool(options.ai_generated),
        }
    if "facebook" in names and options.facebook_format:
        payload["facebook"] = {
            "format": options.facebook_format,
            "aiGenerated": bool(options.ai_generated),
        }
    return payload


def _file_digest(file_path: str) -> str:
    """Cheap stable digest: size + first/last 1 MiB (whole file up to 8 MiB)."""
    size = os.path.getsize(file_path)
    hasher = hashlib.sha256()
    hasher.update(str(size).encode("ascii"))
    chunk = 1024 * 1024
    with open(file_path, "rb") as handle:
        if size <= 8 * chunk:
            hasher.update(handle.read())
        else:
            hasher.update(handle.read(chunk))
            handle.seek(-chunk, os.SEEK_END)
            hasher.update(handle.read(chunk))
    return hasher.hexdigest()


def idempotency_key(job_id: str, clip_index: int, file_path: str) -> str:
    """
    Stable key for retrying the same post without duplicates.

    Depends on the job, clip index and file content, so a retried request maps
    to the same post while a re-cut clip gets a new one.
    """
    digest = _file_digest(file_path)[:16]
    return "clipsai-{}-{}-{}".format(job_id or "job", int(clip_index), digest)


def media_size_ok(file_path: str) -> bool:
    return os.path.getsize(file_path) <= MAX_MEDIA_BYTES
