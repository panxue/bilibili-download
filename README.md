# Bilibili Download · yt-dlp downloader

A Bilibili video download tool: userscript floating panel + local FastAPI backend + yt-dlp.

- Frontend: `userscript/bilibili-download.user.js` (userscript, injects a download floating panel into Bilibili pages)
- Backend: Python (FastAPI + SQLite), listens on `127.0.0.1:8000`
- Engine: yt-dlp (uv library) + ffmpeg (audio/video merging)

## Quick start

Two ways to run, pick one: **Docker (recommended, no dependencies to install)** or **source (uv)**.

### Option A: Docker (no repo clone needed)

```bash
# 1. Grab the two files into an empty directory
curl -sSL -o compose.yaml  https://raw.githubusercontent.com/panxue/bilibili-download/main/compose.yaml
curl -sSL -o .env.example  https://raw.githubusercontent.com/panxue/bilibili-download/main/.env.example

# 2. Create .env and set your options (here: download dir + auth token via sed)
mv .env.example .env
sed -i 's|^# BLDLP_DOWNLOAD_DIR_HOST=.*|BLDLP_DOWNLOAD_DIR_HOST=/home/you/Videos/bilibili|' .env
sed -i 's|^# BLDLP_TOKEN=.*|BLDLP_TOKEN=changeme|' .env
#    Other keys: BLDLP_CONCURRENT (max parallel jobs), BLDLP_PROXY, BLDLP_IMAGE_TAG

# 3. Pull the published image and start (data/ for jobs.db/cookies/.parts is created locally)
docker compose pull
docker compose up -d
```

- Uses the published Docker Hub image (`idevlife/bilibili-download`); `docker compose pull` updates it later
- `docker compose up -d --build` / `docker compose build` only make sense from a repo checkout (they need the Dockerfile + mirror build args)
- If your network blocks the default PyPI, download the Dockerfile too and set the mirror index in `.env` before building:
  `curl -sSL -o Dockerfile https://raw.githubusercontent.com/panxue/bilibili-download/main/Dockerfile`

### Option B: Source

```bash
# 1. Prepare the environment
#    - uv: https://github.com/astral-sh/uv
#    - yt-dlp: provided as a uv dependency (pyproject.toml)
#    - ffmpeg: apt install ffmpeg

# 2. Install dependencies
cd bilibili-download && uv sync

# 3. Copy the config and modify it
cp backend/config.example.toml backend/config.toml

# 4. Start the backend
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
#    or ./start.sh
```

### Install the frontend (shared by both options)

```bash
# 5. Install the userscript in your browser (Tampermonkey/Violentmonkey)
#    Open userscript/bilibili-download.user.js → copy → create a new script and save
#    Or from a raw URL: https://raw.githubusercontent.com/panxue/bilibili-download/main/userscript/bilibili-download.user.js

# 6. Open any bilibili video page → click the floating download panel at the bottom right
```

## Docs index

| Document | Content |
|----------|---------|
| [docs/requirements.md](docs/requirements.md) | Requirements spec: feature scope / boundaries / privacy |
| [docs/design.md](docs/design.md) | System architecture and data flow |
| [docs/api.md](docs/api.md) | Backend API contract and SSE events |
| [docs/ui.md](docs/ui.md) | Userscript / floating panel interaction design |
| [docs/state-lifecycle.md](docs/state-lifecycle.md) | Job state machine and interrupted-download resume |
| [docs/config.md](docs/config.md) | Config design (four-layer model) |
| [docs/changelog.md](docs/changelog.md) | Change index |

## Directory structure

```
bilibili-download/
├── pyproject.toml           # uv project (fastapi/uvicorn/yt-dlp)
├── .python-version          # 3.14
├── Dockerfile               # multi-stage image (uv dependency layer + pip runtime)
├── compose.yaml             # docker compose start/stop (loopback port + data volumes)
├── .dockerignore            # build-context exclusions
├── .env.example             # container env example (BLDLP_TOKEN / PROXY / CONCURRENT / mirror override)
├── start.sh                 # one-shot startup (uv sync + uvicorn)
├── backend/
│   ├── config.example.toml # config example
│   ├── config.toml         # runtime config (gitignored, copy it yourself)
│   ├── main.py             # FastAPI app and routes
│   ├── downloader.py       # yt-dlp library (YoutubeDL) + job queue + progress stream
│   └── db.py               # SQLite job persistence
├── userscript/
│   └── bilibili-download.user.js  # userscript (single file)
├── downloads/              # final output directory
├── data/                   # jobs.db + .parts staging
└── docs/
```

## Prerequisites

| Dependency | Purpose | How to get it |
|------------|---------|---------------|
| Docker (optional) | Containerized run | docker + compose plugin |
| uv | Source-run dependency management | https://github.com/astral-sh/uv |
| yt-dlp | Download engine | uv dependency (already inside the Docker image) |
| ffmpeg | Audio/video merging | `apt install ffmpeg` (source run) or imageio-ffmpeg in the image |
| Tampermonkey | Userscript runtime | browser extension |

> Two run modes: Docker container (image based on `python:3.14-slim`, official PyPI by default with an `.env` mirror override, ships yt-dlp/ffmpeg, artifacts land in `downloads/` via volume) or local source. See [docs/design.md](docs/design.md).