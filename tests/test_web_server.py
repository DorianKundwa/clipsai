import base64
import json
from datetime import datetime

from fastapi.testclient import TestClient

from clipsai import Clip
from clipsai.web_server import ISOLATION_HEADERS, create_app
import clipsai.web_server as web_server
import clipsai.workflow.media as workflow_media


def _sample_transcript_payload() -> dict:
    char_info = []
    clock = 0.0
    for ch in "Hello world today.":
        if ch == " ":
            char_info.append(
                {"char": " ", "start_time": None, "end_time": None, "speaker": 0}
            )
            clock += 0.1
        else:
            char_info.append(
                {
                    "char": ch,
                    "start_time": round(clock, 3),
                    "end_time": round(clock + 0.05, 3),
                    "speaker": 0,
                }
            )
            clock += 0.05
    return {
        "source_software": "TestSoftware",
        "time_created": datetime.now().isoformat(),
        "language": "en",
        "num_speakers": 1,
        "char_info": char_info,
    }


def _make_fake_static(tmp_path):
    static_dir = tmp_path / "web_client"
    (static_dir / "ffmpeg").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><body>ClipsAI</body></html>")
    (static_dir / "ffmpeg" / "ffmpeg-core.wasm").write_bytes(b"\x00asm")
    return static_dir


def test_spa_and_isolation_headers(tmp_path):
    static_dir = _make_fake_static(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    app = create_app(
        output_dir=tmp_path / "outputs",
        static_dir=static_dir,
        env_file=env_file,
    )
    client = TestClient(app)

    for path in ("/", "/pipeline", "/studio", "/api/services", "/api/pipeline/options"):
        resp = client.get(path)
        assert resp.status_code == 200
        for key, value in ISOLATION_HEADERS.items():
            assert resp.headers.get(key.lower()) == value

    wasm = client.get("/ffmpeg/ffmpeg-core.wasm")
    assert wasm.status_code == 200
    assert wasm.headers["content-type"].startswith("application/wasm")
    assert client.get("/api/does-not-exist").status_code == 404


def test_basic_auth_protects_routes_except_health(tmp_path):
    static_dir = _make_fake_static(tmp_path)
    app = create_app(
        output_dir=tmp_path / "outputs",
        static_dir=static_dir,
        auth=("editor", "secret123"),
    )
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("editor", "wrong")).status_code == 401
    assert client.get("/", auth=("editor", "secret123")).status_code == 200


