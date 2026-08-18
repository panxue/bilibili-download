# 01 · Requirements Specification

> Status: finalized at the v0.1 documentation stage; subsequent iterations have been progressively implemented (0.2.0–0.5.1). This file is a mix of **baseline + current-state revision**: changes are indexed in `docs/changelog.md`, details in `docs/iterations/`.

## 1. Project Positioning

A video download tool for Bilibili: **userscript (frontend floating panel) + local FastAPI backend + yt-dlp engine**. Users click the floating panel in the bottom-right corner of a Bilibili video page to start a download; progress syncs in real time and interrupted download resume is supported.

## 2. Target Users and Scenarios

- Single-machine personal users with Tampermonkey/Violentmonkey installed in the browser (Chromium/Firefox)
- A dev environment on the local machine that can run `uv` / Python / yt-dlp / ffmpeg, or a backend host running 24 hours
- Both logged-in Bilibili (enjoying HD and multiple tiers) and not-logged-in (only public low quality) must be usable

## 3. Feature Scope

### 3.1 First Release (P0) Included

| No. | Feature | Description |
|------|------|------|
| F1 | Floating panel injection | Capsule in the bottom-right corner of the player page + 320px panel, Shadow DOM style isolation |
| F2 | Video info parsing | Reads `window.__INITIAL_STATE__` from the page: title/UP/BV/parts; quality list via backend `POST /api/info` |
| F3 | Quality selection | Quality buttons driven by `/api/info.available_qualities` data (grouped by qn, including high-frame-rate tiers 1080P60/720P60), default `Auto (highest tier)`; codec preference order configurable (`hvc>av01>avc` default, changeable in settings panel) |
| F4 | Start download | Submit per part → backend creates SQLite job → queue concurrency (default 2) |
| F5 | Real-time progress | Backend pushes progress (percent/speed/eta/phase) via a single global SSE (`/api/jobs/stream`); the floating panel event bar refreshes in real time, with auto polling fallback on disconnect |
| F6 | Job management | Job list view: pause/resume, cancel, resume (after power loss/failure), delete |
| F7 | Interrupted download resume | `.part` segmented staging directory + SQLite-persisted job + `interrupted → resume` |
| F8 | Logged-in / not-logged-in dual mode | Login badge, quality tiers linked to permissions (insufficient-permission tiers excluded from the list), low-quality downgrade fallback |
| F9 | Settings panel | In-panel settings: backend URL/token/default quality/codec preference (GM persistence) |
| F10 | Backend configuration | TOML config file: download directory, ffmpeg path, concurrency, template, proxy, token |

### 3.2 First Release (Excluded, Later Iterations)

- Danmaku download (yt-dlp does not natively support Bilibili danmaku; the backend would need to separately request the danmaku XML API)
- Subtitle generation / external subtitles
- Time segment clipping
- Favorites / Watch Later batch import
- Chrome native extension variant (MV3)
- Web management page for history
- Open download directory button (jump to local directory on click in the job list)

> Note: Docker one-click deployment was implemented in 0.5.0 (originally listed as excluded, see `docs/iterations/0.5.0.md`).

## 4. Non-Functional Requirements

### 4.1 Privacy and Security
- Backend only listens on `127.0.0.1`; optional `auth_token` as secondary protection
- cookie only takes the three keys `SESSDATA`/`DedeUserID`/`bili_jct` and submits them temporarily with the job, **not written to SQLite**; stored at `data/cookies.txt` (Netscape persistent file, excluded by `.gitignore`, logs sanitized, readable only on the local machine)
- The userscript only reads the current page / current URL / page metadata, with no permissions over other sites
- Cross-origin requests use `GM_xmlhttpRequest`; when used, no CORS relaxation is needed; keep the surface minimal

### 4.2 Reliability
- Power loss/crash: job metadata is already persisted to SQLite; `.` re-run with the same params to resume the `.part`
- Network interruption: yt-dlp library `retries/fragment_retries/file_access_retries = inf` auto retry
- Merge interruption: re-run automatically re-merges `*.mp4.temp`

### 4.3 Performance
- Concurrent downloads default 2 (configurable), queue based on asyncio
- Progress stream pushed with 0.5s throttling

## 5. Boundaries and Limitations

- Non-premium/tourist quality === determined by the real permissions the backend returns (graying out on the page is a hint, not a promise)
- Download capability is limited by the official APIs of the current login state; expired cookie requires refreshing the page to regenerate
- DRM/paid/exclusive content cannot be downloaded
- Completed parts in a collection are not re-downloaded (each part is an independent job)
- First backend startup requires the user to execute a command on the local machine (source run) or `docker compose up -d`

## 6. Glossary

| Term | Meaning |
|------|------|
| floating panel | Collapsible panel injected into the bottom-right corner of the page by the userscript |
| job | One video recorded by the backend (one part = one job) |
| jobId | UUID of the job |
| .part | Partial download file written by yt-dlp to the staging directory |
| staging_dir | `.part` staging directory (persistent disk, not /tmp) |
| SSE | Server-Sent Events, read-only event stream pushed from the backend to the floating panel |
