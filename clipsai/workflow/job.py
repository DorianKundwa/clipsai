"""
Guided pipeline job: fixed stages, artifacts on disk, next-step options.

Stages: transcribe -> find_clips -> trim -> reframe -> captions -> package ->
publish. Each stage enforces its prerequisites, stores its artifacts under
``outputs/<job_id>/`` and returns a ``StageResult`` with the choices that make
sense next.
"""

# standard library imports
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# current package imports
from . import media
from .config import PipelineConfig

STAGES = (
    "transcribe",
    "find_clips",
    "trim",
    "reframe",
    "captions",
    "package",
    "finish",
    "publish",
)

STAGE_LABELS = {
    "transcribe": "Transcribe",
    "find_clips": "Find clips",
    "trim": "Trim clips",
    "reframe": "Reframe to vertical",
    "captions": "Add captions",
    "package": "AI packaging",
    "finish": "Master export",
    "publish": "Publish",
}

REQUIRES = {
    "transcribe": (),
    "find_clips": ("transcribe",),
    "trim": ("find_clips",),
    "reframe": ("trim",),
    "captions": ("trim",),
    "package": ("find_clips",),
    "finish": ("trim",),
    "publish": ("trim",),
}


_JOB_ID_RE = re.compile(r"^[0-9a-f]{10}$")
_CLIP_RENDER_RE = re.compile(r"^clip_(\d+)_(?:captions|hook|effects)\.mp4$")
_CLIP_PLAIN_RE = re.compile(r"^clip_(\d+)(?:_vertical)?\.mp4$")
_TEMP_FILE_RE = re.compile(r"^(?:\..*\.part|.*\.tmp)$")


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _disk_entry(path: Path, *, live: bool) -> dict:
    """Size and age of one job folder, using its manifest when it has one."""
    created = ""
    updated = ""
    manifest = path / "manifest.json"
    if manifest.is_file():
        try:
            with open(manifest, encoding="utf-8") as handle:
                data = json.load(handle)
            created = str(data.get("created") or "")
            updated = str(data.get("updated") or "")
        except (OSError, ValueError):
            pass

    files = 0
    size = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                size += os.path.getsize(os.path.join(root, name))
                files += 1
            except OSError:
                pass

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    stamp = updated or created
    try:
        moment = datetime.fromisoformat(stamp) if stamp else datetime.fromtimestamp(mtime)
    except ValueError:
        moment = datetime.fromtimestamp(mtime)

    return {
        "job_id": path.name,
        "path": str(path),
        "size": int(size),
        "files": int(files),
        "created": created,
        "updated": moment.isoformat(timespec="seconds"),
        "age_days": round(max(0.0, (datetime.now() - moment).total_seconds() / 86400), 2),
        "live": bool(live),
    }


def _workspace_entry(path: Path, *, root_key: str) -> dict:
    """Size and age of one campaign workspace folder."""
    files = 0
    size = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                size += os.path.getsize(os.path.join(root, name))
                files += 1
            except OSError:
                pass
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return {
        "name": path.name,
        "root": root_key,
        "path": str(path),
        "size": int(size),
        "files": int(files),
        "updated": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        "age_days": round(max(0.0, (datetime.now().timestamp() - mtime) / 86400), 2),
    }


class WorkflowError(Exception):
    """A pipeline stage could not complete."""


@dataclass
class StageResult:
    stage: str
    ok: bool
    message: str = ""
    error: str = ""
    artifacts: dict = field(default_factory=dict)
    options: "list[dict]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _write_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
    return str(path)


