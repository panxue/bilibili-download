# 03 · Backend API Contract

> Base URL: `http://127.0.0.1:8000` (configurable). JSON unless otherwise noted.
> Auth: `X-Auth-Token` request header (omitted when `auth_token` is configured as empty).

## 0. Common Conventions

- All responses are shaped as `{ "code": 0, "data": {...} | [...], "msg": "ok" }`
  - When `code != 0`, `data` may be `null` and `msg` carries a readable error
- Timestamps: `ISO8601` (UTC)
- Request body limit: `POST /api/info`, `/api/download` have small payloads (contain cookie strings, a few hundred bytes)

## 1. Health Check

### `GET /api/health`
Used by the floating panel to determine whether the backend is online.
```json
{
  "code": 0,
  "data": {
    "ok": true,
    "version": "1.1.0",
    "yt_dlp": "2026.08.19",
    "ffmpeg": true,
    "max_concurrent": 2
  }
}
```

## 2. Video Info (Prefetch / Quality List)

### `POST /api/info`
Request:
```json
{
  "url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "cookies": "SESSDATA=...; DedeUserID=...; bili_jct=..."   // may be an empty string (not logged in)
}
```
Response:
```json
{
  "code": 0,
  "data": {
"bvid": "BV1xx411c7mD",
  "title": "Video Title",
  "uploader": "Uploader",
  "duration": 482,
  "logged_in": true,
  "vip_type": "big_vip",          // none / vip / big_vip
  "auto_resolution": "1080P60",   // highest tier that auto actually resolves to under current permissions (highest by qn)
  "available_qualities": [
    { "qn": 112, "label": "1080P60", "codecs": ["hvc", "av01", "avc"] },
    { "qn": 80,  "label": "1080P",   "codecs": ["hvc", "av01", "avc"] },
    { "qn": 64,  "label": "720P",    "codecs": ["hvc", "av01", "avc"] },
    { "qn": 32,  "label": "480P",    "codecs": ["hvc", "av01", "avc"] }
  ],
    "pages": [
      { "cid": 1234567, "page": 1, "title": "Part 1 Title", "part": 1 }
    ]
  }
}
```
- `available_qualities` has already been filtered by the current cookie permissions; `auto_resolution` = the highest `qn` among them
- Grouped by **qn (Bilibili quality code)**: 1080P and 1080P60 (high frame rate, qn=112/116) are listed separately (yt-dlp reports the same height/fps for both, so they can only be distinguished by qn)
- `codecs` are sorted by codec preference `hvc > av01 > avc` (HEVC > AV1 > H.264)
- Login state differences are prefetched by the backend (tiers lacking permission are excluded from the list), so the frontend does not need to gray them out; the unauthenticated list generally only goes up to 480P
- **Bangumi seasons** (`/bangumi/play/ss…`): yt-dlp returns a playlist, so `pages` contains one entry **per episode** with a `url` field pointing at that episode's `/bangumi/play/ep…` link; `title` is the season name and `available_qualities` is unioned across the resolved episodes. Single `ep` links behave like a one-part video (no `url` on the single page entry).
- Request failure (network / invalid URL): `code=-2, msg="parse failed"`; invalid cookies: `code=-3`

## 3. Start a Download

