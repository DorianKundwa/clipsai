"""
Unified FastAPI web server for ClipsAI Studio.

Serves the built SvelteKit frontend with cross-origin isolation headers
(for multithreaded ``ffmpeg.wasm``) alongside the Python AI pipeline
(``clipsai.workflow``), DeepSeek metadata, and IndiePost publishing endpoints
on a single origin and port.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hmac
import importlib.metadata
import importlib.util
import json
import logging
import mimetypes
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import sys
import tempfile
import threading
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)

from clipsai.ai import LLMClient, LLMError, LLMResponseError, MissingAPIKeyError
from clipsai.config import AISettings, IndiePostSettings, load_env, service_status
from clipsai.publish.indiepost import (
    IndiePostAuthError,
    IndiePostClient,
    IndiePostError,
    extract_external_ids,
)
from clipsai.publish.models import (
    MAX_MEDIA_BYTES,
    PLATFORMS,
    TIKTOK_PRIVACY_LEVELS,
    PlatformOptions,
    PublishError,
    build_post_payload,
    validate_platforms,
)
from clipsai.workflow import (
    ASPECT_RATIOS,
    REQUIRES,
    STAGE_LABELS,
    STAGES,
    JobStore,
    PipelineConfig,
    PipelineConfigError,
    StageResult,
)

# Windows registry entries sometimes map .js/.mjs unexpectedly or omit .wasm,
# which breaks ES module scripts and ffmpeg.wasm loading under strict browsers.
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("CLIPSAI_OUTPUT_DIR", str(BASE_DIR / "outputs"))
)
DEFAULT_WEB_DIR = BASE_DIR / "web" / "build" / "client"

ISOLATION_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Origin-Agent-Cluster": "?1",
}

MODEL_SIZES = ["auto", "tiny", "base", "small", "medium", "large-v1", "large-v2"]
DEVICES = ["auto", "cpu", "cuda"]
LANGUAGES = ["auto", "en", "fr", "de", "es", "it", "ja", "zh", "nl", "uk", "pt"]
CUTOFF_POLICIES = ["high", "average", "low"]
CAPTION_STYLES = ["bold", "clean", "lime", "pill", "oneword"]
AI_LANGUAGES = [
    "en",
    "es",
    "fr",
    "de",
    "pt",
    "it",
    "nl",
    "pl",
    "uk",
    "ru",
    "tr",
    "ar",
    "hi",
    "ja",
    "ko",
    "zh",
    "id",
    "vi",
]

_TAG_RE = re.compile(r"^[a-z0-9_]{2,30}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_PUBLISH_CHUNK_BYTES = 64 * 1024

_METADATA_SYSTEM_PROMPT = """You write publishing metadata for short-form video clips.

You receive facts about one exported clip: its file name, trimmed length, aspect
ratio, colour look, the platforms it will be posted to, and an optional note from
the editor describing the content.

Rules:
- title: one line for YouTube, at most 90 characters. No hashtags, no emoji, no
  quotation marks, no clickbait. It must make sense on its own. Never headline
  technical facts (duration, aspect ratio, colour look): those describe the file,
  not the story. Prefer the editor's note, then the file name, but never copy
  the note verbatim: condense it into a headline with no trailing period.
- caption: one or two sentences usable on TikTok and Instagram, at most 220
  characters. No hashtags, no emoji, plain text, no leading label. If an existing
  caption is supplied, keep its intent and improve it instead of starting over.
- hashtags: 6 to 8 lowercase tags, letters/digits/underscore only, without '#'.
  Use real, widely searched words. No invented compounds, no spelled-out numbers,
  no tags about the aspect ratio or file format.
- Ground every word in the supplied facts or the editor's note. Never invent
  people, brands, places, events or claims that are not supported by them.
- Match the tone to the listed platforms; keep it neutral when the facts are thin.

