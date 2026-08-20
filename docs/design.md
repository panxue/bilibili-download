# 02 · System Architecture

## 1. Overview

```
┌──────────── Browser (Bilibili page) ────────────┐        ┌─────── Local Backend (127.0.0.1:8000) ───────┐
│  Tampermonkey runtime                           │        │  FastAPI (uvicorn)                           │
│  ├─ bilibili-download.user.js ────────────────┼─POST/─▶│  ├─ main.py         routing layer            │
│  │  inject floating panel (Shadow DOM)         │  SSE  │  ├─ downloader.py   queue + yt-dlp library   │
│  │  read __INITIAL_STATE__ + document.cookie   │◀──────│  ├─ db.py          SQLite job persistence    │
│  │  GM_get/setValue persistent settings        │        │  └─ config.toml / env vars                   │
│  └─────────────────────────────────────────────┘        └──────────────────────┬───────────────────────┘
cookie only sends SESSDATA/DedeUserID/bili_jct                │ to_thread
                                                                    ▼
                                                            yt-dlp library (YoutubeDL, via uv dependency)
                                                            + ffmpeg (apt install)
                                                            ↓ output
                                                        downloads/ (final mp4)
                                                        data/.parts/ (.part staging)
```

**Single-direction data flow**: userscript (fetch info/submit) → backend (persist/schedule) → yt-dlp library (download/merge) → progress flows back to the floating panel via SSE.

## 2. Component Responsibilities

### 2.1 Userscript `userscript/bilibili-download.user.js`

- Single file, no build; `@match https://www.bilibili.com/*`
- Injects a persistent floating panel (Shadow DOM → style isolation, does not pollute the page)
- Parses `window.__INITIAL_STATE__` to obtain metadata such as `bvid/cid/title/parts` (zero backend overhead)
- Reads the login state and cookie (only sends the necessary three keys)
- Communicates with the backend via `GM_xmlhttpRequest`; **a single global SSE (`EventSource` subscribed to `/api/jobs/stream`)** receives progress for all jobs, falling back to full polling on disconnect
- Settings panel persists via `GM_setValue/GM_getValue`

### 2.2 Backend FastAPI `backend/main.py`

- Routes: `/api/health` `/api/info` `/api/download` `/api/jobs` `/api/jobs/{id}` `/api/jobs/stream` `/api/jobs/{id}/stream` (kept for compatibility) `/api/jobs/{id}/resume` `/api/jobs/{id}/delete` `/api/config`
- On startup, scans SQLite: unfinished jobs → `interrupted` (awaiting user resume)
- Binds to `127.0.0.1`; optional `auth_token` (request header `X-Auth-Token`)
- Logs sanitized (cookie not printed)

### 2.3 Downloader `backend/downloader.py`

- asyncio queue, `max_concurrent` (default 2) concurrent slots
- Each job calls the **yt-dlp library** (`yt_dlp.YoutubeDL`) in an independent thread (`asyncio.to_thread`) to download/merge
- Library params (`format/outtmpl/paths/cookiefile/proxy/...`) see [state-lifecycle.md](state-lifecycle.md); progress is written back to state via `progress_hooks` structured callbacks; during the merge stage, `postprocessor_hooks` marks `phase=merging`
- Throttled every 0.5s: scans the job state table and incrementally broadcasts all jobs via **a single global SSE (`/api/jobs/stream`)** (change detection based on snapshot comparison)

### 2.4 Persistence `backend/db.py`

- Single SQLite table `jobs`: `id/url/status/params_json/output_path/times` (cookie not stored in the DB; re-submitted by the floating panel when the job is rebuilt)
- Restored from the DB after power loss/restart; jobs are retained permanently (can be listed/resumed by the floating panel)

## 3. Core Request Sequence

```
Floating Panel           FastAPI               downloader        yt-dlp library      SQLite
  ──┘                      │                      │                │                │
  1 GET /api/health ········▶  (probe; returns version, login-state-independent)
  2 POST /api/info ────────▶  extract_info(download=False) ─▶ quality list ─▶ returns title/quality list/logged_in; for bangumi seasons, also the per-episode page list (ep URLs) from the playlist resolution
  3 POST /api/download ──▶ create job(write DB) ─▶ enqueue to_thread ─▶ download+merge ─▶ update status(write DB)
  4 GET /api/jobs/stream (SSE,EventSource) ◀─ global progress/final-state event broadcast ◀── progress_hooks callback
  5 after completion, the floating panel shows the result; after power-loss restart scan → interrupted → POST resume to resume
```

## 4. Data Directory Conventions