### `POST /api/download`
Request:
```json
{
  "url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "pages": [ 1, 2, 3 ],              // parts to download; if omitted, defaults to the current part only
  "urls": ["https://www.bilibili.com/bangumi/play/ep32374"],  // optional; one ep URL per page, used for bangumi seasons
  "quality": "auto",                 // auto | 8K | 4K | 2K | 1080P60 | 1080P | 720P60 | 720P | 480P | 360P | NNNP | audio
  "codec": "auto",                   // codec preference order: auto (default hvc>av01>avc) or comma-separated e.g. "avc,hvc,av01"
  "audio_only": false,               // set to true when quality=audio
  "cookies": "SESSDATA=...; DedeUserID=...; bili_jct=...",  // may be empty
  "overwrite": false,
  "title": "Video Title"                 // for display; job title = "{title} P{n}"
}
```
- `urls` (optional) is parallel to `pages`: when provided, each job uses `urls[i]` as its download URL instead of `with_page(url, pages[i])`. Season pages populate it with each selected episode's `/bangumi/play/ep…` URL (returned by `/api/info`); ordinary multi-part videos keep using the `?p=N` mechanism and leave it empty.
Response:
```json
{
  "code": 0,
  "data": {
    "jobs": [
      {
        "id": "uuid-...",
        "status": "queued",          // queued | downloading | merging | done | failed | paused | interrupted
        "bvid": "BV1xx411c7mD",
        "page": 1,
        "title": "Part 1 Title",
        "out_path": "/abs/path/downloads/Uploader/BV1xx411c7mD Part 1 Title.mp4"
      }
    ]
  }
}
```
- Each part gets its own independent job (they don't affect each other; completed ones are not re-downloaded)
- `status` is initially `queued`; after enqueueing it is scheduled by the queue
- If the requested tier is unavailable, the backend automatically downgrades to the highest available one and notes `"downgraded: not logged in (480P)"` in the job detail `result`

## 4. Job Query

### `GET /api/jobs?limit=50&status=all`
All jobs (including history), ordered by creation time descending.
```json
{
  "code": 0,
  "data": {
    "total": 12,
    "jobs": [ { ...job detail below... } ]
  }
}
```

### `GET /api/jobs/{id}`
```json
{
  "code": 0,
  "data": {
    "id": "uuid-...",
    "bvid": "BV1xx411c7mD",
    "page": 1,
    "title": "Part 1 Title",
    "url": "...",
    "status": "downloading",
    "quality_requested": "1080P",
    "quality_actual": "720P",        // actual tier after downgrade
    "progress": { "percent": 32.5, "speed": "1.2MiB/s", "eta": "0:32" },
    "phase": "downloading",          // downloading | merging
    "out_path": "/abs/path/...mp4",
    "error": null,
    "created_at": "2026-08-09T08:00:00Z",
    "finished_at": null
  }
}
```

## 5. Real-time Progress (SSE)

### `GET /api/jobs/stream` (global stream · main frontend channel)
- Content-Type: `text/event-stream`
- A single SSE broadcast covers the progress and terminal state of **all jobs**, with events carrying `job_id`; the browser only occupies 1 connection, not subject to the single-host concurrent connection limit, and there is no need to open a separate SSE per job
- Right after the connection is established, the current snapshot is pushed in full once (including historical terminal states), after which incremental pushes are throttled at 0.5s (changes determined by comparing snapshots)
- Event types and fields:
```json
// event: progress   (non-terminal states: queued/downloading/merging/paused/interrupted etc.)
data: {"id":"...","status":"downloading","phase":"downloading","progress":{"percent":32.5,"speed":"1.2MiB/s","eta":"0:32"}}

// event: status     (terminal states: done/failed/canceled, pushed once per connection, then not pushed again)
data: {"id":"...","status":"done","out_path":"/abs/...mp4","error":null}
```
- The event name intentionally does not use `error` (that is the EventSource network-layer event name); the `failed` terminal state also goes through `status`

### `GET /api/jobs/{id}/stream` (single-job stream · kept for compatibility)
- Early versions used one SSE per job (dual events on a single channel); the new frontend no longer uses it; events include `progress` / `status` / `done` / `error`.

### Disconnect Strategy
- The floating panel uses a single `EventSource(/api/jobs/stream)`; on `onerror` → switch to 2s **full polling** of `GET /api/jobs?status=all` as fallback; stop polling once the SSE reconnects successfully (`open` event).

## 6. Job Control

### `POST /api/jobs/{id}/pause`  /  `POST /api/jobs/{id}/resume`(pause/resume download)  /  `POST /api/jobs/{id}/cancel`
- The downloader sets a `threading.Event` on the yt-dlp library download thread; the progress_hook detects it and throws `DownloadCancelled` to abort (equivalent to the old SIGTERM; the `.part` is preserved by `continue` for resume)
- Response `{code:0, data:{status:"paused"}}` etc.

### `POST /api/jobs/{id}/resume_after_interrupt`
**Dedicated to interrupted download resume**: re-runs the yt-dlp library with the original parameters (continuing from `.part`).
- Only effective for `status ∈ {interrupted, failed, canceled}`
- The request may carry `cookies` to override (defaults to the cookies at job creation; if empty they stay empty); invalid cookies return `code=-3`
- Returns the same job structure as `POST /api/download`, with `status=queued`
- Idempotent: repeated calls return error `code=-409` only when the job is already `done`

### `DELETE /api/jobs/{id}`
Deletes a historical job record (terminal-state cleanup). Running/queued jobs return `409`, non-existent `404`.

## 7. Config Read

### `GET /api/config`
The floating panel displays read-only backend info (backend config cannot be changed).
```json
{
  "code": 0,
  "data": {
    "download_dir": "/abs/path/downloads",
    "staging_dir": "/abs/path/data/.parts",
    "max_concurrent": 2,
    "file_template": "[%(id)s] %(title)s.%(ext)s",
    "subdir_by_uploader": true,
    "proxy": "",
    "auth_token_required": false,
    "yt_dlp_version": "2026.08.19"
  }
}
```
> Userscript-side settings (backend URL / token / default quality) belong to browser-side storage and are not read/written through this endpoint.

## 8. Error Codes

| code | meaning | suggested action |
|------|------|---------|
| 0 | success | - |
| -1 | parameter error (URL not Bilibili) | check input |
| -2 | parse failure | retry or switch source |
| -3 | invalid/expired Cookie | refresh the Bilibili page and log in again |
| -401 | auth failure (token mismatch) | check userscript settings |
| -404 | job not found (may have been deleted) | frontend stops polling / refresh the list |
| -409 | invalid job state / running job cannot be deleted | frontend grays out the button or waits for completion |

> Error responses are uniformly `{code, msg}` (FastAPI `HTTPException` converted by the global handler); the frontend only recognizes `code===0` and `-401`.
