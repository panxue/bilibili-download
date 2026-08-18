---
id: arch_002
title: Progress sync: SSE primary + polling fallback
importance: medium
tags: sse, progress, api
---
The backend broadcasts all jobs over a single global `/api/jobs/stream` SSE (avoiding the per-host concurrent connection cap) and falls back to a full `GET /api/jobs` poll on disconnect. Progress fields come structured from progress_hooks (percent/speed/eta/phase). See docs/api.md.