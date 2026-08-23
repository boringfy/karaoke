# karaoke-server container.
#
# Two stages: some ML extras (diffq) are C/Cython extensions that must be
# compiled, but a compiler has no business in the runtime image. The builder
# populates a venv, and the runtime stage copies just that.
#
# Torch comes from the CPU wheel index on purpose: the CUDA build pulls several
# GB of nvidia libraries, and GPU passthrough additionally needs the nvidia
# container toolkit on the host.

# --------------------------------------------------------------- builder
FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU-only torch first so the heavy layer caches independently of the source.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch torchaudio

WORKDIR /src
COPY pyproject.toml README.md ./
COPY karaoke_server/ karaoke_server/
RUN pip install '.[ml]'

# --------------------------------------------------------------- runtime
FROM python:3.12-slim

# ffmpeg is required at runtime (probing, transcoding, instrumental encoding).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    KARAOKE_DATA_DIR=/data \
    KARAOKE_HOST=0.0.0.0 \
    KARAOKE_PORT=8787 \
    HF_HOME=/data/models/hf

# Run as the host user so files written into the volume are not root-owned.
RUN useradd -u 1000 -m karaoke || true
USER 1000:1000

WORKDIR /app
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8787/health || exit 1

CMD ["karaoke-server"]
