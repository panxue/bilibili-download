---
id: ops_001
title: Interrupted-download resume: .part goes through staging_dir
importance: high
tags: resume, staging, continuation
---
`.part` is managed by the yt-dlp library `paths: {"home": ..., "temp": staging_dir}` (only home/temp are accepted; incomplete is invalid), `outtmpl` must be a relative path, and staging_dir must not be `/tmp` — it lives on a persistent disk at `data/.parts/`. An interruption sets the SQLite job to `interrupted`, and re-running with the same params hits the resume path. See docs/state-lifecycle.md.