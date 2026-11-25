# syntax=docker/dockerfile:1
#
# ClipsAI Studio - production image (CPU-only).
#
# Build:
#   docker build -t clipsai-studio .
#
# Run:
#   docker run --rm -p 7860:7860 \
#       -e HF_TOKEN=<your_huggingface_token> \
#       -e CLIPSAI_AUTH=user:password \
#       -v clipsai-models:/app/.cache/huggingface \
#       -v "$PWD/outputs:/app/outputs" \
#       clipsai-studio
#
# Model weights are downloaded on first use into HF_HOME; mount a volume there so
# they are not re-downloaded on every container start.

FROM python:3.9-slim

# ffmpeg is required by ClipsAI's media pipeline; libmagic1 backs python-magic's
# file-type detection.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
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

EXPOSE 7860
VOLUME ["/app/outputs"]

CMD ["python", "app.py", "--host", "0.0.0.0", "--no-browser"]
