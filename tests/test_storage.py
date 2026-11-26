"""Storage management: job listing, deletion, retention cleanup and compaction."""

import json
import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from clipsai.web_server import create_app


def _app(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    static_dir = tmp_path / "web_client"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    app = create_app(
        output_dir=out,
        static_dir=static_dir,
        env_file=env_file,
        workspace_dirs={"outputs": out, "work": work},
    )
    return out, app


def _job_dir(root, job_id: str, *, age_days: float, files: dict) -> None:
    job = root / job_id
    job.mkdir(parents=True)
    updated = (datetime.now() - timedelta(days=age_days)).isoformat(timespec="seconds")
    (job / "manifest.json").write_text(
        json.dumps({"job_id": job_id, "created": updated, "updated": updated}),
        encoding="utf-8",
    )
    for name, size in files.items():
        (job / name).write_bytes(b"\0" * size)
    stamp = (datetime.now() - timedelta(days=age_days)).timestamp()
    os.utime(job / "manifest.json", (stamp, stamp))


def test_storage_lists_job_folders_and_ignores_other_dirs(tmp_path):
    out, app = _app(tmp_path)
    _job_dir(out, "0123456789", age_days=1, files={"clip_0.mp4": 64})
    (out / "my_campaign").mkdir()
    (out / "my_campaign" / "notes.md").write_text("keep", encoding="utf-8")

    client = TestClient(app)
    body = client.get("/api/storage").json()

    assert body["jobs_count"] == 1
    assert body["jobs"][0]["job_id"] == "0123456789"
    assert body["jobs"][0]["size"] >= 64
    assert body["jobs_bytes"] >= 64


def test_delete_job_removes_only_that_folder(tmp_path):
    out, app = _app(tmp_path)
    _job_dir(out, "aaaaaaaaaa", age_days=1, files={"clip_0.mp4": 32})
    _job_dir(out, "bbbbbbbbbb", age_days=1, files={"clip_0.mp4": 32})
    client = TestClient(app)

    response = client.delete("/api/pipeline/jobs/aaaaaaaaaa")
    assert response.status_code == 200
    assert response.json()["freed_bytes"] >= 32
    assert not (out / "aaaaaaaaaa").exists()
    assert (out / "bbbbbbbbbb").exists()


def test_delete_rejects_unsafe_or_unknown_ids(tmp_path):
    out, app = _app(tmp_path)
    client = TestClient(app)

    assert client.delete("/api/pipeline/jobs/..%2F..%2Fetc").status_code in (400, 404, 405)
    assert client.delete("/api/pipeline/jobs/deadbeef00").status_code == 404


def test_cleanup_dry_run_then_real_respects_keep_latest(tmp_path):
    out, app = _app(tmp_path)
    _job_dir(out, "1111111111", age_days=90, files={"clip_0.mp4": 16})
    _job_dir(out, "2222222222", age_days=60, files={"clip_0.mp4": 16})
    _job_dir(out, "3333333333", age_days=2, files={"clip_0.mp4": 16})
    client = TestClient(app)

    preview = client.post(
        "/api/storage/cleanup",
        json={"older_than_days": 30, "keep_latest": 1, "dry_run": True},
    ).json()
    assert preview["dry_run"] is True
    assert {job["job_id"] for job in preview["removed"]} == {"1111111111", "2222222222"}
    assert (out / "1111111111").exists()

    result = client.post(
        "/api/storage/cleanup",
        json={"older_than_days": 30, "keep_latest": 1},
    ).json()
    assert {job["job_id"] for job in result["removed"]} == {"1111111111", "2222222222"}
    assert not (out / "1111111111").exists()
    assert (out / "3333333333").exists()


def test_workspaces_list_campaign_folders_but_not_jobs(tmp_path):
    out, app = _app(tmp_path)
    _job_dir(out, "cccccccccc", age_days=1, files={"clip_0.mp4": 16})
    campaign = out / "spring_campaign"
    campaign.mkdir()
    (campaign / "clip_01.mp4").write_bytes(b"\0" * 48)
    project = tmp_path / "work" / "spring_assets"
    project.mkdir()
    (project / "source.mp4").write_bytes(b"\0" * 128)
    client = TestClient(app)

    body = client.get("/api/storage").json()
    names = {item["name"] for item in body["workspaces"]}

    assert "cccccccccc" not in names
    assert {"spring_campaign", "spring_assets"} <= names
    assert body["workspaces_bytes"] >= 48 + 128
    by_name = {item["name"]: item for item in body["workspaces"]}
    assert by_name["spring_campaign"]["root"] == "outputs"
    assert by_name["spring_assets"]["root"] == "work"


def test_delete_workspace_removes_the_folder(tmp_path):
    out, app = _app(tmp_path)
    campaign = out / "finished_campaign"
    campaign.mkdir()
    (campaign / "clip_01.mp4").write_bytes(b"\0" * 64)
    client = TestClient(app)

    response = client.delete("/api/storage/workspaces/outputs/finished_campaign")
    assert response.status_code == 200
    assert response.json()["freed_bytes"] >= 64
    assert not campaign.exists()


@pytest.mark.parametrize("path", [
    "/api/storage/workspaces/nope/finished_campaign",
    "/api/storage/workspaces/outputs/..",
    "/api/storage/workspaces/outputs/%2E%2E",
])
def test_delete_workspace_rejects_unknown_root_and_traversal(tmp_path, path):
    out, app = _app(tmp_path)
    campaign = out / "finished_campaign"
    campaign.mkdir()
    client = TestClient(app)

    # The router normalises some traversals into a path with no DELETE route.
    assert client.delete(path).status_code in (400, 404, 405)
    assert campaign.exists()


def test_compact_drops_intermediates_behind_a_render(tmp_path):
    out, app = _app(tmp_path)
    _job_dir(
        out,
        "abcdef1234",
        age_days=1,
        files={
            "clip_0.mp4": 100,
            "clip_0_vertical.mp4": 100,
            "clip_0_captions.mp4": 100,
            "clip_1.mp4": 100,
            "transcript.json": 10,
        },
    )
    client = TestClient(app)

    result = client.post("/api/pipeline/jobs/abcdef1234/compact").json()
    names = {item["name"] for item in result["removed"]}
    assert names == {"clip_0.mp4", "clip_0_vertical.mp4"}
    assert (out / "abcdef1234" / "clip_0_captions.mp4").exists()
    # No captioned render for clip 1, so its cut is the only copy and stays.
    assert (out / "abcdef1234" / "clip_1.mp4").exists()
