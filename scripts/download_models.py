"""
Pre-download first-run ML and NLP models used by ClipsAI Studio.

Downloads:
1. NLTK sentence tokenizer data (``punkt`` and ``punkt_tab``)
2. WhisperX ASR model (default: CPU/GPU auto-selected, or ``--whisper-model``),
   its VAD model, and alignment model(s) (default: ``en``)
3. SentenceTransformers ``all-roberta-large-v1`` (used by local TextTiling)
4. Pyannote ``pyannote/speaker-diarization-3.1`` (requires ``HF_TOKEN``)
5. MTCNN + MediaPipe FaceMesh initialization check (bundled weights)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _load_env() -> None:
    from clipsai.config import load_env

    load_env(BASE_DIR / ".env", override=False)


def download_nltk() -> None:
    import nltk

    nltk_dir = os.environ.get("NLTK_DATA")
    kwargs = {"download_dir": nltk_dir} if nltk_dir else {}
    for pkg in ("punkt", "punkt_tab"):
        print(f"[models] NLTK {pkg}...")
        nltk.download(pkg, quiet=True, **kwargs)


def download_whisperx(
    model_size: str, device: str, precision: str, langs: list[str]
) -> None:
    import whisperx

    print(f"[models] WhisperX ASR model '{model_size}' ({device}, {precision})...")
    model = whisperx.load_model(
        whisper_arch=model_size,
        device=device,
        compute_type=precision,
    )
    del model

    for lang in langs:
        lang = lang.strip()
        if not lang:
            continue
        print(f"[models] WhisperX alignment model '{lang}'...")
        align_model, _ = whisperx.load_align_model(language_code=lang, device=device)
        del align_model


def download_embedder(device: str) -> None:
    from sentence_transformers import SentenceTransformer

    print("[models] SentenceTransformer 'all-roberta-large-v1'...")
    model = SentenceTransformer("all-roberta-large-v1", device=device)
    del model


def download_pyannote(device: str, token: str) -> bool:
    if not token:
        print("[models] Skipping Pyannote (HF_TOKEN is not set).")
        return False

    from huggingface_hub import HfApi
    from pyannote.audio import Pipeline
    import torch

    print("[models] Pyannote 'pyannote/speaker-diarization-3.1'...")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=token,
        )
        if pipeline is None:
            api = HfApi()
            print(
                "[models] ERROR: Pyannote returned None. Checking Hugging Face "
                "repository access with configured token..."
            )
            for repo_id in (
                "pyannote/speaker-diarization-3.1",
                "pyannote/segmentation-3.0",
            ):
                try:
                    api.model_info(repo_id, token=token)
                    print(f"[models]   - {repo_id}: metadata accessible")
                except Exception as repo_exc:  # noqa: BLE001
                    print(f"[models]   - {repo_id}: blocked ({repo_exc})")
            print(
                "[models] Hint: For fine-grained HF tokens, ensure (1) user "
                "conditions are accepted on BOTH 'pyannote/speaker-diarization-3.1' "
                "and 'pyannote/segmentation-3.0', and (2) the token has "
                "'Read access to contents of all public gated repos you can access'."
            )
            return False
        pipeline.to(torch.device(device))
        del pipeline
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[models] ERROR downloading Pyannote: {exc}")
        return False


def verify_vision(device: str) -> None:
    from facenet_pytorch import MTCNN
    import mediapipe as mp

    print("[models] Verifying MTCNN & MediaPipe FaceMesh...")
    mtcnn = MTCNN(margin=20, post_process=False, device=device)
    mesh = mp.solutions.face_mesh.FaceMesh()
    mesh.close()
    del mtcnn


def main() -> int:
    _load_env()
    import torch
    from clipsai.config import huggingface_token

    default_device = "cuda" if torch.cuda.is_available() else "cpu"
    default_precision = "float16" if default_device == "cuda" else "int8"
    default_model = "large-v2" if default_device == "cuda" else "tiny"

    parser = argparse.ArgumentParser(
        description="Pre-download ClipsAI first-run models"
    )
    parser.add_argument("--whisper-model", default=default_model)
    parser.add_argument("--device", default=default_device)
    parser.add_argument("--precision", default=default_precision)
    parser.add_argument(
        "--align-langs",
        default="en",
        help="Comma-separated ISO 639-1 alignment languages (default: en)",
    )
    parser.add_argument("--skip-pyannote", action="store_true")
    parser.add_argument("--skip-embedder", action="store_true")
    args = parser.parse_args()

    download_nltk()
    download_whisperx(
        args.whisper_model,
        args.device,
        args.precision,
        args.align_langs.split(","),
    )
    if not args.skip_embedder:
        download_embedder(args.device)
    if not args.skip_pyannote:
        ok = download_pyannote(args.device, huggingface_token())
        if not ok:
            print("[models] WARNING: Pyannote pre-download did not complete.")
    verify_vision(args.device)
    print("[models] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
