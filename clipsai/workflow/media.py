"""
Media operations used by the pipeline stages.

Heavy ML imports (torch, whisperx, pyannote) stay inside the functions so the
workflow package and the UI can be imported quickly.

Model instances are cached per configuration for the life of the process, as
reloading them dominates per-request cost.
"""

# standard library imports
from __future__ import annotations

import json
import logging
import threading

# local imports
from clipsai.config import huggingface_token


class WorkflowError(Exception):
    """A pipeline stage could not complete."""


_CACHE_LOCK = threading.Lock()
_TRANSCRIBERS: dict = {}
_DIARIZERS: dict = {}
_RESIZERS: dict = {}


def _noop_progress(fraction: float, desc: str = "") -> None:
    return None


def _aspect_tuple(aspect_ratio: str) -> "tuple[int, int]":
    width, height = str(aspect_ratio).split(":")
    return int(width), int(height)


def _device(config) -> "str | None":
    value = getattr(config, "device", None)
    return None if value in (None, "", "auto") else value


def _get_transcriber(model_size, device, precision):
    from clipsai import Transcriber

    key = (model_size, device, precision)
    with _CACHE_LOCK:
        transcriber = _TRANSCRIBERS.get(key)
        if transcriber is None:
            transcriber = Transcriber(
                model_size=model_size, device=device, precision=precision
            )
            _TRANSCRIBERS[key] = transcriber
        return transcriber


def _get_diarizer(token, device):
    from clipsai.diarize.pyannote import PyannoteDiarizer

    key = (token, device)
    with _CACHE_LOCK:
        diarizer = _DIARIZERS.get(key)
        if diarizer is None:
            diarizer = PyannoteDiarizer(auth_token=token, device=device)
            _DIARIZERS[key] = diarizer
        return diarizer


def _get_resizer(face_detect_margin, face_detect_post_process, device):
    from clipsai.resize.resizer import Resizer

    key = (face_detect_margin, face_detect_post_process, device)
    with _CACHE_LOCK:
        resizer = _RESIZERS.get(key)
        if resizer is None:
            resizer = Resizer(
                face_detect_margin=int(face_detect_margin),
                face_detect_post_process=bool(face_detect_post_process),
                device=device,
            )
            _RESIZERS[key] = resizer
        return resizer


def transcribe_media(media_path: str, config, progress=None):
    """Transcribe a media file into a ``Transcription``."""
    progress = progress or _noop_progress
    progress(0.05, "Loading WhisperX model (first run downloads weights)...")
    transcriber = _get_transcriber(
        config.model_size, _device(config), config.precision
    )
    progress(0.35, "Transcribing media...")
    transcription = transcriber.transcribe(
        audio_file_path=str(media_path),
        iso6391_lang_code=config.language,
        batch_size=int(config.batch_size),
    )
    progress(0.95, "Transcription complete")
    return transcription


def find_clips(transcription, config):
    """Find clips with TextTiling or DeepSeek, per ``config.method``."""
    if config.method == "deepseek":
        from clipsai.ai import AIClipFinder

        return AIClipFinder(
            min_clip_duration=int(config.min_clip_duration),
            max_clip_duration=int(config.max_clip_duration),
            language=transcription.language or "en",
            max_clips=max(int(config.top_n), 8),
        ).find_clips(transcription)

    from clipsai import ClipFinder

    finder = ClipFinder(
        device=_device(config),
        min_clip_duration=int(config.min_clip_duration),
        max_clip_duration=int(config.max_clip_duration),
        cutoff_policy=config.cutoff_policy,
    )
    return finder.find_clips(transcription=transcription)


