# 05 · Progress Sync and Interrupted Download Resume

## 1. Progress Sync (floating panel ⇄ backend)

### 1.1 Data source: yt-dlp library progress_hooks
The backend runs `yt_dlp.YoutubeDL` in an independent thread (`asyncio.to_thread`), progress driven by **`progress_hooks` structured callbacks** (not text parsing):

```
def hook(d):   # d: {"status": "downloading", "downloaded_bytes", "total_bytes", "speed", "eta", ...}
    percent = downloaded_bytes / total_bytes * 100
    # → write back state.percent / state.speed / state.eta
```

- `status=downloading` means currently downloading; during the **merge/transcode stage** yt-dlp triggers `postprocessor_hooks` (`{"status":"started","postprocessor":"FFmpegMergerPP"}`) → mark `phase=merging`
- After the download thread finishes, the return value `requested_downloads[0].filepath` provides the final artifact path → `done`
- User pause/cancel: the control interface sets `threading.Event`; the progress hook detects it and raises `yt_dlp.utils.DownloadCancelled`, the thread exits and `.part` is retained

### 1.2 Push channel: single global SSE

```
GET /api/jobs/stream
Content-Type: text/event-stream
```

- A single SSE broadcasts progress and final states of **all jobs**, events carry `job_id`; the browser uses only 1 connection (avoids per-host concurrent connection limits). The old per-job `/api/jobs/{id}/stream` is kept for compatibility, no longer used by the new frontend
- On connection established → immediately push the full current snapshot (including historical final states), thereafter incremental pushes throttled every 0.5s (change detection by `status/phase/percent/speed/eta` snapshot comparison)
- Events: `progress` (non-final snapshot), `status` (final state: done/failed/canceled, pushed once per connection)
- **Fallback**: the floating panel `EventSource.onerror` → switch to 2s **full** polling of `GET /api/jobs`; stop polling after SSE recovers (`open`)

```
Floating panel EventSource ──▶ backend /stream ──▶ job state table (in-memory)
                                                          ▲
              downloader thread progress_hooks ───────────┘
```

## 2. Interrupted Download Resume

### 2.1 `.part` staging directory (rather than the download directory / /tmp)

| Location | Conclusion |
|------|------|
| `/tmp` | ❌ Often tmpfs, cleared on restart; `restart clears breakpoint files`, directly negates resume |
| download directory | ✋ Allowed but not recommended: `.part` progress fragments dirty the directory; if the directory is synced by a cloud drive, partial files may be uploaded by mistake |
| **`staging_dir` (this solution)** | ✅ Independent, persistent disk directory, default `data/.parts` |

yt-dlp natively supports a separate staging path, **without changing the final file location** (note yt-dlp only recognizes `home`/`temp`; `incomplete` is an invalid type):

```
--paths "temp:{staging_dir}"
```

- `{staging_dir}` comes from config, default `<project>/data/.parts`
- After completion, yt-dlp automatically renames the artifact into the output directory and deletes the `.part`
- `staging_dir` and `downloads/` must both be writable in different scenarios (same-disk best performance; cross-disk move also works)

### 2.2 Resume-capable yt-dlp library params (output of the job creation function)

```python
yt_dlp.YoutubeDL({
    "format": quality_to_format(quality, codec),      # 8K/4K/2K/1080P60/…/any NNNP
    "outtmpl": "{subdir/}{file_template}",
    "paths": {"home": download_dir, "temp": staging_dir},   # temp=staging_dir writes .part here
    "merge_output_format": "mp4",
    "continue": True,
    "retries": float("inf"),
    "fragment_retries": float("inf"),
    "file_access_retries": float("inf"),
    "overwrites": overwrite,
    "http_headers": {"Referer": "https://www.bilibili.com/"},
    "progress_hooks": [...], "postprocessor_hooks": [...],
    "cookiefile": cookie_file,        # when cookie present
    "proxy": proxy,                   # when proxy present
    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],  # audio-only tier
}).extract_info(url, download=True)
```

Key points:
- `continue` + fixed naming (`[%(id)s] %(title)s.%(ext)s`, id prefix unchanged) → after interruption, re-run finds the `.part` to resume
- **Referer header is required** (Bilibili merge validation)
- Cookie goes via `cookiefile` (Netscape persistent file); putting Cookie in `http_headers` is not recognized as login state, quality capped at 1080P
- Audio-only tier: `audio_only=true` → `postprocessors` FFmpegExtractAudio (or keep m4a, see config)
- Note `outtmpl` must be a relative path: an absolute template makes yt-dlp ignore `paths`, and the `.part` lands in the wrong directory

### 2.3 Backend interruption recovery flow

```
start uvicorn
  └─ db.py scan_jobs(): status ∈ {downloading,merging,paused,queued} and process not present
       → mark all as interrupted (write DB)
  └─ floating panel "job list" refresh: interrupted rows show "Resume download"
      → POST /api/jobs/{id}/resume_after_interrupt (re-run with original params, resume .part)
      → immediately jump back to breakpoint progress (.part size = progress start point)
```

- Power loss during merge: audio/video stream `.part` already complete → re-run the yt-dlp library directly re-merges `*.mp4.temp` to done
- Collection interruption: completed parts are already marked done; any other interrupted part can be submitted, mutually non-blocking
- `.part` corrupt/failed validation: yt-dlp library throws an error → job marked failed → manual "retry" (delete that `.part` then re-download)

## 4. Fault Self-Healing Strategy

| Fault | Layer | Self-healing |
|------|------|------|
| Transient network jitter | yt-dlp library `retries/fragment_retries/file_access_retries = inf` | auto retry |
| yt-dlp version too low (Bilibili 412 risk control) | info stage | prompt to upgrade (`uv add yt-dlp@latest`) |
| Backend restart | SQLite scan → interrupted | one-click resume in the floating panel |
| Cookie expired | -4 | clear error message to refresh the page |

## 5. Related State Machine

```
queued → downloading → merging → done
           │                   └→ failed (non-zero process exit/exception)
           ├→ paused
           ├→ interrupted (startup scan / manual termination)
           └→ canceled
```

| State | Executable operations |
|------|-----------|
| queued/downloading/merging | pause / cancel |
| paused | resume / cancel |
| interrupted / failed / canceled | resume_after_interrupt (resume; manual resume after canceled) / delete |
| done | delete / re-download (new job) |
