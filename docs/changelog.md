# Changelog

## 1.0.0 — 2026-08-19 — Initial public release

- First public release: code and docs fully translated to English, version pinned to 1.0.0 (pyproject / userscript / /api/health), LICENSE (MIT) added, git history squashed to a single commit, repo made public (see docs/iterations/1.0.0.md).

## 0.5.3 — 2026-08-14 — yt-dlp subprocess → Python library migration

- Engine changed from invoking the `yt-dlp` bin in PATH via subprocess to the `yt_dlp.YoutubeDL` library (dedicated thread + structured `progress_hooks` progress + `DownloadCancelled` cancellation); removed the `yt_dlp_path` config and `BLDLP_YT_DLP`, `/api/config` reverted to `yt_dlp_version`; the Docker image no longer installs yt-dlp separately (provided by the uv dependency layer) (see docs/iterations/0.5.3.md).

## 0.5.2 — 2026-08-13 — pytest unit test moat + requirements current-state sync

- Added `backend/tests/` (pytest + pytest-asyncio, all 46 cases green): codec normalization/preference, quality_to_format, parse_probe grouped by qn, cancel-queued regression, cookie pre-validation, db persistence and cookies not persisted; pyproject pinned Tsinghua source and added pytest config (see docs/iterations/0.5.2.md).

## 0.5.1 — 2026-08-12 — review fixes: queued cancel ineffectiveness and doc drift

- Fixed queued jobs still starting download after cancel (worker skips terminal-state jobs); settings panel default quality filled in 1080P60/720P60/360P; corrected api/config/ui doc and implementation drift (SIGTERM/-409/progress fields/overflow error codes/unimplemented claims) (see docs/iterations/0.5.1.md).

## 0.5.0 — 2026-08-12 — Docker Compose support

- Added Dockerfile + compose.yaml: one-command `docker compose up -d` starts the backend (ffmpeg + yt-dlp==2026.07.04), port mapped loopback only, downloads/data volumes persisted, `.env` optionally injects `BLDLP_*`; uv.lock stays out of the repo, no registry dependency (see docs/iterations/0.5.0.md).

## 0.4.1 — 2026-08-11 — 1080P60 display fix and configurable codec

- Quality list now grouped by qn (Bilibili quality code), 1080P and 1080P high frame rate displayed separately (`1080P60`); codec default preferred in `hvc>av01>avc` order, codec preference configurable in the userscript settings panel and submitted with download requests (see docs/iterations/0.4.1.md).

## 0.4.0 — 2026-08-10 — live task list refresh and card UI

- Fixed task list progress not refreshing (`currentTab` not synced, stuck at 0% on first entry); SSE changed to a single global `/api/jobs/stream` broadcasting all jobs (avoids the per-host concurrent connection limit), polling fallback changed to full `GET /api/jobs`; task cards support mini/full two-state expansion, historical completed jobs backfilled to 100% (see docs/iterations/0.4.0.md).

## 0.3.0 — 2026-08-09 — high-tier quality and robustness hardening

- Persistent cookies (Netscape + `--cookies`) unlock 8K/4K; added cookie validity pre-validation; progress staging changed to `--paths temp:`; error body unified to `{code,msg}`; job deletion made backend-authoritative (see docs/iterations/0.3.0.md).

## 0.2.0 — 2026-08-09 — first runnable implementation

- Backend `backend/` (config/db/downloader/main/urls) and userscript `userscript/bilibili-download.user.js` ready and verified end-to-end (health/info/download/pause/resume/cancel/SSE), dependencies managed by uv (see docs/iterations/0.2.0.md).

## 0.1.0 — 2026-08-09 — Documentation baseline

- Documentation baseline: six documents finalized — spec / architecture / API / floating panel interaction / state machine and resume / config (see docs/iterations/0.1.0.md). Documentation phase only, no business code.