class PipelineJob:
    """One pipeline run: settings, artifacts and stage results."""

    def __init__(
        self,
        config: PipelineConfig,
        root: "str | Path",
        store: "JobStore | None" = None,
        llm_client=None,
        publish_client=None,
    ) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.root = Path(root) / self.id
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config
        self._store = store
        self._llm = llm_client
        self._publish = publish_client
        self._lock = threading.Lock()
        self.created = datetime.now().isoformat(timespec="seconds")

        self.transcription = None
        self.clips: "list" = []
        self.selected: "list[int]" = []
        self.trimmed: "list[str]" = []
        self.reframed: "list[str]" = []
        self.reframed_by_index: "dict[int, str]" = {}
        self.captions: "list[dict]" = []
        self.packages: "list[dict]" = []
        self.final: "dict[int, str]" = {}
        self.published: "list[dict]" = []
        self.completed: "set[str]" = set()
        self.stage_state: "dict[str, dict]" = {}
        self._save_manifest()

    # ------------------------------------------------------------------ #
    # Config / artifacts
    # ------------------------------------------------------------------ #

    def set_config(self, config: PipelineConfig) -> None:
        config.validate()
        source_changed = config.source_path != self.config.source_path
        transcript_changed = config.transcript_path != self.config.transcript_path
        self.config = config
        if source_changed or transcript_changed:
            self.reset()

    def reset(self) -> None:
        self.transcription = None
        self.clips = []
        self.selected = []
        self.trimmed = []
        self.reframed = []
        self.reframed_by_index = {}
        self.captions = []
        self.packages = []
        self.final = {}
        self.published = []
        self.completed = set()
        self.stage_state = {}
        self._save_manifest()

    def _clip(self, index: int):
        return self.clips[index]

    def _best_video(self, index: int) -> str:
        if self.final.get(index):
            return self.final[index]
        for group in (self.packages, self.captions, self.reframed):
            if group and isinstance(group[0], dict):
                for item in group:
                    if item.get("index") == index:
                        for key in ("effects", "hooked", "video"):
                            if item.get(key):
                                return item[key]
        if index in self.reframed_by_index:
            return self.reframed_by_index[index]
        # ``trimmed`` is parallel to ``selected``, not indexed by clip number:
        # clip 7 can be the first (only) file written to disk.
        if index in self.selected:
            position = self.selected.index(index)
            if position < len(self.trimmed):
                return self.trimmed[position]
        return ""

    def _clean_video(self, index: int) -> str:
        """Prefer un-hooked/un-captioned video for clean thumbnail frames."""
        if index in self.selected:
            position = self.selected.index(index)
            if position < len(self.trimmed) and self.trimmed[position]:
                return self.trimmed[position]
        if index in self.reframed_by_index and self.reframed_by_index[index]:
            return self.reframed_by_index[index]
        return self._best_video(index)

    def _reset_outputs(self, stage: str, include_stage: bool = False) -> None:
        """Forget the artifacts of ``stage`` (optionally) and of every later stage.

        Called after a successful stage to drop stale downstream output, and
        after a failed one so a half-written artifact cannot look complete.
        """
        start = STAGES.index(stage) + (0 if include_stage else 1)
        cleared = set(STAGES[start:])
        for name in cleared:
            self.completed.discard(name)
            self.stage_state.pop(name, None)
        if "transcribe" in cleared:
            self.transcription = None
        if "find_clips" in cleared:
            self.clips = []
            self.selected = []
        if "trim" in cleared:
            self.trimmed = []
        if "reframe" in cleared:
            self.reframed = []
            self.reframed_by_index = {}
        if "captions" in cleared:
            self.captions = []
        if "package" in cleared:
            self.packages = []
        if "finish" in cleared:
            self.final = {}
        if "publish" in cleared:
            self.published = []

    def clip_rows(self) -> "list[list]":
        """Rows for the UI clip table."""
        rows = []
        for index, clip in enumerate(self.clips):
            start = float(getattr(clip, "start_time", 0.0))
            end = float(getattr(clip, "end_time", 0.0))
            text = ""
            if self.transcription is not None:
                try:
                    chars = self.transcription.get_char_info(start, end)
                    text = " ".join(
                        "".join(str(c.get("char") or "") for c in chars).split()
                    )[:180]
                except Exception:  # noqa: BLE001 - table text is best effort
                    text = ""
            rows.append(
                [
                    index,
                    round(start, 2),
                    round(end, 2),
                    round(end - start, 2),
                    round(float(getattr(clip, "score", 0.0)), 1),
                    getattr(clip, "hook", ""),
                    getattr(clip, "title", ""),
                    text,
                ]
            )
        return rows

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #

    def run(self, stage: str, progress=None) -> StageResult:
        stage = str(stage or "").strip().lower()
        if stage not in STAGES:
            return StageResult(
                stage=stage,
                ok=False,
                error="Unknown stage '{}'. Choose one of: {}.".format(
                    stage, ", ".join(STAGES)
                ),
                options=self.next_options(),
            )
        missing = [name for name in REQUIRES[stage] if name not in self.completed]
        if missing:
            labels = ", ".join(STAGE_LABELS[name] for name in missing)
            return StageResult(
                stage=stage,
                ok=False,
                error="Run {} first.".format(labels),
                options=self.next_options(),
            )

        with self._lock:
            try:
                self.config.validate()
                handler = getattr(self, "_stage_" + stage)
                message, artifacts = handler(progress)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                logging.exception("Pipeline stage '%s' failed", stage)
                # Drop this stage's half-written artifacts and everything that
                # depended on them, so no stale file looks like a finished run.
                self._reset_outputs(stage, include_stage=True)
                self.stage_state[stage] = {
                    "ok": False,
                    "message": str(exc),
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
                self._save_manifest()
                return StageResult(
                    stage=stage,
                    ok=False,
                    error=str(exc),
                    options=self.next_options(),
                )

            self._reset_outputs(stage)
            self.completed.add(stage)
            self.stage_state[stage] = {
                "ok": True,
                "message": message,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            self._save_manifest()
            return StageResult(
                stage=stage,
                ok=True,
                message=message,
                artifacts=artifacts,
                options=self.next_options(),
            )

    def run_all(self, progress=None) -> "list[StageResult]":
        order = ["transcribe", "find_clips", "trim"]
        if self.config.render_vertical:
            order.append("reframe")
        if self.config.captions:
            order.append("captions")
        if self.config.package:
            order.append("package")
        if str(self.config.export_profile or "off") != "off":
            order.append("finish")
        if self.config.publish:
            order.append("publish")

        results = []
        for stage in order:
            result = self.run(stage, progress=progress)
            results.append(result)
            if not result.ok:
                break
        return results

    # ------------------------------------------------------------------ #
    # Stage implementations
    # ------------------------------------------------------------------ #

    def _stage_transcribe(self, progress) -> "tuple[str, dict]":
        transcript_path = self.root / "transcript.json"
        if self.config.transcript_path:
            if not os.path.isfile(self.config.transcript_path):
                raise WorkflowError(
                    "Transcript file '{}' does not exist.".format(
                        self.config.transcript_path
                    )
                )
            from clipsai import Transcription
            from clipsai.filesys.json_file import JSONFile

            transcription = Transcription(JSONFile(self.config.transcript_path))
            transcription.store_as_json_file(str(transcript_path))
        else:
            if not self.config.source_path or not os.path.isfile(
                self.config.source_path
            ):
                raise WorkflowError("Choose a source video or an existing transcript.")
            transcription = media.transcribe_media(
                self.config.source_path,
                self.config,
                progress=progress,
            )
            transcription.store_as_json_file(str(transcript_path))

        self.transcription = transcription
        return (
            "Transcribed {:.1f}s of audio ({} words).".format(
                float(transcription.end_time), len(transcription.get_word_info())
            ),
            {"transcript": str(transcript_path)},
        )

    def _stage_find_clips(self, progress) -> "tuple[str, dict]":
        if self.transcription is None:
            raise WorkflowError("No transcription available.")
        clips = media.find_clips(self.transcription, self.config)
        if not clips:
            raise WorkflowError("No clips were found in this transcription.")
        self.clips = list(clips)
        self.selected = list(range(min(len(clips), int(self.config.top_n))))
        clips_path = self.root / "clips.json"
        _write_json(clips_path, [self._clip_record(c) for c in self.clips])
        return (
            "Found {} clip(s); selected {} for export.".format(
                len(self.clips), len(self.selected)
            ),
            {"clips": str(clips_path)},
        )

    def _stage_trim(self, progress) -> "tuple[str, dict]":
        if not self.config.source_path or not os.path.isfile(self.config.source_path):
            raise WorkflowError("A source video is required to trim clips.")
        if not self.selected:
            raise WorkflowError("No clips are selected.")
        trimmed = []
        for index in self.selected:
            clip = self._clip(index)
            out_path = self.root / "clip_{}.mp4".format(index)
            media.trim_clip(
                self.config.source_path,
                float(clip.start_time),
                float(clip.end_time),
                str(out_path),
            )
            trimmed.append(str(out_path))
        # Committed at the end: a failure halfway leaves ``trimmed`` untouched.
        self.trimmed = trimmed
        return (
            "Trimmed {} clip(s).".format(len(trimmed)),
            {"trimmed": list(trimmed)},
        )

    def _stage_reframe(self, progress) -> "tuple[str, dict]":
        if not self.config.render_vertical:
            raise WorkflowError(
                "Vertical rendering is disabled. Enable it in Output & captions."
            )
        if not self.trimmed:
            raise WorkflowError("Trim the clips first.")
        reframed = []
        reframed_by_index = {}
        for index, path in zip(self.selected, self.trimmed):
            out_path = self.root / "clip_{}_vertical.mp4".format(index)
            media.reframe_clip(path, str(out_path), self.config, progress=progress)
            reframed.append(str(out_path))
            reframed_by_index[index] = str(out_path)
        self.reframed = reframed
        self.reframed_by_index = reframed_by_index
        return (
            "Reframed {} clip(s) to {}.".format(len(reframed), self.config.aspect_ratio),
            {"reframed": list(reframed)},
        )

    def _stage_captions(self, progress) -> "tuple[str, dict]":
        if self.transcription is None:
            raise WorkflowError("No transcription available.")
        captions = []
        for index in self.selected:
            clip = self._clip(index)
            prefix = str(self.root / "clip_{}_captions".format(index))
            video_path = self._best_video(index) or None
            result = media.build_and_burn_captions(
                self.transcription,
                float(clip.start_time),
                float(clip.end_time),
                video_path,
                prefix,
                self.config,
            )
            result["index"] = index
            captions.append(result)
        self.captions = captions
        return (
            "Created captions for {} clip(s){}.".format(
                len(captions),
                " and translated them" if self.config.translate_to not in ("", "off") else "",
            ),
            {"captions": [c["video"] or c["srt"] for c in captions]},
        )

    def _stage_package(self, progress) -> "tuple[str, dict]":
        from clipsai.ai import (
            LLMClient,
            apply_edits,
            burn_hook,
            create_thumbnail,
            package_clip,
            suggest_edits,
            transcript_text,
        )

        if self.transcription is None:
            raise WorkflowError("No transcription available.")
        client = self._llm or LLMClient()
        client.assert_ready()
        packages = []

        for index in self.selected:
            clip = self._clip(index)
            start = float(clip.start_time)
            end = float(clip.end_time)
            metadata = package_clip(
                client,
                self.transcription,
                start,
                end,
                language=self.transcription.language or "en",
            )
            package_path = _write_json(
                self.root / "clip_{}_package.json".format(index), metadata
            )
            record = dict(metadata)
            record.update({"index": index, "package": package_path})

            video = self._best_video(index)
            clean_video = self._clean_video(index)
            hook_text = metadata.get("hook") or metadata.get("title") or ""

            if self.config.hook and hook_text and video:
                hooked = self.root / "clip_{}_hook.mp4".format(index)
                burn_hook(
                    video,
                    hook_text,
                    str(hooked),
                    style=self.config.hook_style,
                    position=self.config.hook_position,
                    font=self.config.hook_font,
                    kicker=self.config.hook_kicker,
                    start=0.0,
                    end=float(self.config.hook_seconds),
                )
                record["hooked"] = str(hooked)
                video = str(hooked)

            if self.config.thumbnail and hook_text and clean_video:
                thumb = self.root / "clip_{}_thumb.jpg".format(index)
                create_thumbnail(clean_video, hook_text, str(thumb), position="left")
                record["thumbnail"] = str(thumb)

            if self.config.effects and video:
                text = transcript_text(self.transcription, start, end)
                edits = suggest_edits(
                    client,
                    text,
                    duration=end - start,
                    language=self.transcription.language or "en",
                    has_captions=bool(self.captions),
                )
                if edits:
                    effects_path = self.root / "clip_{}_effects.mp4".format(index)
                    apply_edits(
                        video,
                        edits,
                        str(effects_path),
                        has_captions=bool(self.captions),
                    )
                    record["effects"] = str(effects_path)
                    record["edits"] = edits

            packages.append(record)

        self.packages = packages
        return (
            "Packaged {} clip(s) with AI copy{}.".format(
                len(packages), " and thumbnails" if self.config.thumbnail else ""
            ),
            {"packages": [p["package"] for p in packages]},
        )

    def _stage_finish(self, progress) -> "tuple[str, dict]":
        """Deliver each clip at a platform profile with normalized loudness."""
        if str(self.config.export_profile or "off") == "off":
            raise WorkflowError(
                "Choose an export profile (Shorts, Reels, TikTok, YouTube or Square)."
            )
        if not self.selected:
            raise WorkflowError("No clips are selected.")

        from clipsai.render import finish_clip, parse_crop

        crop = parse_crop(self.config.source_crop)
        finals = {}
        for index in self.selected:
            video = self._best_video(index)
            if not video or not os.path.isfile(video):
                raise WorkflowError(
                    "Clip {} has no rendered video to finish.".format(index)
                )
            clip = self._clip(index)
            duration = float(clip.end_time) - float(clip.start_time)
            punch_times = []
            if self.config.punch_ins:
                moment = 1.0
                while moment < duration - 0.6 and len(punch_times) < 6:
                    punch_times.append(round(moment, 2))
                    moment += 2.5
            out_path = self.root / "clip_{}_final.mp4".format(index)
            finish_clip(
                video,
                str(out_path),
                self.config.export_profile,
                pad="blur",
                grade=self.config.grade,
                crop=crop,
                punch_ins=punch_times,
                preset="medium",
            )
            finals[index] = str(out_path)

        self.final = finals
        return (
            "Mastered {} clip(s) to {}.".format(
                len(finals), self.config.export_profile
            ),
            {"final": list(finals.values())},
        )

    def _stage_publish(self, progress) -> "tuple[str, dict]":
        from clipsai.publish import IndiePostClient, PlatformOptions

        client = self._publish or IndiePostClient()
        client.assert_ready()

        results = []
        errors = []
        for index in self.selected:
            path = self._best_video(index)
            if not path:
                errors.append("clip {}: no rendered file".format(index))
                continue
            record = next(
                (p for p in self.packages if p.get("index") == index), {}
            )
            caption = (
                self.config.publish_caption
                or record.get("tiktok_caption")
                or record.get("instagram_caption")
                or record.get("summary", "")
            )
            title = (
                self.config.youtube_title
                or record.get("title", "")
                or "ClipsAI short {}".format(index)
            )
            vertical = self.config.aspect_ratio in ("9:16", "3:4", "4:5")
            options = PlatformOptions(
                youtube_title=title,
                youtube_format=self.config.youtube_format,
                tiktok_privacy=self.config.tiktok_privacy,
                ai_generated=self.config.ai_generated,
                instagram_format="reel" if vertical else "post",
                facebook_format="reel" if vertical else "post",
            )
            try:
                result = client.publish_media(
                    path,
                    self.config.platforms,
                    caption=caption,
                    options=options,
                    when=self.config.when,
                    job_id=self.id,
                    clip_index=index,
                )
                result.update({"index": index, "path": path, "title": title})
                results.append(result)
            except Exception as exc:  # noqa: BLE001 - report per clip
                errors.append("clip {}: {}".format(index, exc))

        self.published = results
        if not results:
            raise WorkflowError(
                "Publishing failed: {}".format("; ".join(errors) or "no clips")
            )
        message = "Published {} clip(s) to {}.".format(
            len(results), ", ".join(self.config.platforms)
        )
        if errors:
            message += " Some clips failed: {}".format("; ".join(errors))
        return message, {"published": results}

    # ------------------------------------------------------------------ #
    # Options / manifest
    # ------------------------------------------------------------------ #

    def next_options(self) -> "list[dict]":
        """Every stage with its availability after the current progress."""
        options = []
        for stage in STAGES:
            missing = [name for name in REQUIRES[stage] if name not in self.completed]
            done = stage in self.completed
            enabled = not missing and not done
            reason = ""
            if missing:
                reason = "Run {} first.".format(
                    ", ".join(STAGE_LABELS[name] for name in missing)
                )
            elif done:
                reason = "Already done."
            options.append(
                {
                    "stage": stage,
                    "label": STAGE_LABELS[stage],
                    "enabled": enabled,
                    "done": done,
                    "reason": reason,
                }
            )
        return options

    def next_enabled_stage(self) -> str:
        for option in self.next_options():
            if option["enabled"]:
                return option["stage"]
        return ""

    def _clip_record(self, clip) -> dict:
        record = {
            "start_time": round(float(clip.start_time), 3),
            "end_time": round(float(clip.end_time), 3),
        }
        if hasattr(clip, "score"):
            record.update(
                {
                    "predicted_score": float(getattr(clip, "score", 0.0)),
                    "viral_hook_text": getattr(clip, "hook", ""),
                    "video_title_for_youtube_short": getattr(clip, "title", ""),
                    "why": getattr(clip, "reason", ""),
                }
            )
        return record

    def manifest(self) -> dict:
        return {
            "job_id": self.id,
            "created": self.created,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "config": asdict(self.config),
            "completed": sorted(self.completed, key=STAGES.index),
            "stages": self.stage_state,
            "clips": [self._clip_record(clip) for clip in self.clips],
            "selected": list(self.selected),
            "artifacts": {
                "transcript": str(self.root / "transcript.json")
                if self.transcription is not None
                else "",
                "clips": str(self.root / "clips.json") if self.clips else "",
                "trimmed": list(self.trimmed),
                "reframed": list(self.reframed),
                "captions": self.captions,
                "packages": [p.get("package", "") for p in self.packages],
                "final": list(self.final.values()),
                "published": [
                    {
                        "index": r.get("index"),
                        "platforms": r.get("platforms"),
                        "external_ids": r.get("external_ids"),
                        "idempotency_key": r.get("idempotency_key"),
                        "media_id": r.get("media_id"),
                    }
                    for r in self.published
                ],
            },
        }

    def _save_manifest(self) -> str:
        return _write_json(self.root / "manifest.json", self.manifest())


class JobStore:
    """In-process registry of pipeline jobs, keyed by id."""

    def __init__(
        self,
        root: "str | Path" = "outputs",
        workspaces: "dict[str, str | Path] | None" = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: "dict[str, PipelineJob]" = {}
        self._lock = threading.Lock()
        self.workspaces: "dict[str, Path]" = {
            str(key): Path(value)
            for key, value in (workspaces or {}).items()
            if str(value or "")
        }

    def create(self, config: PipelineConfig, **kwargs) -> PipelineJob:
        config.validate()
        job = PipelineJob(config, self.root, store=self, **kwargs)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> "PipelineJob | None":
        with self._lock:
            return self._jobs.get(str(job_id or ""))

    def all(self) -> "list[PipelineJob]":
        with self._lock:
            return list(self._jobs.values())

    # ------------------------------------------------------------------ #
    # Storage: per-job size, deletion, retention
    # ------------------------------------------------------------------ #

    def path_for(self, job_id: str) -> Path:
        """Folder of one job, rejecting ids that could escape ``root``."""
        job_id = str(job_id or "").strip()
        if not _JOB_ID_RE.match(job_id):
            raise ValueError("Invalid job id: {!r}".format(job_id))
        return self.root / job_id

    def delete(self, job_id: str) -> int:
        """Delete one job's folder, whether it is live or left from an old run.

        Returns the number of bytes freed.
        """
        path = self.path_for(job_id)
        freed = _dir_size(path)
        with self._lock:
            self._jobs.pop(str(job_id), None)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        return freed

    def disk_jobs(self) -> "list[dict]":
        """Every pipeline job folder on disk, newest first.

        Jobs live in memory only, so folders written by an earlier server run are
        listed here too: they are the ones that otherwise pile up unseen.
        """
        entries = []
        if not self.root.is_dir():
            return entries
        for child in self.root.iterdir():
            try:
                if not child.is_dir() or not _JOB_ID_RE.match(child.name):
                    continue
            except OSError:
                continue
            entries.append(_disk_entry(child, live=self.get(child.name) is not None))
        entries.sort(key=lambda e: (e["updated"], e["job_id"]), reverse=True)
        return entries

    def workspace_entries(self) -> "list[dict]":
        """Campaign workspaces: every non-job folder in the workspace roots.

        These are the hand-built campaign folders (``outputs/<campaign>``) and the
        scratch material behind them (``work/<project>``), which the pipeline
        never lists but which take most of the space in practice.
        """
        entries = []
        for root_key, base in self.workspaces.items():
            if not base.is_dir():
                continue
            for child in base.iterdir():
                try:
                    if not child.is_dir() or child.name.startswith("."):
                        continue
                    if _JOB_ID_RE.match(child.name):
                        continue
                except OSError:
                    continue
                entries.append(_workspace_entry(child, root_key=root_key))
        entries.sort(key=lambda e: e["size"], reverse=True)
        return entries

    def delete_workspace(self, root_key: str, name: str) -> int:
        """Delete one campaign workspace folder; returns the bytes freed."""
        base = self.workspaces.get(str(root_key or ""))
        if base is None:
            raise ValueError("Unknown workspace root: {!r}".format(root_key))
        name = str(name or "").strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValueError("Invalid workspace name: {!r}".format(name))
        base_resolved = base.resolve()
        target = (base_resolved / name).resolve()
        if target.parent != base_resolved:
            raise ValueError("Invalid workspace name: {!r}".format(name))
        if not target.is_dir():
            raise FileNotFoundError(str(target))
        freed = _dir_size(target)
        shutil.rmtree(target)
        return freed

    def usage(self) -> dict:
        """Disk footprint of the output root, its jobs, workspaces and free space."""
        jobs = self.disk_jobs()
        jobs_bytes = sum(job["size"] for job in jobs)
        workspaces = self.workspace_entries()
        try:
            total, _used, free = shutil.disk_usage(str(self.root))
        except OSError:
            total, free = 0, 0
        return {
            "root": str(self.root.resolve()),
            "jobs": jobs,
            "jobs_bytes": jobs_bytes,
            "jobs_count": len(jobs),
            "workspaces": workspaces,
            "workspaces_bytes": sum(item["size"] for item in workspaces),
            "workspace_roots": {key: str(path.resolve()) for key, path in self.workspaces.items()},
            "disk_total_bytes": int(total),
            "disk_free_bytes": int(free),
        }

    def cleanup(
        self,
        *,
        older_than_days: "float | None" = None,
        keep_latest: "int | None" = None,
        max_total_bytes: "int | None" = None,
        dry_run: bool = False,
        is_running=None,
    ) -> dict:
        """Delete old job folders according to a retention policy.

        The newest ``keep_latest`` jobs are always protected, as is anything a
        stage is currently writing. ``max_total_bytes`` keeps deleting the oldest
        removable job until the remaining jobs fit the budget.
        """
        jobs = self.disk_jobs()
        running = is_running or (lambda job_id: False)

        protected = {job["job_id"] for job in jobs if job["live"] and running(job["job_id"])}
        if keep_latest and keep_latest > 0:
            protected.update(job["job_id"] for job in jobs[: int(keep_latest)])

        removable = [job for job in jobs if job["job_id"] not in protected]
        doomed = []

        if older_than_days is not None and older_than_days >= 0:
            doomed.extend(
                job for job in removable if job["age_days"] >= float(older_than_days)
            )

        chosen = {job["job_id"] for job in doomed}
        if max_total_bytes is not None and max_total_bytes >= 0:
            remaining = sum(job["size"] for job in jobs if job["job_id"] not in chosen)
            for job in sorted(removable, key=lambda j: j["updated"]):
                if remaining <= max_total_bytes:
                    break
                if job["job_id"] in chosen:
                    continue
                chosen.add(job["job_id"])
                doomed.append(job)
                remaining -= job["size"]

        removed = []
        freed = 0
        for job in doomed:
            if not dry_run:
                try:
                    freed += self.delete(job["job_id"])
                except OSError as exc:  # noqa: BLE001
                    logging.warning("Could not delete job %s: %s", job["job_id"], exc)
                    continue
            else:
                freed += job["size"]
            removed.append(job)

        return {
            "removed": removed,
            "freed_bytes": int(freed),
            "kept": len(jobs) - len(removed),
            "dry_run": bool(dry_run),
            "policy": {
                "older_than_days": older_than_days,
                "keep_latest": keep_latest,
                "max_total_bytes": max_total_bytes,
            },
        }

    def compact(self, job_id: str, *, dry_run: bool = False) -> dict:
        """Drop intermediates a finished job no longer needs.

        Once a captioned / hooked / effects render exists for a clip, the plain
        trimmed cut and the silent vertical reframe that produced it are dead
        weight. Source uploads, transcripts, manifests and every final render are
        kept so the job still lists and publishes.
        """
        path = self.path_for(job_id)
        removed = []
        freed = 0
        if not path.is_dir():
            raise FileNotFoundError(str(path))

        renders = set()
        for child in path.iterdir():
            if not child.is_file():
                continue
            match = _CLIP_RENDER_RE.match(child.name)
            if match:
                renders.add(int(match.group(1)))

        targets = []
        for child in path.iterdir():
            if not child.is_file():
                continue
            if _TEMP_FILE_RE.match(child.name):
                targets.append(child)
                continue
            match = _CLIP_PLAIN_RE.match(child.name)
            if match and int(match.group(1)) in renders:
                targets.append(child)

        for target in targets:
            try:
                size = target.stat().st_size
            except OSError:
                continue
            if not dry_run:
                try:
                    target.unlink()
                except OSError as exc:  # noqa: BLE001
                    logging.warning("Could not remove %s: %s", target, exc)
                    continue
            freed += size
            removed.append({"name": target.name, "size": size})

        return {"job_id": job_id, "removed": removed, "freed_bytes": int(freed),
                "dry_run": bool(dry_run)}