| Path | Purpose | Git status |
|------|------|---------|
| `downloads/` | Final complete files (optionally subdirectories per UP) | ignored |
| `data/.parts/` | `.part` segment staging (persistent disk, not /tmp) | only `.gitkeep` kept |
| `data/jobs.db` | SQLite job database | ignored |
| `data/cookies.txt` | Persistent Netscape cookies.txt (`cookiefile` dependency, overwritten on every cookie received) | ignored |

## 5. Security Model

- Loopback binding + optional token (default empty = pure local-machine trust)
- cookie persisted at `data/cookies.txt` (Netscape, required by `cookiefile`), not in git; overwritten each time userscript cookie is received; logs sanitized
- No public network listening; `Origin`/`Host` validation (server-side CSRF prevention): only accepts requests without Origin (userscript GM requests can be configured without Origin) or from local loopback origin
- No floating panel field other than the raw cookie string is trusted — URL whitelist for Bilibili domains
- Cookie validity: `/api/info`, `/api/download`, `resume_after_interrupt` pre-validate `/x/web-interface/nav`, return `code:-3` on expiry

## 6. Dockerization (Current)

> The container is just **one way to run the backend locally**: `docker compose up -d` is equivalent to `start.sh`.
> Dependency governance: uv.lock not committed; builder uses `uv sync --no-install-project --no-dev` to resolve pyproject.toml in real time.
> Distribution: `docker compose build: .` builds in place; on `main` CI also builds and publishes the image to Docker Hub (`<user>/bilibili-download:latest` + version tag) as a **multi-arch manifest (linux/amd64 + linux/arm64)** via buildx + QEMU — Apple Silicon Macs pull the arm64 build automatically on `docker pull` / `docker compose pull`.
> Package index: **official PyPI by default, overridable via build args** (`UV_DEFAULT_INDEX` for the uv layer, `PIP_INDEX_URL` for the pip layer) — no China-specific source is hardcoded in the repo; compose passes them through from `.env`; **ffmpeg uses the pip package `imageio-ffmpeg`** (bundled static binary, bypasses apt's 133MB download), symlinked to `/usr/local/bin/ffmpeg`. The image is architecture-native: python/uv base images and every pinned wheel (imageio-ffmpeg ships `manylinux2014_aarch64`) exist for both arm64 and amd64.

```dockerfile
# Build args (optional): override for mirrored networks, e.g. a China mirror
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

# Stage 1 — uv dependency layer: produces /app/.venv
# Use the same python:3.14-slim as the runtime as the builder, ensuring .venv's bin/python
# symlink points to /usr/local/bin/python3.14; the link survives COPY to the runtime layer.
FROM python:3.14-slim AS builder
ARG UV_DEFAULT_INDEX
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/uv
ENV PATH="/uv/bin:$PATH" UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-install-project --no-dev

# Stage 2 — runtime layer
FROM python:3.14-slim
ARG PIP_INDEX_URL
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} \
        -U "imageio-ffmpeg==0.6.0" \
    && ln -sf "$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")" /usr/local/bin/ffmpeg
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY backend backend
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app"
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`compose.yaml` key points:
- Uses the **published Docker Hub image** `idevlife/bilibili-download:<tag>` by default (`docker compose up -d`); `docker compose up -d --build` rebuilds from source and tags the local image with the same name; `docker compose pull` updates to a newer published tag
- Port maps only to loopback `127.0.0.1:8000:8000` (consistent with the default host=127.0.0.1 security baseline; LAN requires 0.0.0.0 with `BLDLP_TOKEN`)
- Download directory is configurable at the host level: `BLDLP_DOWNLOAD_DIR_HOST` (default `./downloads`) maps to `/app/downloads` inside the container; `./data:/app/data` persists SQLite, cookie.txt, `.part` breakpoints
- `env_file: .env` (optional, not committed) passes through `BLDLP_TOKEN`/`BLDLP_CONCURRENT`/`BLDLP_PROXY`; `build.args` reads `UV_DEFAULT_INDEX`/`PIP_INDEX_URL` from the same `.env`
- The container runs as **root** (local single-user; no volume permission coordination burden)

### 6.1 Common Operations

```bash
docker compose up -d          # build and run in background
docker compose logs -f        # tail logs
docker compose down           # stop (volumes retained, resume not lost)
docker compose build          # rebuild image only
```

> Note: `data/.parts` must use a persistent volume inside the container (absolutely not `/tmp`); resume semantics are identical to bare metal, see [state-lifecycle.md](state-lifecycle.md).

## 7. Evolution Path (Reserved, Not in First Release)
- Chrome MV3 extension variant (httpOnly cookie capability) — see the replacement strategy at the end of [ui.md](ui.md)
- Danmaku XML download API (backend `POST /api/danmaku`, cid + cookie → XML)
- Web management page (view/delete history, global settings)
