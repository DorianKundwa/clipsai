import json
import os
import subprocess
from datetime import datetime

import pytest

import clipsai.workflow.media as media
from clipsai import Clip, Transcription
from clipsai.ai import AIClip
from clipsai.workflow import JobStore, PipelineConfig, PipelineConfigError

SENTENCES = [
    "Most people get this completely wrong about editing short videos.",
    "The first three seconds decide whether anyone keeps watching.",
    "I tested forty clips last month and the numbers were brutal.",
]


def _transcription(sentences=SENTENCES, char_duration=0.08, gap=0.12):
    char_info = []
    clock = 0.0
    for sentence in sentences:
        for word in sentence.split(" "):
            for char in word:
                char_info.append(
                    {
                        "char": char,
                        "start_time": round(clock, 3),
                        "end_time": round(clock + char_duration, 3),
                        "speaker": 0,
                    }
                )
                clock += char_duration
            char_info.append(
                {"char": " ", "start_time": None, "end_time": None, "speaker": 0}
            )
            clock += gap
    return Transcription(
        {
            "source_software": "TestSoftware",
            "time_created": datetime.now(),
            "language": "en",
            "num_speakers": 1,
            "char_info": char_info,
        }
    )


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=0x203040:s=320x240:d=6:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
    )
    return str(path)


@pytest.fixture
def transcript_file(tmp_path):
    path = tmp_path / "transcript.json"
    _transcription().store_as_json_file(str(path))
    return str(path)


class FakePublisher:
    def __init__(self):
        self.calls = []

    def assert_ready(self):
        return None

    def publish_media(self, path, platforms, caption="", options=None, when="now",
                      job_id="", clip_index=0):
        self.calls.append(
            {
                "path": path,
                "platforms": list(platforms),
                "caption": caption,
                "when": when,
                "job_id": job_id,
                "clip_index": clip_index,
            }
        )
        return {
            "media_id": "media-{}".format(clip_index),
            "platforms": list(platforms),
            "external_ids": ["https://post/{}".format(clip_index)],
            "idempotency_key": "key-{}".format(clip_index),
        }


def test_config_validation_rejects_bad_ranges():
    with pytest.raises(PipelineConfigError):
        PipelineConfig(min_clip_duration=60, max_clip_duration=15).validate()
    with pytest.raises(PipelineConfigError):
        PipelineConfig(aspect_ratio="2:1").validate()
    with pytest.raises(PipelineConfigError):
        PipelineConfig(method="magic").validate()
    with pytest.raises(PipelineConfigError):
        PipelineConfig(publish=True, platforms=(), when="now").validate()


def test_fresh_job_next_options(tmp_path):
    store = JobStore(tmp_path / "outputs")
    job = store.create(PipelineConfig())
    options = {option["stage"]: option for option in job.next_options()}

    assert options["transcribe"]["enabled"] is True
    assert options["find_clips"]["enabled"] is False
    assert "Transcribe" in options["find_clips"]["reason"]
    assert store.get(job.id) is job


def test_stage_prerequisites_are_enforced(tmp_path):
    store = JobStore(tmp_path / "outputs")
    job = store.create(PipelineConfig())
    result = job.run("trim")
    assert result.ok is False
    assert "Find clips" in result.error
    publish = next(o for o in result.options if o["stage"] == "publish")
    assert publish["enabled"] is False
    assert "Trim clips" in publish["reason"]


