"""
IndiePost publishing client.

Wraps the documented ``/api/v1`` endpoints with Bearer auth, retries and
idempotent post creation. The API key comes from the environment
(``INDIEPOST_API_KEY``) and is never logged.

Flow: ``GET /accounts`` -> ``POST /media`` -> ``PUT upload.url`` -> ``POST /posts``.
"""

# standard library imports
from __future__ import annotations

import mimetypes
import os
import time
from pathlib import Path

# current package imports
from .models import (
    PlatformOptions,
    PublishError,
    PublishItem,
    build_post_payload,
    idempotency_key,
    media_size_ok,
    validate_platforms,
)

# 3rd party imports
import requests

DEFAULT_BASE_URL = "https://www.indiepost.app"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class IndiePostError(PublishError):
    """An IndiePost API request failed."""


class IndiePostAuthError(IndiePostError):
    """No API key, or the key was rejected."""


def _guess_mime(file_path: str) -> str:
    guessed, _ = mimetypes.guess_type(file_path)
    if guessed:
        return guessed
    return "video/mp4" if file_path.lower().endswith(".mp4") else "application/octet-stream"


class IndiePostClient:
    """Minimal client for the IndiePost v1 API."""

    def __init__(
        self,
        api_key: "str | None" = None,
        base_url: "str | None" = None,
        timeout: float = 180,
        max_retries: int = 3,
        session: "requests.Session | None" = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.environ.get("INDIEPOST_API_KEY", "")
        ).strip()
        self.base_url = (
            base_url
            or os.environ.get("INDIEPOST_BASE_URL", "")
            or DEFAULT_BASE_URL
        ).strip().rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or requests.Session()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def assert_ready(self) -> None:
        if not self.api_key:
            raise IndiePostAuthError(
                "No IndiePost API key configured. Add INDIEPOST_API_KEY to .env."
            )

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #

    def _headers(self, extra: "dict | None" = None) -> dict:
        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self, method: str, path: str, payload=None, headers=None, params=None
    ) -> dict:
        self.assert_ready()
        url = "{}/api/v1{}".format(
            self.base_url, path if path.startswith("/") else "/" + path
        )
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.request(
                    method,
                    url,
                    headers=self._headers(headers),
                    json=payload,
                    params=params or None,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise IndiePostError("IndiePost request failed: {}".format(exc)) from exc

            if response.status_code in (401, 403):
                raise IndiePostAuthError(
                    "IndiePost rejected the API key (HTTP {}). {}".format(
                        response.status_code, (response.text or "").strip()[:300]
                    )
                )
            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                last_error = "HTTP {}: {}".format(
                    response.status_code, (response.text or "").strip()[:200]
                )
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 15.0)
                except (TypeError, ValueError):
                    delay = min(2 ** attempt, 8)
                time.sleep(delay)
                continue
            if not 200 <= response.status_code < 300:
                raise IndiePostError(
                    "IndiePost returned HTTP {}: {}".format(
                        response.status_code, (response.text or "").strip()[:500]
                    )
                )
            if response.status_code == 204 or not (response.text or "").strip():
                return {}
            try:
                return response.json()
            except ValueError:
                return {"raw": response.text}
        raise IndiePostError("IndiePost request failed: {}".format(last_error))

    def _upload(self, upload_url: str, file_path: str, mime_type: str) -> None:
        """PUT the file to the signed upload URL (no auth header, as documented)."""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with open(file_path, "rb") as handle:
                    response = self._session.put(
                        upload_url,
                        data=handle,
                        headers={"Content-Type": mime_type},
                        timeout=self.timeout,
                    )
            except (OSError, requests.RequestException) as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise IndiePostError("Uploading to IndiePost failed: {}".format(exc)) from exc
            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                last_error = "HTTP {}".format(response.status_code)
                time.sleep(min(2 ** attempt, 8))
                continue
            if not 200 <= response.status_code < 300:
                raise IndiePostError(
                    "IndiePost upload returned HTTP {}.".format(response.status_code)
                )
            return
        raise IndiePostError("IndiePost upload failed: {}".format(last_error))

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #

    def list_accounts(self) -> dict:
        return self._request("GET", "/accounts")

    def list_media(self) -> dict:
        return self._request("GET", "/media")

    def init_media(self, filename: str, mime_type: str, size: int) -> dict:
        """Create the media record and return ``{"media_id", "upload_url"}``."""
        response = self._request(
            "POST",
            "/media",
            {"filename": filename, "mimeType": mime_type, "size": int(size)},
        )
        media = response.get("media") if isinstance(response.get("media"), dict) else {}
        upload = response.get("upload")
        if isinstance(upload, dict):
            upload_url = upload.get("url")
            upload_method = str(upload.get("method") or "PUT").upper()
            expires_in = upload.get("expiresInSeconds")
        else:
            upload_url = upload
            upload_method = "PUT"
            expires_in = None
        media_id = (
            media.get("id")
            or response.get("mediaId")
            or response.get("id")
            or (response.get("media") if isinstance(response.get("media"), str) else None)
        )
        if not upload_url:
            raise IndiePostError(
                "IndiePost did not return an upload URL: {}".format(
                    str(response)[:400]
                )
            )
        return {
            "media_id": media_id,
            "upload_url": upload_url,
            "upload_method": upload_method,
            "expires_in": expires_in,
            "raw": response,
        }

    def confirm_media(self, media_id: str) -> dict:
        """Finalize an upload: IndiePost serves the object only after this call."""
        return self._request("POST", "/media/confirm", {"mediaId": media_id})

    def import_media(self, drive_file_ids) -> dict:
        """Import Google Drive files by id (``POST /media/import``)."""
        ids = (
            [drive_file_ids]
            if isinstance(drive_file_ids, str)
            else list(drive_file_ids or [])
        )
        if not ids:
            raise IndiePostError("At least one Drive file id is required to import media.")
        return self._request("POST", "/media/import", {"driveFileIds": ids})

    def delete_media(self, media_id: str) -> dict:
        return self._request("DELETE", "/media/{}".format(media_id))

    def create_post(self, payload: dict, idempotency_key: "str | None" = None) -> dict:
        body = dict(payload)
        key = idempotency_key or body.get("idempotencyKey")
        if key:
            body["idempotencyKey"] = key
        headers = {"Idempotency-Key": key} if key else None
        return self._request("POST", "/posts", body, headers=headers)

    def schedule_batch(
        self,
        defaults: dict,
        cadence: dict,
        posts: "list[dict]",
        idempotency_key: "str | None" = None,
    ) -> dict:
        """Create a scheduled batch: shared defaults + cadence + per-post copy.

        ``cadence`` is ``{start, timezone, postsPerDay}`` and each post carries
        ``mediaIds``/``caption`` plus its per-platform blocks.
        """
        items = [dict(post) for post in posts or []]
        if not items:
            raise IndiePostError("A batch needs at least one post.")
        payload = {
            "defaults": dict(defaults or {}),
            "cadence": dict(cadence or {}),
            "posts": items,
        }
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._request("POST", "/batches", payload, headers=headers)

    def get_post(self, post_id: str) -> dict:
        return self._request("GET", "/posts/{}".format(post_id))

    def list_posts(self, from_: "str | None" = None, to: "str | None" = None) -> dict:
        """Post groups in a time window (ISO 8601, e.g. ``2026-11-09T00:00:00.000Z``)."""
        params = {}
        if from_:
            params["from"] = str(from_)
        if to:
            params["to"] = str(to)
        return self._request("GET", "/posts", params=params or None)

    def delete_post(self, post_id: str) -> dict:
        return self._request("DELETE", "/posts/{}".format(post_id))

    def get_batch(self, batch_id: str) -> dict:
        return self._request("GET", "/batches/{}".format(batch_id))

    # ------------------------------------------------------------------ #
    # High-level publish
    # ------------------------------------------------------------------ #

    def publish_media(
        self,
        file_path: str,
        platforms,
        caption: str = "",
        options: "PlatformOptions | None" = None,
        when: str = "now",
        job_id: str = "",
        clip_index: int = 0,
    ) -> dict:
        """Upload one media file and create its post group."""
        options = options or PlatformOptions()
        names = validate_platforms(platforms, options)
        if not os.path.isfile(file_path):
            raise IndiePostError("Media file '{}' does not exist.".format(file_path))
        if not media_size_ok(file_path):
            raise IndiePostError("Media file is larger than the 2 GB upload limit.")

        size = os.path.getsize(file_path)
        mime_type = _guess_mime(file_path)
        init = self.init_media(Path(file_path).name, mime_type, size)
        self._upload(init["upload_url"], file_path, mime_type)
        # Documented step three: without it the object stays unconfirmed and the
        # post endpoint cannot use the media id.
        confirmed = self.confirm_media(init["media_id"]) if init.get("media_id") else {}

        key = idempotency_key(job_id, clip_index, file_path)
        payload = build_post_payload(
            [init["media_id"]] if init.get("media_id") else [],
            names,
            caption=caption,
            when=when,
            options=options,
            idempotency_key=key,
        )
        response = self.create_post(payload, key)
        return {
            "media_id": init.get("media_id"),
            "media_key": confirmed.get("key"),
            "platforms": names,
            "idempotency_key": key,
            "post": response,
            "external_ids": extract_external_ids(response),
        }


