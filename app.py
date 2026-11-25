"""
ClipsAI Studio - a guided pipeline UI for the ClipsAI library.

Set the options once, then run a stage. Each completed stage returns its
artifacts and the choices that make sense next (trim, reframe, captions,
packaging, publish). All processing lives in ``clipsai.workflow`` and all
service credentials live in the backend environment / ``.env``.

Run with:
    python app.py                                  # http://127.0.0.1:7860
    python app.py --port 8000 --auth user:pass     # require a login

Or use the bundled one-click launchers (launch.bat / launch.ps1).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import traceback
from pathlib import Path

import gradio as gr

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("CLIPSAI_OUTPUT_DIR", str(BASE_DIR / "outputs")))

MODEL_SIZES = ["auto", "tiny", "base", "small", "medium", "large-v1", "large-v2"]
DEVICES = ["auto", "cpu", "cuda"]
LANGUAGES = ["auto", "en", "fr", "de", "es", "it", "ja", "zh", "nl", "uk", "pt"]
SELECTION_METHODS = ["TextTiling (fast, local)", "DeepSeek AI"]
CUTOFF_POLICIES = ["high", "average", "low"]
ASPECT_RATIOS = ["9:16", "3:4", "4:5", "1:1", "16:9"]
CAPTION_STYLES = ["bold", "clean", "lime", "pill", "oneword"]
HOOK_STYLES = ["box", "dark", "yellow", "outline"]
AI_LANGUAGES = [
    "en", "es", "fr", "de", "pt", "it", "nl", "pl", "uk", "ru", "tr",
    "ar", "hi", "ja", "ko", "zh", "id", "vi",
]
PLATFORM_CHOICES = ["youtube", "tiktok", "instagram", "facebook"]
TIKTOK_PRIVACY = [
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "SELF_ONLY",
]

CLIP_HEADERS = [
    "#", "Start (s)", "End (s)", "Duration (s)", "Score", "Hook", "Title", "Text",
]
PACKAGE_HEADERS = ["#", "Hook", "Title", "Thumbnail", "Effects"]
PUBLISH_HEADERS = ["#", "Platforms", "External ids", "Media id", "Idempotency key"]

ENV_HELP = """
### Where do credentials go?
ClipsAI Studio never asks for keys in the browser. Put them in `.env` next to
`app.py` (copy `.env.example`), then restart the Studio or press **Refresh**:

```bash
DEEPSEEK_API_KEY=...       # https://platform.deepseek.com
HF_TOKEN=...               # https://huggingface.co/pyannote/speaker-diarization-3.1
INDIEPOST_API_KEY=...      # https://www.indiepost.app
```

`DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` and `INDIEPOST_BASE_URL` are optional.
Environment variables already set in your shell win over `.env`.
"""


# --------------------------------------------------------------------------- #
# Compatibility shim (gradio 4.44 + gradio_client 1.3 schema parser)
# --------------------------------------------------------------------------- #
def _patch_gradio_client_schema_parser() -> None:
    try:
        from gradio_client import utils as gc_utils
    except Exception:  # pragma: no cover
        return

    original = gc_utils.json_schema_to_python_type

    def _sanitize(node):
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key == "additionalProperties" and isinstance(value, bool):
                    node[key] = {}
                else:
                    _sanitize(value)
        elif isinstance(node, list):
            for item in node:
                _sanitize(item)
        return node

    def _patched(schema):
        return original(_sanitize(schema))

    gc_utils.json_schema_to_python_type = _patched


_patch_gradio_client_schema_parser()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _out_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


_STORE = None


def _jobs():
    global _STORE
    if _STORE is None:
        from clipsai.workflow import JobStore

        _STORE = JobStore(_out_dir())
    return _STORE


_SECRETS: "set[str]" = set()


def _register_secret(value) -> None:
    if value and len(str(value)) >= 6:
        _SECRETS.add(str(value))


def _redact(text: str) -> str:
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text


def _error(context: str, exc: Exception) -> gr.Error:
    tail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    print("[ClipsAI Studio] {} failed:\n{}".format(context, _redact(traceback.format_exc())))
    return gr.Error(_redact("{} failed: {}".format(context, tail)))


def _make_config(
    source,
    transcript,
    model_size,
    language,
    device,
    method,
    min_dur,
    max_dur,
    top_n,
    cutoff,
    aspect,
    render_vertical,
    keep_trimmed,
    captions,
    caption_preset,
    translate_to,
    packaging,
    hook,
    thumbnail,
    effects,
    publish,
    platforms,
    publish_caption,
    youtube_title,
    youtube_format,
    tiktok_privacy,
    ai_generated,
    when,
):
    from clipsai.workflow import PipelineConfig

    source_path = str(source) if source else ""
    transcript_path = str(transcript) if transcript else ""
    return PipelineConfig(
        source_path=source_path,
        transcript_path=transcript_path,
        model_size=model_size,
        language=language,
        device=device,
        method="deepseek" if str(method or "").lower().startswith("deepseek") else "texttiling",
        min_clip_duration=int(min_dur),
        max_clip_duration=int(max_dur),
        top_n=int(top_n),
        cutoff_policy=cutoff,
        aspect_ratio=aspect,
        render_vertical=bool(render_vertical),
        keep_trimmed=bool(keep_trimmed),
        captions=bool(captions),
        caption_preset=caption_preset,
        translate_to=translate_to or "off",
        package=bool(packaging),
        hook=bool(hook),
        thumbnail=bool(thumbnail),
        effects=bool(effects),
        publish=bool(publish),
        platforms=tuple(platforms or ()),
        publish_caption=publish_caption or "",
        youtube_title=youtube_title or "",
        youtube_format=youtube_format or "short",
        tiktok_privacy=tiktok_privacy or "PUBLIC_TO_EVERYONE",
        ai_generated=bool(ai_generated),
        when=when or "now",
    ).validate()


def _job_for(job_id, config):
    store = _jobs()
    job = store.get(job_id) if job_id else None
    if job is None:
        return store.create(config)
    job.set_config(config)
    return job


def _next_update(job):
    options = [option for option in job.next_options() if option["enabled"]]
    labels = [option["label"] for option in options]
    return gr.update(choices=labels, value=labels[0] if labels else None)


def _status_markdown(job, result=None) -> str:
    lines = ["### Job `{}`".format(job.id)]
    done = [option["label"] for option in job.next_options() if option["done"]]
    lines.append("**Completed:** {}".format(", ".join(done) if done else "nothing yet"))
    if result is not None:
        label = result.stage.replace("_", " ").title()
        if result.ok:
            lines.append("**{}:** {}".format(label, result.message))
        else:
            lines.append("**{} failed:** {}".format(label, result.error))
    upcoming = [option["label"] for option in job.next_options() if option["enabled"]]
    lines.append(
        "**Next:** {}".format(upcoming[0] if upcoming else "everything is done")
    )
    lines.append("Artifacts: `{}`".format(job.root))
    return "\n\n".join(lines)


def _outputs(job, result=None):
    package_rows = [
        [
            item.get("index"),
            item.get("hook", ""),
            item.get("title", ""),
            item.get("thumbnail", ""),
            item.get("effects", ""),
        ]
        for item in job.packages
    ]
    publish_rows = [
        [
            item.get("index"),
            ", ".join(item.get("platforms") or []),
            ", ".join(str(i) for i in (item.get("external_ids") or [])),
            item.get("media_id") or "",
            item.get("idempotency_key") or "",
        ]
        for item in job.published
    ]
    caption_files = [
        item["video"] or item["srt"] for item in job.captions if item.get("video") or item.get("srt")
    ]
    return (
        job.id,
        _status_markdown(job, result),
        job.clip_rows(),
        job.trimmed,
        job.reframed,
        caption_files,
        package_rows,
        publish_rows,
        _next_update(job),
    )


# --------------------------------------------------------------------------- #
# Pipeline handlers
# --------------------------------------------------------------------------- #
def run_step(
    job_id, step_label, source, transcript, model_size, language, device, method,
    min_dur, max_dur, top_n, cutoff, aspect, render_vertical, keep_trimmed, captions,
    caption_preset, translate_to, packaging, hook, thumbnail, effects, publish,
    platforms, publish_caption, youtube_title, youtube_format, tiktok_privacy,
    ai_generated, when, progress=gr.Progress(),
):
    try:
        from clipsai.workflow import STAGE_LABELS

        config = _make_config(
            source, transcript, model_size, language, device, method, min_dur,
            max_dur, top_n, cutoff, aspect, render_vertical, keep_trimmed,
            captions, caption_preset, translate_to, packaging, hook, thumbnail,
            effects, publish, platforms, publish_caption, youtube_title,
            youtube_format, tiktok_privacy, ai_generated, when,
        )
        job = _job_for(job_id, config)

        stage = ""
        for name, label in STAGE_LABELS.items():
            if label == (step_label or "").strip():
                stage = name
                break
        if not stage:
            stage = job.next_enabled_stage()

        if not stage:
            return _outputs(job, None)

        return _outputs(job, job.run(stage, progress=progress))
    except gr.Error:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _error("Pipeline", exc)


def run_all(
    job_id, source, transcript, model_size, language, device, method, min_dur,
    max_dur, top_n, cutoff, aspect, render_vertical, keep_trimmed, captions,
    caption_preset, translate_to, packaging, hook, thumbnail, effects, publish,
    platforms, publish_caption, youtube_title, youtube_format, tiktok_privacy,
    ai_generated, when, progress=gr.Progress(),
):
    try:
        config = _make_config(
            source, transcript, model_size, language, device, method, min_dur,
            max_dur, top_n, cutoff, aspect, render_vertical, keep_trimmed,
            captions, caption_preset, translate_to, packaging, hook, thumbnail,
            effects, publish, platforms, publish_caption, youtube_title,
            youtube_format, tiktok_privacy, ai_generated, when,
        )
        job = _job_for(job_id, config)
        results = job.run_all(progress=progress)
        if not results:
            return _outputs(job, None)
        last = results[-1]
        if len(results) > 1 and last.ok:
            summary = "\n".join(
                "- {}: {}".format(result.stage.replace("_", " ").title(), result.message)
                for result in results
            )
            last.message = summary
        return _outputs(job, last)
    except gr.Error:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _error("Pipeline", exc)


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
def services_markdown() -> str:
    from clipsai.config import AISettings, IndiePostSettings, huggingface_token

    ai = AISettings.from_env()
    indiepost = IndiePostSettings.from_env()
    env_file = BASE_DIR / ".env"
    lines = ["### Services"]
    lines.append(
        "- **DeepSeek:** {} · model `{}` · `{}`".format(
            "ready" if ai.is_configured() else "missing `DEEPSEEK_API_KEY`",
            ai.model,
            ai.base_url,
        )
    )
    lines.append(
        "- **HuggingFace / pyannote:** {}".format(
            "ready" if huggingface_token() else "missing `HF_TOKEN` (needed to reframe)"
        )
    )
    lines.append(
        "- **IndiePost:** {} · `{}`".format(
            "ready" if indiepost.is_configured() else "missing `INDIEPOST_API_KEY`",
            indiepost.base_url,
        )
    )
    lines.append(
        "- **`.env`:** {}".format(
            "loaded from `{}`".format(env_file) if env_file.is_file() else "not found (using the process environment)"
        )
    )
    return "\n".join(lines)


def env_check() -> str:
    lines = ["### Environment"]
    lines.append("- Python: `{}`".format(sys.version.split()[0]))
    lines.append("- Output folder: `{}`".format(OUTPUT_DIR))
    for module, label in (
        ("gradio", "gradio"),
        ("torch", "torch"),
        ("whisperx", "whisperx"),
        ("mediapipe", "mediapipe"),
        ("magic", "python-magic (libmagic)"),
    ):
        try:
            imported = __import__(module)
            version = getattr(imported, "__version__", "ok")
            lines.append("- {}: `{}`".format(label, version))
        except Exception as exc:  # noqa: BLE001
            lines.append("- {}: **MISSING** ({})".format(label, exc))
    ffmpeg_path = shutil.which("ffmpeg")
    lines.append(
        "- ffmpeg: `{}`".format(ffmpeg_path)
        if ffmpeg_path
        else "- ffmpeg: **NOT FOUND** (required)"
    )
    return "\n".join(lines)


def indiepost_accounts() -> str:
    try:
        from clipsai.publish import IndiePostClient

        client = IndiePostClient()
        client.assert_ready()
        payload = client.list_accounts()
    except gr.Error:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _error("IndiePost accounts", exc)

    workspaces = payload.get("workspaces") if isinstance(payload, dict) else None
    if not workspaces:
        return "No IndiePost workspaces returned."

    lines = ["### IndiePost accounts"]
    for workspace in workspaces:
        if not isinstance(workspace, dict):
            continue
        default = " (default)" if workspace.get("isDefault") else ""
        lines.append(
            "\n**{}**{} · id `{}`".format(
                workspace.get("name") or "Workspace",
                default,
                workspace.get("id") or "?",
            )
        )
        for account in workspace.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            state = "connected" if account.get("connected") else "not connected"
            lines.append(
                "- {} · {} {}".format(
                    account.get("platform") or "?",
                    account.get("username") or "",
                    "· " + state,
                ).rstrip()
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="ClipsAI Studio", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# ClipsAI Studio\n"
            "Set the options once, run a stage, then pick the next step. Every "
            "stage writes its files to a job folder and reports what it produced."
        )
        job_state = gr.State("")

        with gr.Tabs():
            with gr.Tab("Pipeline"):
                with gr.Row():
                    with gr.Column(scale=4):
                        with gr.Accordion("1. Source & transcription", open=True):
                            p_source = gr.File(
                                label="Video file", type="filepath", file_count="single"
                            )
                            p_transcript = gr.File(
                                label="Existing transcript JSON (optional)",
                                type="filepath",
                                file_count="single",
                            )
                            p_model = gr.Dropdown(
                                MODEL_SIZES, value="auto", label="Whisper model size"
                            )
                            p_language = gr.Dropdown(
                                LANGUAGES, value="auto", label="Language"
                            )
                            p_device = gr.Dropdown(DEVICES, value="auto", label="Device")

                        with gr.Accordion("2. Clip selection", open=True):
                            p_method = gr.Radio(
                                choices=SELECTION_METHODS,
                                value=SELECTION_METHODS[0],
                                label="How to find clips",
                            )
                            p_min = gr.Number(
                                value=15, label="Min clip duration (s)", precision=0
                            )
                            p_max = gr.Number(
                                value=60, label="Max clip duration (s)", precision=0
                            )
                            p_topn = gr.Slider(
                                1, 20, value=3, step=1, label="Clips to export"
                            )
                            p_cutoff = gr.Dropdown(
                                CUTOFF_POLICIES,
                                value="high",
                                label="TextTiling cutoff policy",
                            )

                        with gr.Accordion("3. Output & captions", open=True):
                            p_aspect = gr.Dropdown(
                                ASPECT_RATIOS, value="9:16", label="Aspect ratio"
                            )
                            p_render_v = gr.Checkbox(
                                value=True, label="Reframe to vertical"
                            )
                            p_keep = gr.Checkbox(
                                value=True, label="Keep trimmed (original aspect) clips"
                            )
                            p_captions = gr.Checkbox(
                                value=False, label="Add captions"
                            )
                            p_caption_preset = gr.Dropdown(
                                CAPTION_STYLES, value="bold", label="Caption style"
                            )
                            p_translate = gr.Dropdown(
                                ["off"] + AI_LANGUAGES,
                                value="off",
                                label="Translate captions (DeepSeek)",
                            )

                        with gr.Accordion("4. Packaging & publishing", open=False):
                            p_packaging = gr.Checkbox(
                                value=False,
                                label="Generate AI packaging (hook, titles, thumbnails)",
                            )
                            p_hook = gr.Checkbox(value=False, label="Burn the hook")
                            p_thumbnail = gr.Checkbox(
                                value=False, label="Create a thumbnail"
                            )
                            p_effects = gr.Checkbox(
                                value=False, label="Apply AI effects"
                            )
                            p_publish = gr.Checkbox(
                                value=False, label="Publish with IndiePost"
                            )
                            p_platforms = gr.CheckboxGroup(
                                PLATFORM_CHOICES, value=["instagram"], label="Platforms"
                            )
                            p_publish_caption = gr.Textbox(
                                label="Caption (blank = from packaging or clip text)",
                                lines=2,
                            )
                            p_yt_title = gr.Textbox(
                                label="YouTube title (blank = from packaging)"
                            )
                            p_yt_format = gr.Dropdown(
                                ["short", "long"], value="short", label="YouTube format"
                            )
                            p_tt_privacy = gr.Dropdown(
                                TIKTOK_PRIVACY,
                                value="PUBLIC_TO_EVERYONE",
                                label="TikTok privacy",
                            )
                            p_ai_generated = gr.Checkbox(
                                value=False, label="Label as AI-generated"
                            )
                            p_when = gr.Textbox(
                                value="now",
                                label="Publish when ('now' or ISO timestamp)",
                            )

                    with gr.Column(scale=6):
                        status_md = gr.Markdown("No job yet. Run a stage to begin.")
                        with gr.Row():
                            run_step_btn = gr.Button("Run next step", variant="primary")
                            run_all_btn = gr.Button("Run all enabled stages")
                        next_step = gr.Radio(
                            label="Next step",
                            choices=["Transcribe"],
                            value="Transcribe",
                        )
                        clips_table = gr.Dataframe(
                            headers=CLIP_HEADERS, label="Clips", wrap=True,
                            interactive=False,
                        )
                        with gr.Row():
                            trimmed_files = gr.File(
                                label="Trimmed clips", file_count="multiple",
                                interactive=False,
                            )
                            vertical_files = gr.File(
                                label="Vertical clips", file_count="multiple",
                                interactive=False,
                            )
                            caption_files = gr.File(
                                label="Captioned clips", file_count="multiple",
                                interactive=False,
                            )
                        with gr.Row():
                            package_table = gr.Dataframe(
                                headers=PACKAGE_HEADERS, label="AI packaging",
                                interactive=False,
                            )
                            publish_table = gr.Dataframe(
                                headers=PUBLISH_HEADERS, label="Published posts",
                                interactive=False,
                            )

                pipeline_inputs = [
                    job_state, p_source, p_transcript, p_model, p_language, p_device,
                    p_method, p_min, p_max, p_topn, p_cutoff, p_aspect, p_render_v,
                    p_keep, p_captions, p_caption_preset, p_translate, p_packaging,
                    p_hook, p_thumbnail, p_effects, p_publish, p_platforms,
                    p_publish_caption, p_yt_title, p_yt_format, p_tt_privacy,
                    p_ai_generated, p_when,
                ]
                pipeline_outputs = [
                    job_state, status_md, clips_table, trimmed_files, vertical_files,
                    caption_files, package_table, publish_table, next_step,
                ]

                run_step_btn.click(
                    run_step,
                    inputs=[job_state, next_step] + pipeline_inputs[1:],
                    outputs=pipeline_outputs,
                )
                run_all_btn.click(
                    run_all,
                    inputs=pipeline_inputs,
                    outputs=pipeline_outputs,
                )

            with gr.Tab("Services"):
                gr.Markdown(
                    "Credentials and readiness live in the backend `.env`. "
                    "Press **Refresh status** to read them."
                )
                services_md = gr.Markdown()
                with gr.Row():
                    refresh_btn = gr.Button("Refresh status")
                    accounts_btn = gr.Button("Check IndiePost accounts")
                    env_btn = gr.Button("Check environment")
                accounts_md = gr.Markdown()
                env_md = gr.Markdown()
                refresh_btn.click(services_markdown, inputs=None, outputs=services_md)
                accounts_btn.click(indiepost_accounts, inputs=None, outputs=accounts_md)
                env_btn.click(env_check, inputs=None, outputs=env_md)
                gr.Markdown(ENV_HELP)

    return demo


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main() -> None:
    from clipsai.config import load_env

    loaded = load_env(BASE_DIR / ".env")
    for name in (
        "DEEPSEEK_API_KEY",
        "HF_TOKEN",
        "PYANNOTE_AUTH_TOKEN",
        "INDIEPOST_API_KEY",
    ):
        _register_secret(os.environ.get(name))
    if loaded:
        print("[ClipsAI Studio] Loaded {} setting(s) from .env".format(len(loaded)))

    parser = argparse.ArgumentParser(description="ClipsAI Studio web UI")
    parser.add_argument("--host", default=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("GRADIO_SERVER_PORT", "7860"))
    )
    parser.add_argument("--share", action="store_true", help="Create a public Gradio share link")
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open a browser window"
    )
    parser.add_argument(
        "--auth",
        default=os.environ.get("CLIPSAI_AUTH", ""),
        help="Require login as 'user:password' (or set CLIPSAI_AUTH).",
    )
    parser.add_argument(
        "--max-file-size",
        default=os.environ.get("CLIPSAI_MAX_FILE_SIZE", "2gb"),
        help="Maximum upload size, e.g. '2gb'",
    )
    args = parser.parse_args()

    auth = None
    if args.auth:
        if ":" not in args.auth:
            parser.error("--auth must be in the form 'user:password'")
        user, _, password = args.auth.partition(":")
        auth = (user, password)
        _register_secret(password)
    if args.share and auth is None:
        print(
            "[ClipsAI Studio] WARNING: --share exposes this app publicly without auth. "
            "Add --auth user:password."
        )

    _out_dir()
    demo = build_ui()
    demo.queue()
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        inbrowser=not args.no_browser,
        show_api=False,
        auth=auth,
        max_file_size=args.max_file_size or None,
    )


if __name__ == "__main__":
    main()
