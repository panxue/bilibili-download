---
id: arch_001
title: yt-dlp engine: Python library, not a subprocess
importance: high
tags: engine, yt-dlp, downloader
---
The download engine uses the `yt_dlp.YoutubeDL` library (`uv add yt-dlp`, version governed by uv.lock), not a PATH bin subprocess. Progress comes from structured `progress_hooks` callbacks (percent/speed/eta/phase); cancel uses a `threading.Event` + the progress_hook raising `DownloadCancelled` (no SIGTERM). See docs/iterations/0.5.3.md.