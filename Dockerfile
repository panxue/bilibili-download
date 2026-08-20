# Bilibili yt-dlp Downloader — backend image
# Build: docker compose build / docker build -t bilibili-download .
# Note: uv.lock is not committed; deps are resolved live by uv sync from pyproject.toml, same as local start.sh.
#
# Package index build args (default to the official PyPI; override for mirrored networks, e.g. China:
#   docker build --build-arg UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
#                --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .)
# compose.yaml passes them through from the .env file, so nothing China-specific is hardcoded in this repo.
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

# ---- Dependency layer (built with uv, only the .venv output is kept) ----
# Use the same python:3.14-slim as the runtime as the builder; .venv/bin/python is a symlink
# to /usr/local/bin/python3.14, so the link stays valid after COPY into the runtime layer.
FROM python:3.14-slim AS builder
ARG UV_DEFAULT_INDEX
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/uv
ENV PATH="/uv/bin:$PATH" \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-install-project --no-dev

# ---- Runtime layer ----
FROM python:3.14-slim
# ffmpeg: required by yt-dlp for audio/video merging. Use the pip package imageio-ffmpeg (ships a static ffmpeg binary,
# avoiding the 133MB apt download and Debian source network issues); symlink it onto PATH so yt-dlp and the config probe find it.
# yt-dlp is installed as a Python library by the uv dependency layer (pyproject.toml), not installed here separately.
ARG PIP_INDEX_URL
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} \
        -U "imageio-ffmpeg==0.6.0" \
    && ln -sf "$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")" /usr/local/bin/ffmpeg
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY backend backend

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    BLDLP_HOST="0.0.0.0" \
    BLDLP_PORT="8000"

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