def test_pipeline_stages_produce_artifacts(
    tmp_path, sample_video, transcript_file, monkeypatch
):
    clips = [Clip(0.0, 2.0, 0, 10), Clip(2.5, 4.0, 10, 20)]
    monkeypatch.setattr(media, "find_clips", lambda transcription, config: clips)

    store = JobStore(tmp_path / "outputs")
    job = store.create(
        PipelineConfig(
            source_path=sample_video,
            transcript_path=transcript_file,
            top_n=2,
            captions=True,
            render_vertical=False,
        )
    )

    assert job.run("transcribe").ok is True
    assert job.run("find_clips").ok is True
    assert len(job.clips) == 2
    assert job.run("trim").ok is True
    assert len(job.trimmed) == 2
    assert all(os.path.isfile(path) for path in job.trimmed)

    result = job.run("captions")
    assert result.ok is True, result.error
    assert len(job.captions) == 2
    for item in job.captions:
        assert os.path.isfile(item["srt"])
        assert item["video"] and os.path.isfile(item["video"])

    rows = job.clip_rows()
    assert [row[0] for row in rows] == [0, 1]
    assert rows[0][-1]

    manifest = json.loads((job.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] == ["transcribe", "find_clips", "trim", "captions"]
    assert manifest["artifacts"]["trimmed"] == job.trimmed

    enabled = [o["stage"] for o in job.next_options() if o["enabled"]]
    assert "publish" in enabled
    assert "package" in enabled


def test_ai_clips_are_reported_in_rows(tmp_path, transcript_file, monkeypatch):
    ai_clip = AIClip(
        start_time=0.5, end_time=2.0, score=91, hook="40 clips, 2x viewers",
        title="The hook rule",
    )
    monkeypatch.setattr(media, "find_clips", lambda transcription, config: [ai_clip])

    job = JobStore(tmp_path / "outputs").create(
        PipelineConfig(transcript_path=transcript_file, method="deepseek")
    )
    assert job.run("transcribe").ok is True
    assert job.run("find_clips").ok is True
    row = job.clip_rows()[0]
    assert row[4] == 91.0
    assert row[5] == "40 clips, 2x viewers"
    assert row[6] == "The hook rule"


def test_publish_stage_uses_trimmed_clip_and_manifest(
    tmp_path, sample_video, transcript_file, monkeypatch
):
    monkeypatch.setattr(
        media, "find_clips", lambda transcription, config: [Clip(0.0, 2.0, 0, 10)]
    )
    publisher = FakePublisher()
    config = PipelineConfig(
        source_path=sample_video,
        transcript_path=transcript_file,
        top_n=1,
        publish=True,
        platforms=("instagram",),
        when="now",
        render_vertical=False,
    )
    job = JobStore(tmp_path / "outputs").create(config, publish_client=publisher)

    assert job.run("transcribe").ok is True
    assert job.run("find_clips").ok is True
    assert job.run("trim").ok is True

    result = job.run("publish")
    assert result.ok is True, result.error
    assert len(job.published) == 1
    assert publisher.calls[0]["platforms"] == ["instagram"]
    assert publisher.calls[0]["path"] == job.trimmed[0]

    manifest = json.loads((job.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["published"][0]["external_ids"] == [
        "https://post/0"
    ]


def test_publish_without_a_key_fails_cleanly(
    tmp_path, sample_video, transcript_file, monkeypatch
):
    monkeypatch.delenv("INDIEPOST_API_KEY", raising=False)
    monkeypatch.setattr(
        media, "find_clips", lambda transcription, config: [Clip(0.0, 2.0, 0, 10)]
    )
    job = JobStore(tmp_path / "outputs").create(
        PipelineConfig(
            source_path=sample_video,
            transcript_path=transcript_file,
            top_n=1,
            publish=True,
            platforms=("instagram",),
            render_vertical=False,
        )
    )
    assert job.run("transcribe").ok is True
    assert job.run("find_clips").ok is True
    assert job.run("trim").ok is True

    result = job.run("publish")
    assert result.ok is False
    assert "INDIEPOST_API_KEY" in result.error


def test_best_video_maps_trimmed_files_by_position(tmp_path):
    job = JobStore(tmp_path / "outputs").create(PipelineConfig())
    job.clips = [Clip(0.0, 1.0, 0, 5), Clip(1.0, 2.0, 5, 9), Clip(2.0, 3.0, 9, 13)]
    # Clip 2 is not exported, so the files on disk belong to clips 1 and 2.
    job.selected = [1, 2]
    job.trimmed = ["/out/clip_1.mp4", "/out/clip_2.mp4"]

    assert job._best_video(1) == "/out/clip_1.mp4"
    assert job._best_video(2) == "/out/clip_2.mp4"
    assert job._best_video(0) == ""


def test_failed_trim_leaves_no_partial_state(
    tmp_path, sample_video, transcript_file, monkeypatch
):
    monkeypatch.setattr(
        media,
        "find_clips",
        lambda transcription, config: [Clip(0.0, 2.0, 0, 10), Clip(2.5, 4.0, 10, 20)],
    )
    written = []

    def fake_trim(media_path, start_time, end_time, out_path):
        written.append(out_path)
        if len(written) == 2:
            raise RuntimeError("ffmpeg failed on the second clip")
        with open(out_path, "wb") as handle:
            handle.write(b"not really a video")
        return out_path

    monkeypatch.setattr(media, "trim_clip", fake_trim)

    job = JobStore(tmp_path / "outputs").create(
        PipelineConfig(
            source_path=sample_video,
            transcript_path=transcript_file,
            top_n=2,
            render_vertical=False,
        )
    )
    assert job.run("transcribe").ok is True
    assert job.run("find_clips").ok is True

    result = job.run("trim")
    assert result.ok is False
    assert "ffmpeg failed" in result.error
    assert "trim" not in job.completed
    assert job.trimmed == []

    options = {option["stage"]: option for option in job.next_options()}
    assert options["trim"]["enabled"] is True
    assert options["publish"]["enabled"] is False

    manifest = json.loads((job.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] == ["transcribe", "find_clips"]
    assert manifest["artifacts"]["trimmed"] == []


def test_failed_captions_leave_no_partial_state(
    tmp_path, sample_video, transcript_file, monkeypatch
):
    monkeypatch.setattr(
        media,
        "find_clips",
        lambda transcription, config: [Clip(0.0, 2.0, 0, 10), Clip(2.5, 4.0, 10, 20)],
    )
    job = JobStore(tmp_path / "outputs").create(
        PipelineConfig(
            source_path=sample_video,
            transcript_path=transcript_file,
            top_n=2,
            captions=True,
            render_vertical=False,
        )
    )
    assert job.run("transcribe").ok is True
    assert job.run("find_clips").ok is True
    assert job.run("trim").ok is True

    calls = []

    def fake_captions(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("libass is missing")
        return {"video": None, "srt": str(job.root / "clip_0.srt")}

    monkeypatch.setattr(media, "build_and_burn_captions", fake_captions)

    result = job.run("captions")
    assert result.ok is False
    assert "libass" in result.error
    assert "captions" not in job.completed
    assert job.captions == []
    # The trim output is still valid, so it stays done.
    assert "trim" in job.completed

    manifest = json.loads((job.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] == ["transcribe", "find_clips", "trim"]


def test_stage_failure_is_reported_without_crashing(tmp_path, transcript_file):
    job = JobStore(tmp_path / "outputs").create(
        PipelineConfig(transcript_path=transcript_file)
    )
    assert job.run("transcribe").ok is True
    # no source video, but find_clips is real here only for the option list
    result = job.run("trim")
    assert result.ok is False
    assert result.error


def test_clean_video_prefers_trimmed_over_hooked_for_thumbnails(
    tmp_path, transcript_file
):
    job = JobStore(tmp_path / "outputs").create(
        PipelineConfig(transcript_path=transcript_file)
    )
    job.selected = [1]
    job.trimmed = ["/out/clip_1.mp4"]
    job.reframed_by_index = {1: "/out/clip_1_vertical.mp4"}
    job.packages = [{"index": 1, "hooked": "/out/clip_1_hook.mp4"}]

    assert job._clean_video(1) == "/out/clip_1.mp4"


def test_type_checker_helpers_accept_standard_arguments():
    from clipsai.utils.type_checker import TypeChecker

    tc = TypeChecker()
    assert tc.is_type(42, (int,)) is True
    assert tc.is_type("x", (int,)) is False
    assert tc.are_list_elems_of_type(["a", "b"], (str,)) is True
    assert tc.are_list_elems_of_type(["a", 1], (str,)) is False
