---
id: sec_001
title: Three-key cookie policy, never in the DB or git
importance: high
tags: security, cookie, privacy
---
Only the three keys (SESSDATA/DedeUserID/bili_jct) are submitted with `/api/info` and `/api/download`, written to the persistent `data/cookies.txt` (yt-dlp `cookiefile`), overwritten on every receipt. Logs are redacted, cookies never enter SQLite or git. See docs/design.md and docs/config.md.