Respond with JSON only, exactly this shape:
{"title":"...","caption":"...","hashtags":["..."]}"""


def _safe_filename(name: str, fallback: str = "upload.bin") -> str:
    base = Path(str(name or "")).name.strip()
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    return cleaned[:180] or fallback


def _refresh_env(env_file: Path) -> None:
    if env_file.is_file():
        load_env(env_file, override=True)


def _request_origin(request: Request) -> "tuple[str, str]":
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    proto = proto.split(",")[0].strip().lower()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        host = host.split(",")[0].strip().lower()
    else:
        host = (request.url.netloc or "").lower()
    return proto, host


def _check_same_origin(request: Request) -> None:
    header = request.headers.get("origin")
    if not header:
        return
    try:
        parsed = urlparse(header)
        origin_pair = (parsed.scheme.lower(), parsed.netloc.lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="Cross-origin requests are not allowed."
        ) from exc
    if not origin_pair[0] or origin_pair != _request_origin(request):
        raise HTTPException(
            status_code=403, detail="Cross-origin requests are not allowed."
        )


def _normalize_metadata(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    title = str(raw.get("title") or "").strip()[:100].rstrip(".。")
    caption = str(raw.get("caption") or "").strip()[:700]
    raw_tags = raw.get("hashtags") if isinstance(raw.get("hashtags"), list) else []
    hashtags: "list[str]" = []
    seen: "set[str]" = set()
    for item in raw_tags:
        tag = str(item).strip().lstrip("#").lower()
        if _TAG_RE.match(tag) and tag not in seen:
            seen.add(tag)
            hashtags.append(tag)
            if len(hashtags) >= 8:
                break
    if not title or not caption:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek returned incomplete metadata. Try again.",
        )
    return {"title": title, "caption": caption, "hashtags": hashtags}


def _decode_publish_header(raw: "str | None") -> "dict | None":
    if not raw:
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("ascii"))
        parsed = json.loads(payload.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _normalize_platforms(value) -> "list[str]":
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                items = parsed if isinstance(parsed, list) else []
            except ValueError:
                items = []
        else:
            items = text.split(",")
    else:
        items = []
    seen: "list[str]" = []
    for item in items:
        name = str(item).strip().lower()
        if name and name not in seen:
            seen.append(name)
    return seen


def _file_url(job_id: str, job_root: Path, raw_path: "str | None") -> "str | None":
    if not raw_path:
        return None
    try:
        target = Path(raw_path).resolve()
        root_resolved = job_root.resolve()
        if not target.is_relative_to(root_resolved):
            return None
        rel = target.relative_to(root_resolved).as_posix()
        return "/api/pipeline/jobs/{}/files/{}".format(job_id, rel)
    except OSError:
        return None


def _file_size(raw_path: "str | None") -> int:
    if not raw_path:
        return 0
    try:
        return Path(raw_path).stat().st_size
    except OSError:
        return 0


def _config_from_payload(
    data: dict, base: "PipelineConfig | None" = None
) -> PipelineConfig:
    method_raw = str(data.get("method", base.method if base else "texttiling"))
    method = (
        "deepseek"
        if method_raw.strip().lower().startswith("deepseek")
        else "texttiling"
    )
    platforms_raw = data.get("platforms", base.platforms if base else ())
    if isinstance(platforms_raw, str):
        platforms = tuple(p.strip() for p in platforms_raw.split(",") if p.strip())
    else:
        platforms = tuple(
            str(p).strip() for p in (platforms_raw or ()) if str(p).strip()
        )

    def pick(key: str, default):
        return data[key] if key in data and data[key] is not None else default

    cfg = PipelineConfig(
        source_path=str(pick("source_path", base.source_path if base else "")),
        transcript_path=str(
            pick("transcript_path", base.transcript_path if base else "")
        ),
        model_size=pick("model_size", base.model_size if base else "auto"),
        language=pick("language", base.language if base else "auto"),
        device=pick("device", base.device if base else "auto"),
        method=method,
        min_clip_duration=int(
            pick("min_clip_duration", base.min_clip_duration if base else 15)
        ),
        max_clip_duration=int(
            pick("max_clip_duration", base.max_clip_duration if base else 60)
        ),
        top_n=int(pick("top_n", base.top_n if base else 3)),
        cutoff_policy=str(
            pick("cutoff_policy", base.cutoff_policy if base else "high")
        ),
        aspect_ratio=str(pick("aspect_ratio", base.aspect_ratio if base else "9:16")),
        render_vertical=bool(
            pick("render_vertical", base.render_vertical if base else True)
        ),
        keep_trimmed=bool(pick("keep_trimmed", base.keep_trimmed if base else True)),
        captions=bool(pick("captions", base.captions if base else False)),
        caption_preset=str(
            pick("caption_preset", base.caption_preset if base else "bold")
        ),
        translate_to=str(
            pick("translate_to", base.translate_to if base else "off") or "off"
        ),
        package=bool(pick("package", base.package if base else False)),
        hook=bool(pick("hook", base.hook if base else False)),
        thumbnail=bool(pick("thumbnail", base.thumbnail if base else False)),
        effects=bool(pick("effects", base.effects if base else False)),
        publish=bool(pick("publish", base.publish if base else False)),
        platforms=platforms,
        publish_caption=str(
            pick("publish_caption", base.publish_caption if base else "")
        ),
        youtube_title=str(pick("youtube_title", base.youtube_title if base else "")),
        youtube_format=str(
            pick("youtube_format", base.youtube_format if base else "short")
        ),
        tiktok_privacy=str(
            pick(
                "tiktok_privacy", base.tiktok_privacy if base else "PUBLIC_TO_EVERYONE"
            )
        ),
        ai_generated=bool(pick("ai_generated", base.ai_generated if base else False)),
        when=str(pick("when", base.when if base else "now") or "now"),
    )
    return cfg.validate()


def _serialize_job(job, runtime_state: "dict | None" = None) -> dict:
    manifest = job.manifest()
    rows = job.clip_rows()
    selected_set = set(job.selected)
    clips = []
    for row in rows:
        idx = row[0]
        rec = manifest["clips"][idx] if idx < len(manifest["clips"]) else {}
        clips.append(
            {
                "index": idx,
                "selected": idx in selected_set,
                "start_time": row[1],
                "end_time": row[2],
                "duration": row[3],
                "score": row[4],
                "hook": row[5],
                "title": row[6],
                "reason": rec.get("why", ""),
                "text": row[7],
            }
        )

    trimmed = []
    for idx, path in zip(job.selected, job.trimmed):
        url = _file_url(job.id, job.root, path)
        if url:
            trimmed.append(
                {
                    "index": idx,
                    "name": Path(path).name,
                    "url": url,
                    "size": _file_size(path),
                }
            )

    reframed = []
    for idx, path in sorted(job.reframed_by_index.items()):
        url = _file_url(job.id, job.root, path)
        if url:
            reframed.append(
                {
                    "index": idx,
                    "name": Path(path).name,
                    "url": url,
                    "size": _file_size(path),
                }
            )

    captions = []
    for item in job.captions:
        captions.append(
            {
                "index": item.get("index"),
                "name": Path(item.get("video") or item.get("srt") or "captions").name,
                "video_url": _file_url(job.id, job.root, item.get("video")),
                "srt_url": _file_url(job.id, job.root, item.get("srt")),
                "size": _file_size(item.get("video") or item.get("srt")),
            }
        )

    packages = []
    for item in job.packages:
        packages.append(
            {
                "index": item.get("index"),
                "hook": item.get("hook", ""),
                "title": item.get("title", ""),
                "youtube_titles": item.get("youtube_titles", []),
                "tiktok_caption": item.get("tiktok_caption", ""),
                "instagram_caption": item.get("instagram_caption", ""),
                "hashtags": item.get("hashtags", []),
                "summary": item.get("summary", ""),
                "hooked_url": _file_url(job.id, job.root, item.get("hooked")),
                "thumbnail_url": _file_url(job.id, job.root, item.get("thumbnail")),
                "effects_url": _file_url(job.id, job.root, item.get("effects")),
                "package_url": _file_url(job.id, job.root, item.get("package")),
                "edits": item.get("edits", []),
            }
        )

    source_url = _file_url(job.id, job.root, job.config.source_path)
    state = runtime_state or {}
    return {
        "job_id": job.id,
        "created": job.created,
        "updated": manifest["updated"],
        "root": str(job.root),
        "config": manifest["config"],
        "completed": manifest["completed"],
        "stage_state": manifest["stages"],
        "next_options": job.next_options(),
        "next_stage": job.next_enabled_stage(),
        "clips": clips,
        "selected": list(job.selected),
        "artifacts": {
            "source_url": source_url,
            "source_name": (
                Path(job.config.source_path).name if job.config.source_path else ""
            ),
            "transcript_url": _file_url(
                job.id, job.root, manifest["artifacts"].get("transcript")
            ),
            "clips_url": _file_url(
                job.id, job.root, manifest["artifacts"].get("clips")
            ),
            "trimmed": trimmed,
            "reframed": reframed,
            "captions": captions,
            "packages": packages,
            "published": manifest["artifacts"].get("published", []),
        },
        "running": bool(state.get("running", False)),
        "progress": {
            "stage": state.get("stage", ""),
            "fraction": float(state.get("fraction", 0.0)),
            "message": state.get("message", ""),
        },
        "last_result": state.get("last_result"),
    }


def _env_summary(output_dir: Path) -> dict:
    checks = {}
    for module, dist_names, label in (
        ("torch", ("torch",), "torch"),
        ("whisperx", ("whisperx",), "whisperx"),
        ("mediapipe", ("mediapipe",), "mediapipe"),
        ("magic", ("python-magic", "python-magic-bin"), "python-magic"),
        ("gradio", ("gradio",), "gradio"),
    ):
        spec = importlib.util.find_spec(module)
        if spec is None:
            checks[label] = {"installed": False, "error": "Not installed"}
            continue
        ver = "ok"
        for dist in dist_names:
            try:
                ver = importlib.metadata.version(dist)
                break
            except importlib.metadata.PackageNotFoundError:
                continue
        checks[label] = {"installed": True, "version": ver}
    return {
        "python": sys.version.split()[0],
        "output_dir": str(output_dir),
        "ffmpeg": shutil.which("ffmpeg"),
        "packages": checks,
    }


def _check_basic_auth(request: Request, auth: "tuple[str, str]") -> bool:
    header = request.headers.get("authorization") or ""
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
        username, sep, password = decoded.partition(":")
        if not sep:
            return False
        user_ok = hmac.compare_digest(username.encode("utf-8"), auth[0].encode("utf-8"))
        pass_ok = hmac.compare_digest(password.encode("utf-8"), auth[1].encode("utf-8"))
        return user_ok and pass_ok
    except Exception:  # noqa: BLE001
        return False


def create_app(
    output_dir: "str | Path | None" = None,
    static_dir: "str | Path | None" = None,
    env_file: "str | Path | None" = None,
    auth: "tuple[str, str] | None" = None,
    max_upload_bytes: int = MAX_MEDIA_BYTES,
) -> FastAPI:
    """Build the unified FastAPI application serving API routes and the web UI."""
    out_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    web_dir = Path(static_dir or DEFAULT_WEB_DIR)
    env_path = Path(
        env_file or os.environ.get("CLIPSAI_ENV_FILE") or (BASE_DIR / ".env")
    )
    _refresh_env(env_path)

    store = JobStore(out_dir)
    state_lock = threading.Lock()
    run_states: "dict[str, dict]" = {}
    subscribers: "dict[str, list[queue.Queue]]" = {}

    app = FastAPI(title="ClipsAI Studio", docs_url="/api/docs", openapi_url=None)

    @app.middleware("http")
    async def _headers_and_auth(request: Request, call_next):
        if auth and request.url.path != "/api/health":
            if not _check_basic_auth(request, auth):
                return Response(
                    content="Authentication required",
                    status_code=401,
                    headers={
                        "WWW-Authenticate": 'Basic realm="ClipsAI Studio"',
                        **ISOLATION_HEADERS,
                    },
                )
        response = await call_next(request)
        for name, value in ISOLATION_HEADERS.items():
            response.headers[name] = value
        return response

    def _get_state(job_id: str) -> dict:
        with state_lock:
            return dict(run_states.get(job_id, {}))

    def _set_state(job_id: str, **updates) -> dict:
        with state_lock:
            current = dict(run_states.get(job_id, {}))
            current.update(updates)
            run_states[job_id] = current
            return dict(current)

    def _broadcast(job_id: str, event_type: str, payload: dict) -> None:
        with state_lock:
            targets = list(subscribers.get(job_id, ()))
        message = {"type": event_type, **payload}
        for sub in targets:
            try:
                sub.put_nowait(message)
            except queue.Full:
                pass

    def _require_job(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Job '{}' not found.".format(job_id)
            )
        return job

    def _start_worker(job, runner) -> dict:
        with state_lock:
            current = run_states.get(job.id, {})
            if current.get("running"):
                raise HTTPException(
                    status_code=409,
                    detail="A pipeline stage is already running for this job.",
                )
            run_states[job.id] = {
                "running": True,
                "stage": "",
                "fraction": 0.0,
                "message": "Starting...",
                "last_result": current.get("last_result"),
            }

        def _progress(fraction: float, desc: str = "") -> None:
            clamped = max(0.0, min(1.0, float(fraction or 0.0)))
            state = _set_state(job.id, fraction=clamped, message=str(desc or ""))
            _broadcast(job.id, "progress", {"progress": state, "job_id": job.id})

        def _worker() -> None:
            try:
                last_res: "StageResult | None" = runner(_progress)
                result_dict = last_res.to_dict() if last_res is not None else None
                state = _set_state(
                    job.id,
                    running=False,
                    fraction=1.0 if (last_res and last_res.ok) else 0.0,
                    message=last_res.message if last_res else "",
                    last_result=result_dict,
                )
            except Exception as exc:  # noqa: BLE001
                logging.exception("Unexpected error in pipeline worker")
                state = _set_state(
                    job.id,
                    running=False,
                    fraction=0.0,
                    message="",
                    last_result={"stage": "", "ok": False, "error": str(exc)},
                )
            _broadcast(job.id, "done", {"job": _serialize_job(job, state)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return _serialize_job(job, _get_state(job.id))

    # ------------------------------------------------------------------ #
    # Health / Services / Options
    # ------------------------------------------------------------------ #

    @app.get("/api/health")
    def api_health() -> dict:
        return {"ok": True}

    @app.get("/api/services")
    def api_services() -> JSONResponse:
        _refresh_env(env_path)
        payload = service_status()
        payload["env"] = _env_summary(out_dir)
        payload["env_file"] = str(env_path) if env_path.is_file() else None
        payload["web_built"] = (web_dir / "index.html").is_file()
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/pipeline/options")
    def api_pipeline_options() -> dict:
        return {
            "model_sizes": MODEL_SIZES,
            "devices": DEVICES,
            "languages": LANGUAGES,
            "selection_methods": [
                {"id": "texttiling", "label": "TextTiling (fast, local)"},
                {"id": "deepseek", "label": "DeepSeek AI"},
            ],
            "cutoff_policies": CUTOFF_POLICIES,
            "aspect_ratios": list(ASPECT_RATIOS),
            "caption_styles": CAPTION_STYLES,
            "ai_languages": ["off"] + AI_LANGUAGES,
            "platforms": list(PLATFORMS),
            "tiktok_privacy": list(TIKTOK_PRIVACY_LEVELS),
            "youtube_formats": ["short", "long"],
            "stages": list(STAGES),
            "stage_labels": STAGE_LABELS,
            "requires": {k: list(v) for k, v in REQUIRES.items()},
        }

    # ------------------------------------------------------------------ #
    # DeepSeek AI metadata (browser studio compatible)
    # ------------------------------------------------------------------ #

    @app.get("/api/ai/metadata")
    def api_ai_metadata_status() -> JSONResponse:
        _refresh_env(env_path)
        ai = AISettings.from_env()
        return JSONResponse(
            {"configured": ai.is_configured(), "model": ai.model},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/ai/metadata")
    async def api_ai_metadata_generate(request: Request) -> JSONResponse:
        _check_same_origin(request)
        _refresh_env(env_path)
        ai = AISettings.from_env()
        if not ai.is_configured():
            return JSONResponse(
                {
                    "error": (
                        "DeepSeek is not configured. Add DEEPSEEK_API_KEY to "
                        "the repository .env file."
                    )
                },
                status_code=503,
            )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "Expected a JSON body."}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Expected a JSON body."}, status_code=400)

        name = str(body.get("name") or "").strip()
        if not name:
            return JSONResponse(
                {"error": "A clip name is required to write metadata."}, status_code=400
            )

        raw_platforms = body.get("platforms")
        platforms = (
            [str(p) for p in raw_platforms if p]
            if isinstance(raw_platforms, list)
            else []
        )

        start = float(body.get("start") or 0.0)
        end = float(body.get("end") or 0.0)
        facts = {
            "file": name,
            "length_seconds": round(max(0.0, end - start), 2),
            "aspect_ratio": str(body.get("aspect") or "source"),
            "colour_look": str(body.get("look") or "none"),
            "platforms": platforms,
            "editor_note": str(body.get("brief") or "").strip() or None,
            "existing_caption": str(body.get("existingCaption") or "").strip() or None,
        }

        def _generate() -> dict:
            client = LLMClient()
            payload = client.complete_json(
                json.dumps(facts),
                system=_METADATA_SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=600,
            )
            result = _normalize_metadata(payload)
            result["model"] = ai.model
            return result

        try:
            result = await run_in_threadpool(_generate)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except MissingAPIKeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except (LLMError, LLMResponseError) as exc:
            msg = str(exc)
            status = 401 if ("401" in msg or "403" in msg) else 502
            return JSONResponse({"error": msg}, status_code=status)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=502)

    # ------------------------------------------------------------------ #
    # IndiePost endpoints (browser studio compatible)
    # ------------------------------------------------------------------ #

    def _indiepost_client() -> IndiePostClient:
        _refresh_env(env_path)
        settings = IndiePostSettings.from_env()
        return IndiePostClient(api_key=settings.api_key, base_url=settings.base_url)

    @app.get("/api/indiepost/accounts")
    async def api_indiepost_accounts() -> JSONResponse:
        client = _indiepost_client()
        if not client.is_configured():
            return JSONResponse(
                {
                    "configured": False,
                    "workspace": None,
                    "accounts": [],
                    "message": (
                        "INDIEPOST_API_KEY is not set in the repository .env file."
                    ),
                }
            )
        try:
            payload = await run_in_threadpool(client.list_accounts)
            workspaces = (
                payload.get("workspaces") if isinstance(payload, dict) else None
            ) or []
            ws = next(
                (w for w in workspaces if isinstance(w, dict) and w.get("isDefault")),
                workspaces[0] if workspaces else None,
            )
            if not isinstance(ws, dict):
                return JSONResponse(
                    {"configured": True, "workspace": None, "accounts": []},
                    headers={"Cache-Control": "no-store"},
                )
            workspace = (
                {"id": str(ws["id"]), "name": str(ws.get("name") or "Default")}
                if ws.get("id")
                else None
            )
            accounts = [
                {
                    "platform": str(acc["platform"]),
                    "connected": acc.get("connected") is True,
                    "username": str(acc["username"]) if acc.get("username") else None,
                }
                for acc in (ws.get("accounts") or [])
                if isinstance(acc, dict) and isinstance(acc.get("platform"), str)
            ]
            return JSONResponse(
                {"configured": True, "workspace": workspace, "accounts": accounts},
                headers={"Cache-Control": "no-store"},
            )
        except IndiePostAuthError as exc:
            return JSONResponse(
                {
                    "configured": True,
                    "workspace": None,
                    "accounts": [],
                    "message": str(exc),
                },
                status_code=401,
            )
        except IndiePostError as exc:
            return JSONResponse(
                {
                    "configured": True,
                    "workspace": None,
                    "accounts": [],
                    "message": str(exc),
                },
                status_code=502,
            )

    @app.get("/api/indiepost/media")
    async def api_indiepost_media() -> JSONResponse:
        client = _indiepost_client()
        if not client.is_configured():
            return JSONResponse(
                {
                    "configured": False,
                    "items": [],
                    "message": (
                        "INDIEPOST_API_KEY is not set in the repository .env file."
                    ),
                }
            )
        try:
            payload = await run_in_threadpool(client.list_media)
            raw_items = (
                payload.get("items") if isinstance(payload, dict) else None
            ) or []
            items = []
            for entry in raw_items:
                if not isinstance(entry, dict):
                    continue
                media_id = str(entry.get("mediaId") or entry.get("id") or "")
                if not media_id:
                    continue
                items.append(
                    {
                        "mediaId": media_id,
                        "filename": str(entry.get("filename") or ""),
                        "mime": str(entry.get("mime") or ""),
                        "size": int(entry.get("size") or 0),
                        "inUse": entry.get("inUse") is True,
                    }
                )
            return JSONResponse(
                {"configured": True, "items": items},
                headers={"Cache-Control": "no-store"},
            )
        except IndiePostAuthError as exc:
            return JSONResponse(
                {"configured": True, "items": [], "message": str(exc)}, status_code=401
            )
        except IndiePostError as exc:
            return JSONResponse(
                {"configured": True, "items": [], "message": str(exc)}, status_code=502
            )

    @app.delete("/api/indiepost/media/{media_id}")
    async def api_indiepost_delete_media(
        media_id: str, request: Request
    ) -> JSONResponse:
        _check_same_origin(request)
        client = _indiepost_client()
        if not client.is_configured():
            return JSONResponse(
                {
                    "error": (
                        "IndiePost is not configured. Set INDIEPOST_API_KEY in "
                        "the repository .env file."
                    )
                },
                status_code=503,
            )
        clean_id = media_id.strip()
        if not clean_id:
            return JSONResponse({"error": "A media id is required."}, status_code=400)
        try:
            await run_in_threadpool(client.delete_media, clean_id)
            return JSONResponse({"ok": True})
        except IndiePostAuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        except IndiePostError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)

    @app.get("/api/indiepost/posts")
    async def api_indiepost_posts(request: Request) -> JSONResponse:
        client = _indiepost_client()
        if not client.is_configured():
            return JSONResponse(
                {
                    "configured": False,
                    "posts": [],
                    "message": (
                        "INDIEPOST_API_KEY is not set in the repository .env file."
                    ),
                }
            )
        now = datetime.now(timezone.utc)
        from_ts = request.query_params.get("from") or (
            now - timedelta(days=14)
        ).isoformat().replace("+00:00", "Z")
        to_ts = request.query_params.get("to") or (
            now + timedelta(days=14)
        ).isoformat().replace("+00:00", "Z")
        for val in (from_ts, to_ts):
            try:
                datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                return JSONResponse(
                    {"error": "from and to must be ISO 8601 timestamps."},
                    status_code=400,
                )
        try:
            payload = await run_in_threadpool(client.list_posts, from_ts, to_ts)
            raw_posts = (
                payload.get("posts") if isinstance(payload, dict) else None
            ) or []
            posts = []
            for entry in raw_posts:
                if not isinstance(entry, dict):
                    continue
                group_id = str(entry.get("postGroupId") or entry.get("id") or "")
                if not group_id:
                    continue
                sub_posts = [
                    {
                        "platform": str(p.get("platform") or ""),
                        "status": str(p.get("status") or ""),
                        "format": str(p["format"]) if p.get("format") else None,
                        "externalPostId": (
                            str(p["externalPostId"])
                            if p.get("externalPostId")
                            else None
                        ),
                        "postedAt": str(p["postedAt"]) if p.get("postedAt") else None,
                    }
                    for p in (entry.get("posts") or [])
                    if isinstance(p, dict)
                ]
                posts.append(
                    {
                        "postGroupId": group_id,
                        "status": str(entry.get("status") or ""),
                        "scheduledAt": (
                            str(entry["scheduledAt"])
                            if entry.get("scheduledAt")
                            else None
                        ),
                        "platforms": [str(p) for p in (entry.get("platforms") or [])],
                        "posts": sub_posts,
                    }
                )
            return JSONResponse(
                {"configured": True, "from": from_ts, "to": to_ts, "posts": posts},
                headers={"Cache-Control": "no-store"},
            )
        except IndiePostAuthError as exc:
            return JSONResponse(
                {
                    "configured": True,
                    "from": from_ts,
                    "to": to_ts,
                    "posts": [],
                    "message": str(exc),
                },
                status_code=401,
            )
        except IndiePostError as exc:
            return JSONResponse(
                {
                    "configured": True,
                    "from": from_ts,
                    "to": to_ts,
                    "posts": [],
                    "message": str(exc),
                },
                status_code=502,
            )

    @app.delete("/api/indiepost/posts/{post_id}")
    async def api_indiepost_delete_post(post_id: str, request: Request) -> JSONResponse:
        _check_same_origin(request)
        client = _indiepost_client()
        if not client.is_configured():
            return JSONResponse(
                {
                    "error": (
                        "IndiePost is not configured. Set INDIEPOST_API_KEY in "
                        "the repository .env file."
                    )
                },
                status_code=503,
            )
        clean_id = post_id.strip()
        if not clean_id:
            return JSONResponse(
                {"error": "A post group id is required."}, status_code=400
            )
        try:
            await run_in_threadpool(client.delete_post, clean_id)
            return JSONResponse({"ok": True})
        except IndiePostAuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        except IndiePostError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)

    @app.post("/api/indiepost/publish")
    async def api_indiepost_publish(request: Request) -> JSONResponse:
        _check_same_origin(request)
        client = _indiepost_client()
        if not client.is_configured():
            return JSONResponse(
                {
                    "error": (
                        "IndiePost is not configured. Set INDIEPOST_API_KEY in "
                        "the repository .env file."
                    )
                },
                status_code=503,
            )

        try:
            declared = int(request.headers.get("x-clip-size") or "")
        except ValueError:
            declared = 0
        if declared <= 0:
            return JSONResponse(
                {"error": "Expected the clip size in the x-clip-size header."},
                status_code=411,
            )
        if declared > MAX_MEDIA_BYTES:
            return JSONResponse(
                {"error": "IndiePost accepts files up to 2 GB."}, status_code=413
            )

        raw_cl = request.headers.get("content-length")
        if raw_cl:
            try:
                content_length = int(raw_cl)
            except ValueError:
                content_length = -1
            if content_length > 0 and content_length != declared:
                return JSONResponse(
                    {"error": "The upload size did not match the clip size."},
                    status_code=400,
                )

        metadata = _decode_publish_header(request.headers.get("x-clipsai-publish"))
        if not metadata:
            return JSONResponse(
                {"error": "The publish details are missing or unreadable."},
                status_code=400,
            )

        platforms_raw = _normalize_platforms(metadata.get("platforms"))
        options = PlatformOptions(
            youtube_title=str(metadata.get("youtubeTitle") or "").strip(),
            youtube_format=(
                "long" if metadata.get("youtubeFormat") == "long" else "short"
            ),
            tiktok_privacy=(
                str(metadata.get("tiktokPrivacy"))
                if metadata.get("tiktokPrivacy") in TIKTOK_PRIVACY_LEVELS
                else "PUBLIC_TO_EVERYONE"
            ),
            ai_generated=metadata.get("aiGenerated") is True,
        )
        try:
            platforms = validate_platforms(platforms_raw, options)
        except PublishError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        caption = str(metadata.get("caption") or "")[:2200]
        when = str(metadata.get("when") or "now").strip() or "now"
        idem_key = str(metadata.get("idempotencyKey") or "").strip()[
            :128
        ] or "clipsai-web-{}".format(secrets.token_hex(8))

        clip_name = _safe_filename(
            unquote(request.headers.get("x-clip-name") or "clip.mp4"),
            fallback="clip.mp4",
        )
        mime_type = request.headers.get("content-type") or "video/mp4"

        tmp_path: "str | None" = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="clipsai_pub_",
                suffix=Path(clip_name).suffix or ".mp4",
                delete=False,
            ) as tmp:
                tmp_path = tmp.name
                received = 0
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > MAX_MEDIA_BYTES:
                        return JSONResponse(
                            {"error": "IndiePost accepts files up to 2 GB."},
                            status_code=413,
                        )
                    tmp.write(chunk)

            if received <= 0:
                return JSONResponse(
                    {"error": "No video file was uploaded."}, status_code=400
                )

            def _do_publish() -> dict:
                init = client.init_media(clip_name, mime_type, received)
                media_id = init.get("media_id")
                client._upload(init["upload_url"], tmp_path, mime_type)
                if media_id:
                    client.confirm_media(media_id)
                payload = build_post_payload(
                    [media_id] if media_id else [],
                    platforms,
                    caption=caption,
                    when=when,
                    options=options,
                    idempotency_key=idem_key,
                )
                post = client.create_post(payload, idem_key)
                return {
                    "mediaId": str(media_id) if media_id else None,
                    "platforms": platforms,
                    "post": post,
                    "links": extract_external_ids(post),
                }

            result = await run_in_threadpool(_do_publish)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except IndiePostAuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        except IndiePostError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=502)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    # Auto Pipeline endpoints (/api/pipeline/*)
    # ------------------------------------------------------------------ #

    @app.get("/api/pipeline/jobs")
    def api_pipeline_list_jobs() -> JSONResponse:
        jobs = sorted(store.all(), key=lambda j: j.created, reverse=True)
        return JSONResponse(
            {"jobs": [_serialize_job(j, _get_state(j.id)) for j in jobs]},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/pipeline/jobs")
    async def api_pipeline_create_job(request: Request) -> JSONResponse:
        _check_same_origin(request)
        content_type = (request.headers.get("content-type") or "").lower()

        config_data: dict = {}
        video_upload = None
        transcript_upload = None

        if "multipart/form-data" in content_type:
            form = await request.form()
            raw_cfg = form.get("config")
            if isinstance(raw_cfg, str) and raw_cfg.strip():
                try:
                    parsed = json.loads(raw_cfg)
                    if isinstance(parsed, dict):
                        config_data = parsed
                except ValueError:
                    return JSONResponse(
                        {"error": "Invalid config JSON."}, status_code=400
                    )
            video_field = form.get("video")
            if (
                video_field is not None
                and hasattr(video_field, "filename")
                and video_field.filename
            ):
                video_upload = video_field
            transcript_field = form.get("transcript")
            if (
                transcript_field is not None
                and hasattr(transcript_field, "filename")
                and transcript_field.filename
            ):
                transcript_upload = transcript_field
        elif "application/json" in content_type:
            try:
                parsed = await request.json()
                config_data = parsed if isinstance(parsed, dict) else {}
            except Exception:  # noqa: BLE001
                return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

        try:
            initial_cfg = _config_from_payload(config_data)
        except PipelineConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        job = store.create(initial_cfg)
        uploads_dir = job.root / "uploads"
        if video_upload is not None or transcript_upload is not None:
            uploads_dir.mkdir(parents=True, exist_ok=True)

        try:
            if video_upload is not None:
                dest = uploads_dir / _safe_filename(video_upload.filename, "source.mp4")
                total = 0
                with dest.open("wb") as handle:
                    while True:
                        chunk = await video_upload.read(_UPLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if max_upload_bytes and total > max_upload_bytes:
                            raise HTTPException(
                                status_code=413,
                                detail="Uploaded video exceeds maximum allowed size.",
                            )
                        handle.write(chunk)
                config_data["source_path"] = str(dest)

            if transcript_upload is not None:
                dest = uploads_dir / _safe_filename(
                    transcript_upload.filename, "transcript.json"
                )
                with dest.open("wb") as handle:
                    while True:
                        chunk = await transcript_upload.read(_UPLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                config_data["transcript_path"] = str(dest)

            final_cfg = _config_from_payload(config_data, base=initial_cfg)
            job.set_config(final_cfg)
        except HTTPException:
            raise
        except PipelineConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        return JSONResponse(
            _serialize_job(job, _get_state(job.id)),
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/pipeline/jobs/{job_id}")
    def api_pipeline_get_job(job_id: str) -> JSONResponse:
        job = _require_job(job_id)
        return JSONResponse(
            _serialize_job(job, _get_state(job.id)),
            headers={"Cache-Control": "no-store"},
        )

    @app.put("/api/pipeline/jobs/{job_id}/config")
    async def api_pipeline_update_config(job_id: str, request: Request) -> JSONResponse:
        _check_same_origin(request)
        job = _require_job(job_id)
        if _get_state(job.id).get("running"):
            return JSONResponse(
                {"error": "Cannot modify settings while a stage is running."},
                status_code=409,
            )
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "Invalid JSON body."}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Expected a JSON object."}, status_code=400)
        try:
            cfg = _config_from_payload(body, base=job.config)
            job.set_config(cfg)
        except PipelineConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            _serialize_job(job, _get_state(job.id)),
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/pipeline/jobs/{job_id}/reset")
    def api_pipeline_reset_job(job_id: str, request: Request) -> JSONResponse:
        _check_same_origin(request)
        job = _require_job(job_id)
        if _get_state(job.id).get("running"):
            return JSONResponse(
                {"error": "Cannot reset while a stage is running."},
                status_code=409,
            )
        job.reset()
        state = _set_state(
            job.id, running=False, stage="", fraction=0.0, message="", last_result=None
        )
        return JSONResponse(
            _serialize_job(job, state),
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/pipeline/jobs/{job_id}/run")
    async def api_pipeline_run_stage(job_id: str, request: Request) -> JSONResponse:
        _check_same_origin(request)
        _refresh_env(env_path)
        job = _require_job(job_id)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            body = {}

        if isinstance(body.get("config"), dict):
            try:
                job.set_config(_config_from_payload(body["config"], base=job.config))
            except PipelineConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

        stage = str(body.get("stage") or "").strip().lower() or job.next_enabled_stage()
        if not stage:
            return JSONResponse(
                _serialize_job(job, _get_state(job.id)),
                headers={"Cache-Control": "no-store"},
            )
        if stage not in STAGES:
            return JSONResponse(
                {"error": "Unknown stage '{}'.".format(stage)}, status_code=400
            )

        sync_mode = request.query_params.get("sync") in ("1", "true", "yes")
        if sync_mode:
            result = await run_in_threadpool(job.run, stage)
            state = _set_state(
                job.id,
                running=False,
                stage=stage,
                fraction=1.0 if result.ok else 0.0,
                message=result.message if result.ok else result.error,
                last_result=result.to_dict(),
            )
            return JSONResponse(
                _serialize_job(job, state), headers={"Cache-Control": "no-store"}
            )

        def _run(progress_cb):
            _set_state(job.id, stage=stage, message=STAGE_LABELS.get(stage, stage))
            return job.run(stage, progress=progress_cb)

        snapshot = _start_worker(job, _run)
        return JSONResponse(
            snapshot, status_code=202, headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/pipeline/jobs/{job_id}/run-all")
    async def api_pipeline_run_all(job_id: str, request: Request) -> JSONResponse:
        _check_same_origin(request)
        _refresh_env(env_path)
        job = _require_job(job_id)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            body = {}

        if isinstance(body.get("config"), dict):
            try:
                job.set_config(_config_from_payload(body["config"], base=job.config))
            except PipelineConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

        sync_mode = request.query_params.get("sync") in ("1", "true", "yes")
        if sync_mode:
            results = await run_in_threadpool(job.run_all)
            last = results[-1] if results else None
            state = _set_state(
                job.id,
                running=False,
                stage=last.stage if last else "",
                fraction=1.0 if (last and last.ok) else 0.0,
                message=(
                    last.message if (last and last.ok) else (last.error if last else "")
                ),
                last_result=last.to_dict() if last else None,
            )
            return JSONResponse(
                _serialize_job(job, state), headers={"Cache-Control": "no-store"}
            )

        def _run_all(progress_cb):
            results = job.run_all(progress=progress_cb)
            if not results:
                return None
            last = results[-1]
            if len(results) > 1 and last.ok:
                last.message = "\n".join(
                    "- {}: {}".format(r.stage.replace("_", " ").title(), r.message)
                    for r in results
                )
            return last

        snapshot = _start_worker(job, _run_all)
        return JSONResponse(
            snapshot, status_code=202, headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/pipeline/jobs/{job_id}/events")
    async def api_pipeline_events(job_id: str) -> StreamingResponse:
        job = _require_job(job_id)
        sub_q: queue.Queue = queue.Queue(maxsize=64)
        with state_lock:
            subscribers.setdefault(job.id, []).append(sub_q)

        async def _stream():
            try:
                initial = _serialize_job(job, _get_state(job.id))
                yield "data: {}\n\n".format(
                    json.dumps({"type": "snapshot", "job": initial})
                )
                while True:
                    try:
                        event = await run_in_threadpool(sub_q.get, True, 2.0)
                        yield "data: {}\n\n".format(json.dumps(event))
                        if event.get("type") == "done":
                            break
                    except queue.Empty:
                        if not _get_state(job.id).get("running"):
                            final_job = _serialize_job(job, _get_state(job.id))
                            yield "data: {}\n\n".format(
                                json.dumps({"type": "done", "job": final_job})
                            )
                            break
                        yield ": keepalive\n\n"
            finally:
                with state_lock:
                    lst = subscribers.get(job.id, [])
                    if sub_q in lst:
                        lst.remove(sub_q)

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/pipeline/jobs/{job_id}/files/{file_path:path}")
    def api_pipeline_file(job_id: str, file_path: str) -> Response:
        job = _require_job(job_id)
        root_resolved = job.root.resolve()
        try:
            target = (root_resolved / file_path).resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail="Invalid file path.") from exc
        if not target.is_relative_to(root_resolved):
            raise HTTPException(status_code=403, detail="Access denied.")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        media_type, _ = mimetypes.guess_type(str(target))
        return FileResponse(target, media_type=media_type or "application/octet-stream")

    # ------------------------------------------------------------------ #
    # Unified SvelteKit SPA frontend
    # ------------------------------------------------------------------ #

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found.")

        if web_dir.is_dir():
            web_resolved = web_dir.resolve()
            rel = full_path.lstrip("/")
            if rel:
                try:
                    candidate = (web_resolved / rel).resolve()
                    if candidate.is_relative_to(web_resolved) and candidate.is_file():
                        media_type, _ = mimetypes.guess_type(str(candidate))
                        return FileResponse(
                            candidate,
                            media_type=media_type or "application/octet-stream",
                        )
                except OSError:
                    pass

            index_file = web_resolved / "index.html"
            if index_file.is_file():
                return FileResponse(index_file, media_type="text/html")

        return HTMLResponse(
            "<h1>ClipsAI Studio frontend not built yet</h1>"
            "<p>Run <code>npm --prefix web run build</code>, or launch the legacy "
            "Gradio interface with <code>python app.py --gradio</code>.</p>",
            status_code=503,
        )

    return app
