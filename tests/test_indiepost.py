import pytest

from clipsai.publish import (
    IndiePostAuthError,
    IndiePostClient,
    PlatformOptions,
    PublishValidationError,
    build_post_payload,
    idempotency_key,
    validate_platforms,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text if text is not None else "{}"
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.puts = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json": json,
                "params": params,
            }
        )
        return self.responses.pop(0)

    def put(self, url, data=None, headers=None, timeout=None):
        self.puts.append({"url": url, "headers": headers or {}})
        return FakeResponse(200)


def _options(**kwargs):
    base = {"youtube_title": "A real title", "youtube_format": "short"}
    base.update(kwargs)
    return PlatformOptions(**base)


def test_x_is_rejected():
    with pytest.raises(PublishValidationError, match="not available"):
        validate_platforms(["x"], PlatformOptions())


def test_youtube_requires_title_and_valid_format():
    with pytest.raises(PublishValidationError, match="youtube.title"):
        validate_platforms(["youtube"], PlatformOptions(youtube_title=""))
    with pytest.raises(PublishValidationError, match="youtube.format"):
        validate_platforms(
            ["youtube"], PlatformOptions(youtube_title="Title", youtube_format="clip")
        )


def test_tiktok_privacy_and_commercial_conflict():
    with pytest.raises(PublishValidationError, match="privacyLevel"):
        validate_platforms(["tiktok"], PlatformOptions(tiktok_privacy="EVERYONE"))
    with pytest.raises(PublishValidationError, match="SELF_ONLY"):
        validate_platforms(
            ["tiktok"],
            PlatformOptions(
                tiktok_privacy="SELF_ONLY", tiktok_branded_content=True
            ),
        )


def test_payload_includes_platform_blocks():
    payload = build_post_payload(
        ["media-1"],
        ["youtube", "tiktok", "instagram"],
        caption="Hello",
        when="now",
        options=_options(
            tiktok_privacy="FOLLOWER_OF_CREATOR",
            tiktok_commercial_your_brand=True,
            instagram_format="reel",
            ai_generated=True,
        ),
        idempotency_key="key-1",
    )

    assert payload["mediaIds"] == ["media-1"]
    assert payload["platforms"] == ["youtube", "tiktok", "instagram"]
    assert payload["idempotencyKey"] == "key-1"
    assert payload["youtube"] == {
        "title": "A real title",
        "format": "short",
        "aiGenerated": True,
    }
    assert payload["tiktok"]["privacyLevel"] == "FOLLOWER_OF_CREATOR"
    assert payload["tiktok"]["commercialYourBrand"] is True
    assert payload["instagram"]["format"] == "reel"


def test_idempotency_key_is_stable_and_content_sensitive(tmp_path):
    first = tmp_path / "a.mp4"
    first.write_bytes(b"x" * 2048)
    second = tmp_path / "b.mp4"
    second.write_bytes(b"y" * 2048)

    assert idempotency_key("job1", 0, str(first)) == idempotency_key(
        "job1", 0, str(first)
    )
    assert idempotency_key("job1", 0, str(first)) != idempotency_key(
        "job1", 1, str(first)
    )
    assert idempotency_key("job1", 0, str(first)) != idempotency_key(
        "job1", 0, str(second)
    )