def extract_external_ids(payload) -> "list[str]":
    """Best-effort collection of platform post ids/URLs from an API response."""
    found: "list[str]" = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in (
                    "externalPostId",
                    "externalId",
                    "postUrl",
                    "permalink",
                    "url",
                ) and isinstance(value, (str, int)):
                    found.append(str(value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(found))


def publish_items(
    client: IndiePostClient,
    items: "list[PublishItem]",
    platforms,
    when: str = "now",
    job_id: str = "",
) -> "list[dict]":
    """Publish several items with one shared platform selection."""
    results = []
    for item in items:
        options = item.options
        if item.youtube_title and not options.youtube_title:
            options = PlatformOptions(
                youtube_title=item.youtube_title,
                youtube_format=options.youtube_format,
                tiktok_privacy=options.tiktok_privacy,
                tiktok_commercial_enabled=options.tiktok_commercial_enabled,
                tiktok_commercial_your_brand=options.tiktok_commercial_your_brand,
                tiktok_branded_content=options.tiktok_branded_content,
                instagram_format=options.instagram_format,
                facebook_format=options.facebook_format,
                ai_generated=options.ai_generated,
            )
        result = client.publish_media(
            item.path,
            platforms,
            caption=item.caption,
            options=options,
            when=when,
            job_id=job_id,
            clip_index=item.index,
        )
        result["index"] = item.index
        result["path"] = item.path
        results.append(result)
    return results
