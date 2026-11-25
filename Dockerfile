# syntax=docker/dockerfile:1
#
# ClipsAI Studio - production image (CPU-only).
#
# Build:
#   docker build -t clipsai-studio .
#   docker build --build-arg PRELOAD_MODELS=true -t clipsai-studio .
#
# Run:
#   docker run --rm -p 7860:7860 \
#       --env-file .env \
#       -e CLIPSAI_AUTH=user:password \
#       -v clipsai-cache:/app/.cache \
#       -v "$PWD/outputs:/app/outputs" \
#       clipsai-studio
#
# NLTK tokenizers are pre-downloaded at build time; pass
# --build-arg PRELOAD_MODELS=true to also pre-bake public WhisperX, VAD,
# alignment, and SentenceTransformer weights. Pyannote speaker diarization
# weights download into HF_HOME on first use (or via scripts/download_models.py)
# when HF_TOKEN has access to the gated pyannote repos.

FROM python:3.9-slim

ARG PRELOAD_MODELS=false

# ffmpeg/fontconfig/fonts-dejavu-core back ClipsAI's media, caption, hook, and
# thumbnail pipeline; libmagic1 backs python-magic's file-type detection.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    TORCH_HOME=/app/.cache/torch \
    NLTK_DATA=/app/.cache/nltk_data \
    MPLCONFIGDIR=/tmp/matplotlib \
    CLIPSAI_OUTPUT_DIR=/app/outputs

WORKDIR /app

# CPU-only PyTorch wheels keep the image far smaller than the default CUDA build.
RUN pip install --upgrade pip \
    && pip install "torch==2.2.2" "torchaudio==2.2.2" "torchvision==0.17.2" \
        --index-url https://download.pytorch.org/whl/cpu

# Install ClipsAI + the UI, pinned by the committed lock file.
COPY constraints.txt ./
COPY setup.py setup.cfg README.md ./
COPY clipsai ./clipsai
RUN pip install -c constraints.txt "setuptools<81" \
    && pip install -c constraints.txt ".[ui]" "mediapipe==0.10.14" "whisperx==3.3.1"

COPY app.py ./
COPY scripts ./scripts

RUN mkdir -p /app/outputs /app/.cache/huggingface /app/.cache/torch /app/.cache/nltk_data \
    && python -c "import nltk; nltk.download('punkt', download_dir='/app/.cache/nltk_data', quiet=True); nltk.download('punkt_tab', download_dir='/app/.cache/nltk_data', quiet=True)" \
    && if [ "$PRELOAD_MODELS" = "true" ]; then python scripts/download_models.py --skip-pyannote; fi \
    && groupadd --system clipsai \
    && useradd --system --gid clipsai --home /app clipsai \
    && chown -R clipsai:clipsai /app

USER clipsai

EXPOSE 7860
VOLUME ["/app/outputs", "/app/.cache"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/', timeout=5)"]

CMD ["python", "app.py", "--host", "0.0.0.0", "--no-browser"]