def test_client_requires_a_key(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    client = IndiePostClient(api_key="")
    assert client.is_configured() is False
    with pytest.raises(IndiePostAuthError):
        client.list_accounts()


def test_client_rejects_bad_key(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    session = FakeSession([FakeResponse(401, text="bad key")])
    client = IndiePostClient(api_key="ip_bad", session=session)
    with pytest.raises(IndiePostAuthError, match="rejected"):
        client.list_accounts()


def test_publish_media_uploads_confirms_then_creates_post(tmp_path, monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake video bytes")

    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "mediaId": "media-42",
                    "mime": "video/mp4",
                    "size": 16,
                    "upload": {
                        "method": "PUT",
                        "url": "https://upload.example/put/42",
                        "expiresInSeconds": 600,
                    },
                },
            ),
            FakeResponse(
                200, {"ok": True, "mediaId": "media-42", "key": "users/x/media/42.mp4"}
            ),
            FakeResponse(200, {"id": "post-1", "posts": [{"externalPostId": "yt-9"}]}),
        ]
    )
    client = IndiePostClient(api_key="ip_test", session=session)

    result = client.publish_media(
        str(video),
        ["youtube"],
        caption="Hello",
        options=_options(),
        job_id="job1",
        clip_index=0,
    )

    assert result["media_id"] == "media-42"
    assert result["media_key"] == "users/x/media/42.mp4"
    assert "yt-9" in result["external_ids"]

    init_call, confirm_call, post_call = session.calls
    assert init_call["url"].endswith("/api/v1/media")
    assert init_call["json"]["filename"] == "clip.mp4"
    assert init_call["headers"]["Authorization"] == "Bearer ip_test"

    assert session.puts[0]["url"] == "https://upload.example/put/42"
    # The documented confirm step runs between the upload and the post.
    assert confirm_call["url"].endswith("/api/v1/media/confirm")
    assert confirm_call["json"] == {"mediaId": "media-42"}

    assert post_call["url"].endswith("/api/v1/posts")
    assert post_call["json"]["mediaIds"] == ["media-42"]
    assert post_call["json"]["platforms"] == ["youtube"]
    assert post_call["json"]["youtube"]["title"] == "A real title"
    assert post_call["headers"]["Idempotency-Key"] == result["idempotency_key"]


def test_import_media_sends_drive_file_ids(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"items": [{"mediaId": "m1", "ok": True}], "remaining": []},
            )
        ]
    )
    client = IndiePostClient(api_key="ip_test", session=session)

    result = client.import_media(["drive-1", "drive-2"])

    assert result["items"][0]["mediaId"] == "m1"
    assert session.calls[0]["url"].endswith("/api/v1/media/import")
    assert session.calls[0]["json"] == {"driveFileIds": ["drive-1", "drive-2"]}


def test_list_posts_sends_the_time_window(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    session = FakeSession([FakeResponse(200, {"posts": []})])
    client = IndiePostClient(api_key="ip_test", session=session)

    client.list_posts("2026-11-09T00:00:00.000Z", "2026-11-23T00:00:00.000Z")

    assert session.calls[0]["url"].endswith("/api/v1/posts")
    assert session.calls[0]["params"] == {
        "from": "2026-11-09T00:00:00.000Z",
        "to": "2026-11-23T00:00:00.000Z",
    }


def test_schedule_batch_builds_the_documented_body(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    session = FakeSession([FakeResponse(200, {"batchId": "b_01", "okCount": 1})])
    client = IndiePostClient(api_key="ip_test", session=session)

    result = client.schedule_batch(
        defaults={"platforms": ["instagram"], "instagram": {"format": "reel"}},
        cadence={
            "start": "2026-10-16T15:00:00",
            "timezone": "America/Los_Angeles",
            "postsPerDay": 5,
        },
        posts=[{"mediaIds": ["m1"], "caption": "Hello"}],
        idempotency_key="batch-1",
    )

    call = session.calls[0]
    assert result["batchId"] == "b_01"
    assert call["url"].endswith("/api/v1/batches")
    assert call["json"]["defaults"]["platforms"] == ["instagram"]
    assert call["json"]["cadence"]["postsPerDay"] == 5
    assert call["json"]["posts"][0]["mediaIds"] == ["m1"]
    assert call["headers"]["Idempotency-Key"] == "batch-1"


def test_schedule_batch_rejects_an_empty_batch(monkeypatch):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    client = IndiePostClient(api_key="ip_test", session=FakeSession([]))
    with pytest.raises(Exception, match="at least one post"):
        client.schedule_batch({}, {}, [])
