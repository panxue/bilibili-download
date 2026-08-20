# 04 · Userscript / Floating Panel Interaction Design

> Deliverable: `userscript/bilibili-download.user.js` (single file, no build, zero dependencies).
> Runtime: Tampermonkey / Violentmonkey.

## 1. Script Metadata

```
// ==UserScript==
// @name         Bilibili yt-dlp Downloader
// @namespace    https://github.com/idevlife/bilibili-download
// @match        https://www.bilibili.com/*
// @run-at       document-idle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_xmlhttpRequest
// @grant        GM_cookie
// @grant        unsafeWindow
// @connect      127.0.0.1
// @version      0.3.0
// ==/UserScript==
```

## 2. Floating Panel Form

- Position: fixed at the bottom-right of the page, with an extreme `z-index`; **no dragging** (simplified interaction)
- Two states:
  - **Capsule state**: `[⬇ Download]` small button + backend status dot (green=online / red=offline / yellow=connecting). Click to expand
  - **Panel state**: 320px wide floating panel, scrollable, collapsible
- **Shadow DOM isolation**: all styles are attached to `:host`, so the page is not polluted and the panel is not disturbed by Bilibili styles
- Style tone: dark card (blends with Bilibili dark mode), 12px border radius, subtle lift on hover

```
┌──────────────────────────────┐
│ New Download  |  Tasks  |  Settings  │  ← Tab bar
├──────────────────────────────┤
│ [content area]                │
│                              │
│                              │
│                              │
├──────────────────────────────┤
│ [open download dir] [icon badge] │
└──────────────────────────────┘
```

## 3. Tab 1 · New Download (form)

| Area | Control | State / Interaction |
|------|------|----------|
| Video info card | thumbnail + title + uploader name + BV ID | spinner shown while parsing; red text + retry on parse failure |
| Login badge | `logged in · username` / `not logged in` | reads `document.cookie` for whether it contains `SESSDATA` |
| Part selection | checkbox list (current part checked by default) | multi-part collapses to "P1..Pn"; provides "select all / select none" |
| Quality | dropdown, see §3.1 | grayed out / unlocked based on login state |
| Additional | ☐ audio-only (linked to switching to the audio tier) | - |
| Main button | `Start download` | click→loading→POST→on success switch to "Job List" |

### 3.1 Quality Control (dynamic list, data-driven)

- The quality buttons are fully generated from `/api/info.available_qualities`, **no longer hard-coded presets**: `Auto ({auto_resolution})` + the real list; each button shows yt-dlp's own tier label (e.g. `4K 超高清`, `HDR 真彩`) plus a human-readable size, and carries the tier's bound `format_id` (the backend picks the concrete stream per the codec preference — the frontend just displays and passes it back)
- `auto_resolution` displays in real time the highest tier the auto tier resolves to under current permissions (e.g. `Auto (1080P60)`)
- The backend filters the list by cookie permissions → the frontend needs no gray-out logic; tiers lacking permission are simply not in the list (not logged in: only 480P and below); the first button (`Auto`) is pre-selected
- The settings panel "codec preference" dropdown: Auto (hev1>hvc1>av01>avc1) / HEVC>AV1>H.264 / AV1>HEVC>H.264 / H.264 first / HEVC only / H.264 only; values are literal yt-dlp vcodec prefixes, submitted with the `codec` field of `POST /api/info` (drives format_id binding) and echoed on `POST /api/download` (stored in GM_setValue; the backend only applies it per request, not persisted to the config store)

### 3.2 Parse Source Priority

1. Read page metadata locally: `unsafeWindow.__INITIAL_STATE__` (legacy pages) or `playurlSSRData`+`og:title` (modern SSR bangumi, title/BV/current-ep, zero latency; the userscript sandbox needs `unsafeWindow` to bypass isolation)
2. Quality list / login state permissions → backend `POST /api/info` (with the current three cookie keys)
3. Backend unreachable → keep the default structure, yellow bar at the top showing "Backend unreachable, quality not verified" (no downgrade of preset tiers, to avoid misleadingly selecting an unavailable tier)

## 4. Tab 2 · Job List

One card row per job:
```
[status badge] part-1 title.....................
   ▓▓▓▓▓▓▓▓░░░░░░  32.5% · 1.2MiB/s · ETA 0:32
   [pause] [cancel]
```