def trim_clip(media_path: str, start_time: float, end_time: float, out_path: str) -> str:
    """Cut a time range out of a media file, stream-copying the codecs."""
    from clipsai import MediaEditor

    editor = MediaEditor()
    media = editor.instantiate_as_temporal_media_file(str(media_path))
    result = editor.trim(
        media_file=media,
        start_time=float(start_time),
        end_time=float(end_time),
        trimmed_media_file_path=str(out_path),
        video_codec="copy",
        audio_codec="copy",
        crf="23",
        preset="medium",
    )
    if result is None:
        raise WorkflowError(
            "Trimming {} - {}s out of '{}' failed.".format(
                round(start_time, 2), round(end_time, 2), media_path
            )
        )
    return str(out_path)


def reframe_clip(video_path: str, out_path: str, config, progress=None) -> dict:
    """Diarize, detect scenes, pick crops and render a reframed clip."""
    progress = progress or _noop_progress
    token = huggingface_token()
    if not token:
        raise WorkflowError(
            "A HuggingFace/pyannote token is required for vertical rendering. "
            "Add HF_TOKEN to .env."
        )

    from clipsai.media.audiovideo_file import AudioVideoFile
    from clipsai.media.editor import MediaEditor
    from clipsai.media.video_file import VideoFile
    from clipsai.resize.vid_proc import detect_scenes

    media = AudioVideoFile(str(video_path))
    media.assert_has_audio_stream()
    media.assert_has_video_stream()

    device = _device(config)
    progress(0.1, "Diarizing speakers...")
    diarizer = _get_diarizer(token, device)
    segments = diarizer.diarize(media, 1.5, 6)

    progress(0.35, "Detecting scenes...")
    scene_changes = detect_scenes(media, 0.25)

    progress(0.45, "Detecting faces and choosing crops...")
    resizer = _get_resizer(20, False, device)
    crops = resizer.resize(
        video_file=media,
        speaker_segments=segments,
        scene_changes=scene_changes,
        aspect_ratio=_aspect_tuple(config.aspect_ratio),
        samples_per_segment=13,
        face_detect_width=960,
        n_face_detect_batches=8,
        scene_merge_threshold=0.25,
    )

    crops_path = str(out_path).rsplit(".", 1)[0] + ".crops.json"
    with open(crops_path, "w", encoding="utf-8") as handle:
        json.dump(crops.to_dict(), handle, indent=2)

    progress(0.7, "Rendering reframed video...")
    editor = MediaEditor()
    rendered = editor.resize_video(
        original_video_file=VideoFile(str(video_path)),
        resized_video_file_path=str(out_path),
        width=crops.crop_width,
        height=crops.crop_height,
        segments=crops.to_dict()["segments"],
        crf=str(int(config.crf)),
        preset=config.preset,
    )
    if rendered is None:
        raise WorkflowError("Rendering the reframed clip failed.")
    progress(0.95, "Reframe complete")
    return {
        "video": str(out_path),
        "crops": crops_path,
        "segments": len(crops.segments),
    }


def build_and_burn_captions(
    transcription,
    start_time: float,
    end_time: float,
    video_path: "str | None",
    out_prefix: str,
    config,
) -> dict:
    """Build cues for a clip, write SRT/ASS and optionally burn them in."""
    from clipsai.captions import build_cues, burn_captions, write_ass, write_srt

    cues = build_cues(
        transcription, start_time, end_time, preset=config.caption_preset
    )
    if not cues:
        raise WorkflowError("No speech was found in that clip.")

    if config.translate_to and config.translate_to != "off":
        from clipsai.ai import LLMClient, translate_cues

        cues = translate_cues(LLMClient(), cues, config.translate_to)

    srt_path = out_prefix + ".srt"
    ass_path = out_prefix + ".ass"
    write_srt(cues, srt_path)

    video_out = None
    if video_path:
        video_out = burn_captions(
            str(video_path),
            cues,
            out_prefix + ".mp4",
            preset=config.caption_preset,
        )
        # burn_captions writes the matching .ass next to the video
    else:
        write_ass(cues, ass_path, preset=config.caption_preset)

    return {
        "video": video_out,
        "srt": srt_path,
        "ass": ass_path,
        "cues": len(cues),
    }