def test_pipeline_job_lifecycle_and_file_security(tmp_path, monkeypatch):
    static_dir = _make_fake_static(tmp_path)
    monkeypatch.setattr(
        workflow_media,
        "find_clips",
        lambda transcription, config: [Clip(0.0, 0.8, 0, 12)],
    )

    app = create_app(
        output_dir=tmp_path / "outputs",
        static_dir=static_dir,
        env_file=tmp_path / "missing.env",
    )
    client = TestClient(app)

    transcript_bytes = json.dumps(_sample_transcript_payload()).encode("utf-8")
    create_resp = client.post(
        "/api/pipeline/jobs",
        data={"config": json.dumps({"method": "texttiling", "top_n": 1})},
        files={"transcript": ("transcript.json", transcript_bytes, "application/json")},
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    job_id = created["job_id"]
    assert created["next_stage"] == "transcribe"

    t_resp = client.post(
        f"/api/pipeline/jobs/{job_id}/run?sync=1", json={"stage": "transcribe"}
    )
    assert t_resp.status_code == 200
    assert "transcribe" in t_resp.json()["completed"]

    f_resp = client.post(
        f"/api/pipeline/jobs/{job_id}/run?sync=1", json={"stage": "find_clips"}
    )
    assert f_resp.status_code == 200
    body = f_resp.json()
    assert "find_clips" in body["completed"]
    assert len(body["clips"]) == 1

    clips_url = body["artifacts"]["clips_url"]
    assert clips_url is not None
    assert client.get(clips_url).status_code == 200

    # Path traversal outside job directory must fail cleanly.
    escaped = client.get(f"/api/pipeline/jobs/{job_id}/files/%2e%2e/secret.txt")
    assert escaped.status_code in (400, 403, 404)

    reset_resp = client.post(f"/api/pipeline/jobs/{job_id}/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["completed"] == []


def test_ai_metadata_and_indiepost_routes(tmp_path, monkeypatch):
    static_dir = _make_fake_static(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=sk-test-12345\nINDIEPOST_API_KEY=ip_test_12345\n",
        encoding="utf-8",
    )

    class FakeLLM:
        def complete_json(self, prompt, **kwargs):
            return {
                "title": "Fast Browser Video Editing.",
                "caption": "Trim and reframe clips cleanly.",
                "hashtags": ["VideoEditing", "#Shorts", "bad-tag"],
            }

    class FakeIndiePost:
        def __init__(self, api_key="", base_url=""):
            self.api_key = api_key
            self.uploaded = []

        def is_configured(self):
            return bool(self.api_key)

        def list_accounts(self):
            return {
                "workspaces": [
                    {
                        "id": "ws-1",
                        "name": "Main",
                        "isDefault": True,
                        "accounts": [
                            {
                                "platform": "youtube",
                                "connected": True,
                                "username": "@chan",
                            }
                        ],
                    }
                ]
            }

        def list_media(self):
            return {
                "items": [
                    {
                        "id": "med-1",
                        "filename": "clip.mp4",
                        "mime": "video/mp4",
                        "size": 128,
                        "inUse": False,
                    }
                ]
            }

        def list_posts(self, from_, to_):
            return {
                "posts": [
                    {
                        "id": "pg-1",
                        "status": "posted",
                        "platforms": ["youtube"],
                        "posts": [
                            {
                                "platform": "youtube",
                                "status": "posted",
                                "externalPostId": "yt-99",
                            }
                        ],
                    }
                ]
            }

        def init_media(self, filename, mime_type, size):
            return {"media_id": "med-1", "upload_url": "https://upload.example/put"}

        def _upload(self, upload_url, file_path, mime_type):
            self.uploaded.append((upload_url, file_path, mime_type))

        def confirm_media(self, media_id):
            return {"ok": True}

        def create_post(self, payload, idempotency_key=None):
            return {"id": "pg-2", "postUrl": "https://youtube.com/shorts/yt-99"}

    monkeypatch.setattr(web_server, "LLMClient", FakeLLM)
    monkeypatch.setattr(web_server, "IndiePostClient", FakeIndiePost)

    app = create_app(
        output_dir=tmp_path / "outputs",
        static_dir=static_dir,
        env_file=env_file,
    )
    client = TestClient(app)

    cross = client.post(
        "/api/ai/metadata",
        headers={"Origin": "https://evil.example"},
        json={"name": "clip.mp4"},
    )
    assert cross.status_code == 403

    meta = client.post(
        "/api/ai/metadata",
        json={"name": "clip.mp4", "start": 0, "end": 12, "platforms": ["youtube"]},
    )
    assert meta.status_code == 200
    assert meta.json()["title"] == "Fast Browser Video Editing"
    assert meta.json()["hashtags"] == ["videoediting", "shorts"]

    accts = client.get("/api/indiepost/accounts").json()
    assert accts["workspace"] == {"id": "ws-1", "name": "Main"}
    assert accts["accounts"][0]["platform"] == "youtube"

    assert client.get("/api/indiepost/media").json()["items"][0]["mediaId"] == "med-1"
    assert (
        client.get("/api/indiepost/posts").json()["posts"][0]["postGroupId"] == "pg-1"
    )

    bad_size = client.post("/api/indiepost/publish", content=b"123")
    assert bad_size.status_code == 411

    meta_header = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "platforms": ["youtube"],
                    "youtubeTitle": "My Clip",
                    "youtubeFormat": "short",
                    "caption": "Check this out",
                }
            ).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    pub = client.post(
        "/api/indiepost/publish",
        headers={
            "Content-Type": "video/mp4",
            "x-clip-size": "4",
            "x-clip-name": "my%20clip.mp4",
            "x-clipsai-publish": meta_header,
        },
        content=b"\x00\x00\x00\x18",
    )
    assert pub.status_code == 200
    pub_json = pub.json()
    assert pub_json["mediaId"] == "med-1"
    assert "https://youtube.com/shorts/yt-99" in pub_json["links"]