| Status | Badge color | Actions |
|------|--------|------|
| queued | gray | cancel |
| downloading | blue | pause / cancel |
| merging | purple | cancel |
| paused | orange | resume / cancel |
| interrupted | red | **resume download** (continue from .part) / delete |
| failed | red | **retry** / delete |
| canceled | gray | **resume** / delete |
| done | green | delete |

- Deleting a job calls backend `DELETE /api/jobs/{id}` (deleted → 404 → the frontend removes it from the cache and redraws); deleting a running job returns 409 and is rejected by the backend

- Each card has a **mini / full dual state**, mini by default: title + progress bar + `percent · speed · phase · ETA` + action buttons (omits the verbose local file path); click the title row or the top-right「expand」to switch to full (appends error details and `out_path`), click「collapse」to switch back. The expanded state is remembered per job (memory-level), and survives SSE refresh redraws
- Progress update source: **single global** `EventSource(/api/jobs/stream)` (events carry job_id); `onerror` → 2s full polling of `GET /api/jobs` as fallback, stop polling after successful reconnect (`open`)
- Multiple jobs (multiple parts) each get their own row but share the same event stream; the top shows an aggregate `3/5 done`
- Empty state: `No jobs yet. Start one on the New Download tab.`

## 5. Tab 3 · Settings Panel

| Item | Default | Storage |
|----|------|------|
| Backend URL | `http://127.0.0.1:8000` | GM_setValue |
| auth_token | empty | GM_setValue |
| Codec preference | auto | GM_setValue |

- Panel bottom: read-only display of concurrency, yt-dlp version, and file template returned by `GET /api/config` (backend status)
- Emergency channel: `GM_registerMenuCommand("Set backend URL", ...)` pops an input — an escape hatch when the floating panel fails to render

## 6. Full Interaction Sequence (main flow)

```
1. Enter the play page document-idle → inject capsule (connecting)
2. GET /api/health → green dot ready (failure→red dot + tooltip "Please run uv run uvicorn ...")
3. Click capsule → expand → parse __INITIAL_STATE__ / playurlSSRData (bangumi) → spinner→form; in parallel POST /api/info to fill in qualities (and the full episode list for a season URL)
4. User picks a tier → click "Start download" → POST /api/download → get jobs[] → auto switch to Tab2
5. Tab2 opens a single global `EventSource(/api/jobs/stream)` → dispatch real-time progress/terminal state by job_id
6. Exceptions: SSE drops → poll; backend 400/4xx → red bar with the reason
7. After power loss and restart, return to the page → Tab2 shows an interrupted row → click "Resume download" → POST resume_after_interrupt
```

## 7. Cookie Handling

- Only the three keys `SESSDATA`/`DedeUserID`/`bili_jct` are taken and concatenated into a string for submission
- SESSDATA is HttpOnly and unreadable via `document.cookie` → **primary channel `GM_cookie.list`** (requires user authorization); when unsupported, downgrade to `document.cookie` (if SESSDATA cannot be read, show "not logged in" and log a console message)
- Not logged in (no SESSDATA) → submit an empty string → the backend uses the guest channel
- Cookies are only submitted with `/api/info`, `/api/download`, `resume_after_interrupt`; not stored in browser local storage
- The backend persists them as a permanent Netscape `cookiefile` (not in git, logs desensitized); invalid cookies are intercepted in advance by the nav interface validation returning `code:-3`

## 8. Errors and Edge-case Feedback

| Scenario | Frontend behavior |
|------|---------|
| Backend not started | red capsule dot; yellow bar in the tab showing the startup command |
| Token error | 401 red bar + jump to the settings panel |
| Cookie invalid (-3) | red bar on parse/download prompting to refresh the Bilibili page |
| Job not found (-404) | frontend stops polling; list refresh is driven by backend state |
| Deleting a running job (409) | red bar "job is downloading or queued, cannot delete" |
| Non-Bilibili video page | floating panel shows "only bilibili video page URLs are supported" |
| Page switch/close | floating panel is destroyed with the page (no cross-page persistence); the job list is restored from the backend when reopened |

## 9. Chrome MV3 Variant (reserved replacement strategy)

If HttpOnly cookies or store distribution are ever needed:
- Port the same UI code into a content script (still Shadow DOM)
- Switch cookies to `chrome.cookies.get` (the API can read HttpOnly)
- Cross-origin goes through `chrome.runtime.sendMessage` → background `fetch`, no GM permissions needed
- manifest permissions: `cookies`, `host_permissions: ["http://127.0.0.1:8000/*","https://*.bilibili.com/*"]`
