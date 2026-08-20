# AGENTS.md

## Project overview

Bilibili video downloader: browser userscript floating panel + local FastAPI backend + yt-dlp engine (**Python library**, managed with uv). The core pipeline is implemented and shipped (since 0.2.0, the first runnable release): userscript floating panel, job queue, SSE realtime progress, interrupted-download resume, persistent cookies, Docker containerization, and a 46-case unit test moat.

## Doc layout (doc-standards)

| Document | Role |
|----------|------|
| `docs/requirements.md` | Requirements baseline + current-state revision (changes tracked in changelog) |
| `docs/design.md` | Current architecture (living) |
| `docs/state-lifecycle.md` | Job state machine + interrupted-download resume operations |
| `docs/api.md` | Backend API contract and SSE events |
| `docs/ui.md` | Userscript floating panel interaction design |
| `docs/config.md` | Four-layer config model |
| `docs/changelog.md` | Change index (one-line summary + link only) |
| `docs/iterations/<version>.md` | Per-version change details (`Topic | Before → After | Reason`) |

Architecture conventions: read `docs/design.md` first for design; append change records per `docs/changelog.md` rules. The doc-standards skill is vendored to `.agents/skills/doc-standards/`, distilled decisions live in `.agents/memories/`.

## Commands

Dependency and env management uses **uv** (Python ≥3.12, `.python-version` = 3.14):

```bash
uv sync                       # Install dependencies (fastapi / uvicorn / yt-dlp)
uv lock                       # Refresh the lock file
uv run ruff check backend/    # Lint (dev dependency group)
uv run pytest                 # Unit tests (backend/tests/, 46 cases)
```

> When the network is restricted, dependencies install via a mirror: the repo **does not hardcode any package source** — uv defaults to the official PyPI; for China use set `UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"` in the shell (e.g. `.envrc`) before `uv sync` / `uv add`.

**Local startup**:

```bash
cp backend/config.example.toml backend/config.toml
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
# or ./start.sh
```

**Docker startup** (optional, no local dependencies needed):

```bash
docker compose up -d --build
# Optional: cp .env.example .env and set BLDLP_TOKEN / BLDLP_PROXY as needed
# In China, also set UV_DEFAULT_INDEX / PIP_INDEX_URL in .env to the Tsinghua mirror for the image build
```

> The Docker image uses official PyPI by default; the mirror is a build-time override via `UV_DEFAULT_INDEX` / `PIP_INDEX_URL` build args (compose reads them from `.env`), never hardcoded in the repo. On `main`, CI builds and pushes the image to Docker Hub (`<user>/bilibili-download`).

Runtime prerequisites (already installed locally): Python 3.12+ / uv, Tampermonkey/Violentmonkey (browser). yt-dlp is a uv library dependency (not a PATH bin); ffmpeg needs `apt install ffmpeg` for source runs, the Docker image ships imageio-ffmpeg.

## Directory structure

```
├── pyproject.toml            # uv project declaration (don't hand-edit the dependency array; use uv add/remove)
├── start.sh                  # one-shot startup (uv sync + uvicorn)
├── Dockerfile                # multi-stage image (uv dependency layer + pip runtime imageio-ffmpeg)
├── compose.yaml              # docker compose start/stop (loopback port + downloads/data volumes)
├── .env.example              # container env example (BLDLP_TOKEN / PROXY / CONCURRENT)
├── .github/workflows/ci.yml  # ruff + pytest (Python 3.12/3.14 matrix) + Docker build/push to Docker Hub on main
├── backend/
│   ├── config.example.toml   # config example (config.toml not committed)
│   ├── config.py             # TOML + env config loading
│   ├── main.py               # routes (info/download/jobs/stream/config)
│   ├── downloader.py         # yt-dlp library (YoutubeDL) + queue + progress stream
│   ├── db.py                 # SQLite job persistence
│   ├── urls.py               # API path constants
│   └── tests/                # pytest cases (46)
├── userscript/               # bilibili-download.user.js (userscript, single file)
├── downloads/                # output directory (gitignored)
├── data/                     # jobs.db + cookies.txt + .parts (gitignored)
├── docs/                     # project docs (see table above)
└── .agents/                  # agent config (skills/ + memories/)
```

## Conventions (must follow during coding)

- **uv-managed dependencies**: add/remove deps with `uv add` / `uv remove`; never hand-edit the `pyproject.toml` dependency array without syncing the lock file; yt-dlp is a Python library dependency (`uv add yt-dlp`), not a PATH bin
- **TOML-first config**: `backend/config.toml`; the userscript side prefers browser `GM_setValue`
- **Cookies never stored in the DB**: only the three keys (SESSDATA/DedeUserID/bili_jct) are submitted with `/api/info` and `/api/download`, written to the persistent `data/cookies.txt` (`cookiefile`), logs redacted, never in git
- **Resume**: `.part` uses the yt-dlp library `paths: {"home": ..., "temp": staging_dir}` (only `home/temp` are accepted, `incomplete` is invalid), `outtmpl` must be a relative path, `staging_dir` must not be `/tmp`
- **Progress**: SSE primary + polling fallback; structured `progress_hooks` callbacks from the yt-dlp library (no text parsing)
- **Auth**: loopback `127.0.0.1` only by default, optional `auth_token`
- **Bilibili downloads require**: `http_headers: {"Referer": "https://www.bilibili.com/"}` + quality matching cookie permissions
- **Control**: pause/cancel set a `threading.Event` on the download thread → progress_hook raises `yt_dlp.utils.DownloadCancelled` (no SIGTERM)
- No danmaku (excluded from the first release, see requirements.md)

## Doc update rules

- A change to `requirements.md` / `design.md` must also add an index entry to `docs/changelog.md` and write `docs/iterations/<version>.md` details (reason required)
- Changelog index entry: `## <version> — <date> — <change type>` + one-line summary + link to the iteration doc, no embedded details
- Commit message style: `<type>: <subject>` (`docs:` / `feat:` / `fix:` / `refactor:`)

## Security notes

- `backend/config.toml`, `data/`, `downloads/` are in `.gitignore`, never commit them
- Token and cookies never appear in logs or git