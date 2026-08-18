# 06 · Config Design

## 1. Config Ownership Overview

| Layer | Config content | Stored where | Priority |
|----|---------|------|:---:|
| ① Backend global | download dir / concurrency / template / proxy / token | `backend/config.toml` | low |
| ② Conditional override | the above can be overridden by env vars / CLI | env / startup command | medium |
| ③ Userscript side | backend URL/token/default quality/floating panel preferences | browser GM_setValue | high |
| ④ Per-job | tier / audio-only / overwrite | floating panel form submission | highest |

Actual resolution order: **④ > ③ > ② > ①**. ①② are server-side assets; ③④ belong to the browser session.

## 2. Backend Config File `backend/config.toml`

> Copied from `backend/config.example.toml`, not in git.

```toml
[server]
host = "127.0.0.1"          # local only; if changed to 0.0.0.0, auth_token is required
port = 8000
auth_token = ""             # empty=loopback only; non-empty means the userscript settings must match

[download]
dir = "./downloads"          # final output directory (relative to project root or absolute path)
staging_dir = "./data/.parts" # .part staging (must be persistent disk, do not use /tmp)
ffmpeg_path = "ffmpeg"
max_concurrent = 2           # number of concurrent download jobs
subdir_by_uploader = true    # subdirectory per uploader name
file_template = "[%(id)s] %(title)s.%(ext)s"  # fixed id prefix ensures resume can hit the same file
overwrite = false
audio_format = "mp3"         # output codec for the audio-only tier

[network]
proxy = ""                   # empty=direct connection; socks5://127.0.0.1:1080 example

[storage]
db_path = "./data/jobs.db"
cookie_file = "./data/cookies.txt"   # persistent Netscape cookies.txt (used by the yt-dlp library cookiefile; overwritten each time userscript cookies are received, not in git)
```

### Required/default notes

- `dir`, `staging_dir`, `db_path`, `cookie_file` support relative paths (relative to the process cwd, i.e. the project root)
- `staging_dir` must be on **persistent disk**, `/tmp` is forbidden (tmpfs is wiped on power loss, breaking resume) — see [state-lifecycle.md](state-lifecycle.md)
- `cookie_file` must be persistent (`cookiefile` is read continuously while yt-dlp runs); the path is in `.gitignore`
- `ffmpeg_path` is only used for the probe signal; the actual merge is still performed by the yt-dlp library internally via ffmpeg on PATH; this item is used for health-check validation
- `proxy` is passed through directly as the yt-dlp library `proxy` parameter; socks5 requires pysocks installed on the `uv`/yt-dlp side

## 3. Env Var / CLI Override (②)

| Env var | Overrides |
|----------|------|
| `BLDLP_HOST` / `BLDLP_PORT` | server.host/port |
| `BLDLP_TOKEN` | server.auth_token |
| `BLDLP_DOWNLOAD_DIR` | download.dir |
| `BLDLP_CONCURRENT` | download.max_concurrent |

CLI override example:
```bash
BLDLP_DOWNLOAD_DIR=/data/videos uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Override priority: CLI(env) > config.toml > built-in defaults.

Container env vars: compose passes the same-named `BLDLP_*` through `.env`; path-type ones (`BLDLP_DOWNLOAD_DIR`) point to in-container mount points (`/app/downloads`, `/app/data`). `auth_token` is injected only via `BLDLP_TOKEN`; do not hard-code it into the image/volumes.

## 4. Userscript-side Config (③, browser, GM_setValue)

| key | Default | Notes |
|-----|------|------|
| `backendUrl` | `http://127.0.0.1:8000` | editable in the settings panel |
| `authToken` | `""` | requests require it to match the backend |
| `defaultQuality` | `auto` | initial tier of the new-download form |
| `codecPref` | `auto` | codec preference order (comma-separated families, submitted with the download request) |

Userscript settings → `GM_setValue`; the panel saves on change and takes effect immediately.

## 5. Per-job Parameters (④)

| Parameter | Source | Notes |
|------|------|------|
| `url` / `pages[]` | page parsing | required |
| `quality` | form | auto\|8K\|4K\|2K\|1080P60\|1080P\|720P60\|720P\|480P\|360P\|audio |
| `codec` | settings panel (③) | codec preference order, submitted with the request |
| `audio_only` | form | linked to quality=audio |
| `cookies` | three-key string of the current page carried by the form | temporary, not persisted |
| `overwrite` | frontend fixed false (no option yet) | same-name files are not overwritten |

## 6. Sensitivity Notes

- `auth_token` and cookies never enter logs or the git repo; the token is only validated in the request header
- `authToken` in the userscript settings is browser-local storage; users should manage it themselves when switching machines
- `config.toml` is excluded via .gitignore; only `config.example.toml` is committed

## 7. Change Impact

| Changed item | Effective when | Impact |
|--------|---------|------|
| Directly edit config.toml | backend restart | all |
| Change staging_dir | restart | resume requires migrating `.part` together |
| Change file_template | restart | affects only new jobs (old jobs must be re-run with the same params) |
| Userscript UI change | refresh the script | browser side |
