import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError, format_bytes, formatSeconds

from .config import Settings
from .db import JobDB, utcnow
from .urls import is_bangumi_season, is_bangumi_url

logger = logging.getLogger("bilibili.downloader")


def write_cookies_file(cookie: str, path: str) -> None:
    """Overwrite a "K1=V1; K2=V2" string into a Netscape cookies.txt.

    Must be passed via the library cookiefile parameter, not http_headers, otherwise yt-dlp's
    bilibili extractor cannot detect is_logged_in=True and high tiers like 8K/4K stay unavailable.
    The file is persistent (data/cookies.txt), overwritten on every cookie received; no temp files are created.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for part in cookie.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if not name or not value:
                continue
            # all three bilibili keys belong to .bilibili.com; Netscape format has 7 columns
            f.write(f".bilibili.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

# quality → max height; None means unlimited (auto)
QUALITY_HEIGHT = {
    "auto": None,
    "8K": 4320,
    "4K": 2160,
    "2K": 1440,
    "1080P60": 1080,
    "1080P": 1080,
    "720P60": 720,
    "720P": 720,
    "480P": 480,
    "360P": 360,
}

# codec preference order, expressed as literal yt-dlp vcodec prefixes (no family aliasing):
# HEVC first (hev1/hvc1, whichever spelling a stream reports), then av01 (AV1), then avc1 (H.264).
# the frontend settings panel may override the order; format: comma-separated prefixes, e.g. "avc1,hev1,hvc1"
CODEC_PRIORITY_ORDER = ["hev1", "hvc1", "av01", "avc1"]


def normalize_codec_order(codec: str) -> list[str]:
    """Normalize a requested codec preference ("auto" or comma-separated vcodec prefixes) into an ordered prefix list.

    - "auto"/empty → default order (hev1 > hvc1 > av01 > avc1)
    - explicit list → dedupe in the given order, append any prefixes not mentioned to the end
    """
    if not codec or codec.strip().lower() in ("", "auto"):
        return list(CODEC_PRIORITY_ORDER)
    wanted = []
    for item in (codec or "").replace(" ", "").split(","):
        prefix = item.lower()
        if prefix in CODEC_PRIORITY_ORDER and prefix not in wanted:
            wanted.append(prefix)
    if not wanted:
        return list(CODEC_PRIORITY_ORDER)
    wanted.extend(c for c in CODEC_PRIORITY_ORDER if c not in wanted)
    return wanted


def codec_family(vcodec: str) -> str:
    """The literal first segment of the yt-dlp vcodec: hvc1.1.6.L150.90 → hvc1; hev1.1.6 → hev1."""
    fam = (vcodec or "").split(".", 1)[0].lower()
    return fam or "unknown"


def codec_rank(family: str) -> int:
    if family in CODEC_PRIORITY_ORDER:
        return CODEC_PRIORITY_ORDER.index(family)
    return 99


def _codec_preferred(height: int | None, codec: str = "auto") -> str:
    """Build a -f expression with codec preference + height cap (auto = no height limit / default order)."""
    cond = f"[height<={height}]" if height else ""
    alts = [f"bestvideo{cond}[vcodec*={c}]+bestaudio" for c in normalize_codec_order(codec)]
    alts.append(f"bestvideo{cond}+bestaudio")
    alts.append("best")
    return "/".join(alts)


def _single_fallback(height: int | None, family: str) -> str:
    """The exact match for one vcodec prefix: bestvideo[height<=H][vcodec*=fam]+bestaudio.

    Used when caching fallback expressions per format_id (the bind already resolved the family, so
    only that one codec is the "same parameters" guarantee; the download chain appends /best after).
    """
    cond = f"[height<={height}]" if height else ""
    return f"bestvideo{cond}[vcodec*={family}]+bestaudio"


def quality_to_format(quality: str, codec: str = "auto") -> str:
    """Map a quality label to a yt-dlp -f expression; codec preference defaults to hev1>hvc1>av01>avc1, overridable per request.

    Supports: auto/8K/4K/2K/1080P60/1080P/720P60/720P/480P/360P/audio/any NNN P.
    Returns a format string (empty codec / auto uses the default).
    """
    if quality == "audio":
        return "bestaudio"
    height = QUALITY_HEIGHT.get(quality)
    if height is not None:
        return _codec_preferred(height, codec)
    m = re.match(r"^(\d{3,4})P$", quality)
    if m:
        return _codec_preferred(int(m.group(1)), codec)
    return _codec_preferred(None, codec)

TERMINAL = {"done", "failed", "canceled"}

# format_id → fallback -f expression (built from the same yt-dlp format object that yielded the id,
# i.e. its height + codec family). Bilibili format_ids are stable per (qn, codec) across a season,
# but individual episodes can differ (e.g. a hev1 1080P id swapped on one ep) — the /-fallback keeps
# batch downloads working when an id goes missing. Keyed by format_id, conflicts keep the latest probe.
_FORMAT_TABLE: dict[str, str] = {}


def bind_qualities(qualities: list[dict], codec: str = "auto") -> list[dict]:
    """Pick the concrete format_id of each quality tier per the user's codec preference.

    The frontend is display-only: binding the format_id (and recording its height+codec fallback in
    _FORMAT_TABLE) is backend logic. Each entry becomes {qn, label, format_id, codec, size}.
    """
    order = normalize_codec_order(codec)
    out = []
    for q in qualities:
        families = q.get("format_ids") or {}
        fam = next((c for c in order if families.get(c)), None)
        fid = families.get(fam) or "" if fam else ""
        if fid:
            _FORMAT_TABLE[fid] = _single_fallback(q.get("height"), fam or "auto")
        out.append({"qn": q.get("qn"), "label": q.get("label"),
                    "format_id": fid, "codec": fam or "",
                    "size": q.get("size", "")})
    return out


def _fmt_speed(speed) -> str:
    """progress hook speed (float B/s) → display string (e.g. "23.69MiB/s")."""
    return f"{format_bytes(speed)}/s" if speed else ""


def _fmt_eta(eta) -> str:
    """progress hook eta (seconds) → display string (e.g. "00:12")."""
    return f"{formatSeconds(eta):>5s}" if eta else ""


@dataclass
class JobState:
    id: str
    url: str
    bvid: str
    page: int
    title: str
    quality: str
    params: dict
    status: str = "queued"
    phase: str = "waiting"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    out_path: str = ""
    error: str = ""
    cancel_event: threading.Event | None = None
    created_at: str = field(default_factory=lambda: utcnow())


def _download_format(state: JobState) -> str:
    """Resolve the yt-dlp -f expression for a job.

    Priority:
      1. explicit format_id from the probe-time binding: "{id}+bestaudio" with a /-fallback to the
         height+codec chain (and finally "best") for episodes lacking that exact id
      2. audio-only request → bestaudio
      3. fall back to the legacy height-based mapping (auto / NNN P / audio)
    """
    fid = (state.params.get("format_id") or "").strip()
    if fid and state.quality != "audio":
        fb = (state.params.get("format_fallback") or "").strip() or "best"
        return f"{fid}+bestaudio/best" if fb == "best" else f"{fid}+bestaudio/{fb}/best"
    return quality_to_format(state.quality, (state.params.get("codec") or ""))


class DownloadManager:
    def __init__(self, settings: Settings, db: JobDB):
        self.settings = settings
        self.db = db
        self.states: dict[str, JobState] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        n = self.settings.download["max_concurrent"]
        self._workers = [asyncio.create_task(self._worker()) for _ in range(max(1, n))]
        for job_id in self.db.scan_interrupted(set(self.states)):
            state = self.db.get(job_id)
            if state:
                self._load_state(state)
                self.states[job_id].status = "interrupted"

    def _load_state(self, row: dict) -> None:
        self.states[row["id"]] = JobState(
            id=row["id"], url=row["url"], bvid=row["bvid"], page=row["page"],
            title=row["title"], quality=row["quality"],
            params=row.get("params", {}), status=row["status"],
            created_at=row["created_at"],
        )

    def create_job(self, url: str, bvid: str, page: int, title: str,
                   quality: str, params: dict) -> JobState:
        job = JobState(
            id=uuid4().hex, url=url, bvid=bvid, page=page,
            title=title, quality=quality, params=params,
        )
        self.states[job.id] = job
        db_params = {k: v for k, v in params.items() if k != "cookies" and not k.startswith("cookie_")}
        self.db.insert({
            "id": job.id, "url": job.url, "bvid": job.bvid, "page": job.page,
            "title": job.title, "status": "queued", "quality": job.quality,
            "params": db_params, "created_at": job.created_at,
        })
        return job

    def enqueue(self, job_id: str) -> None:
        self._queue.put_nowait(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            state = self.states.get(job_id)
            # a job canceled while queued: already terminal, skip it on dequeue without starting the download
            if state and state.cancel_event is None and state.status not in TERMINAL:
                await self._run(state)
            self._queue.task_done()

    async def _run(self, state: JobState) -> None:
        self._set(state, "downloading", phase="downloading")
        self.db.update_status(state.id, "downloading")
        cancel = threading.Event()
        state.cancel_event = cancel
        params = self._build_params(state)
        cookie = (state.params.get("cookies") or "").strip()
        logger.info("job %s start quality=%s cookiefile=%s",
                    state.id, state.quality, bool(cookie))
        try:
            await asyncio.to_thread(self._download, state, params, cancel)
        except DownloadCancelled:
            # user pause/cancel: the cancel signal raised in the hook; .part is kept
            pass
        except asyncio.CancelledError:
            cancel.set()  # notify the download thread to exit as soon as possible
            raise
        except Exception as e:  # noqa: BLE001
            self.db.mark_failed(state.id, str(e))
            self._set(state, "failed", error=str(e), phase="error")
            return
        finally:
            state.cancel_event = None

        out = state.out_path
        if state.status in TERMINAL:
            pass  # already terminalized by a control op (cancel); do not overwrite here
        elif state.status == "paused":
            pass  # user paused intentionally: keep the paused status
        elif out:
            self.db.mark_done(state.id, out)
            self._set(state, "done", phase="done", out_path=out, percent=100.0)
        else:
            msg = state.error or "yt-dlp produced no file"
            self.db.mark_failed(state.id, msg)
            self._set(state, "failed", error=msg, phase="error")

    def _download(self, state: JobState, params: dict, cancel: threading.Event) -> dict:
        """Run the yt-dlp library download in a dedicated thread; progress/pp hooks write back to state."""
        progress = self._progress_hook(state, cancel)
        postproc = self._postproc_hook(state)
        params["progress_hooks"] = [progress]
        params["postprocessor_hooks"] = [postproc]
        with yt_dlp.YoutubeDL(params) as ydl:
            info = ydl.extract_info(state.url, download=True)
        # final artifact path: after merge/transcode it is given by requested_downloads[0].filepath
        dl = (info.get("requested_downloads") or [{}])[0]
        fp = (dl or {}).get("filepath") or ""
        if fp:
            state.out_path = fp
        return info

    def _progress_hook(self, state: JobState, cancel: threading.Event):
        def hook(d: dict) -> None:
            if cancel.is_set():
                raise DownloadCancelled("user cancelled")
            if d.get("status") == "downloading" and state.status in ("downloading", "merging"):
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                pct = (done / total * 100.0) if total else state.percent
                self._set(state, state.status, percent=pct,
                          speed=_fmt_speed(d.get("speed")), eta=_fmt_eta(d.get("eta")))
        return hook

    def _postproc_hook(self, state: JobState):
        def hook(d: dict) -> None:
            # postprocessor_hooks delivers {status, info_dict, postprocessor}
            if d.get("status") == "started" and state.status in ("downloading", "merging"):
                self._set(state, "merging", phase="merging")
                self.db.update_status(state.id, "merging")
        return hook

    def _set(self, state: JobState, status: str, **kw) -> None:
        state.status = status
        for k, v in kw.items():
            setattr(state, k, v)

    def _build_params(self, state: JobState) -> dict:
        s = self.settings.download
        proxy = self.settings.network.get("proxy", "")
        tpl = s["file_template"]
        if s["subdir_by_uploader"]:
            if is_bangumi_url(state.url):
                # bangumi entries have no uploader ("na"); group by series + season instead
                tpl = f"%(series)s/%(season)s/{tpl}"
            else:
                tpl = f"%(uploader)s/{tpl}"

        params = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": _download_format(state),
            "outtmpl": tpl,
            "paths": {"home": self.settings.download_dir, "temp": self.settings.staging_dir},
            "merge_output_format": "mp4",
            "continue": True,
            "retries": float("inf"),
            "fragment_retries": float("inf"),
            "file_access_retries": float("inf"),
            "overwrites": bool(state.params.get("overwrite")),
            "http_headers": {"Referer": "https://www.bilibili.com/"},
        }
        if state.quality == "audio":
            params["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": s.get("audio_format", "mp3"),
            }]

        cookie = (state.params.get("cookies") or "").strip()
        if cookie:
            write_cookies_file(cookie, self.settings.cookie_file)
            params["cookiefile"] = self.settings.cookie_file
        if proxy:
            params["proxy"] = proxy
        return params

    def to_api(self, state: JobState | None, row: dict | None = None) -> dict | None:
        src = state or row
        if not src:
            return None

        def g(key: str, default=None):
            if isinstance(src, dict):
                return src.get(key, default)
            return getattr(src, key, default)

        quality_actual = state.quality if state else g("quality", "")
        if state:
            prog = {"percent": state.percent, "speed": state.speed, "eta": state.eta}
        else:
            status = g("status", "queued")
            # no in-memory state (historical jobs loaded from db after a backend restart): backfill 100% for done, avoid showing 0.0%
            prog = {"percent": 100.0 if status == "done" else 0.0, "speed": "", "eta": ""}
        return {
            "id": g("id"), "bvid": g("bvid", ""), "page": g("page", 1), "title": g("title", ""),
            "url": g("url", ""), "status": g("status", "queued"), "quality_requested": g("quality", ""),
            "quality_actual": quality_actual, "progress": prog,
            "phase": g("phase", "") or "", "out_path": g("out_path", "") or "",
            "error": g("error", None),
            "created_at": g("created_at", "") or "",
            "finished_at": g("finished_at", None),
        }

    # ---- Controls ----
    def pause_job(self, job_id: str) -> dict | None:
        state = self.states.get(job_id)
        if not state or state.status not in ("downloading", "merging"):
            return None
        if state.cancel_event:
            state.cancel_event.set()
        self.db.update_status(job_id, "paused")
        self._set(state, "paused")
        return self.to_api(state)

    def resume_job(self, job_id: str) -> dict | None:
        state = self.states.get(job_id)
        if not state or state.status != "paused":
            return None
        self.db.update_status(job_id, "downloading")
        self.enqueue(job_id)
        self._set(state, "queued", percent=state.percent)
        return self.to_api(state)

    def cancel_job(self, job_id: str) -> dict | None:
        state = self.states.get(job_id)
        if not state:
            return None
        if state.status in ("downloading", "merging"):
            if state.cancel_event:
                state.cancel_event.set()
        elif state.status == "queued":
            pass
        self.db.update_status(job_id, "canceled", finished_at=utcnow())
        self._set(state, "canceled")
        return self.to_api(state)

    def resume_interrupted(self, job_id: str) -> dict | None:
        state = self.states.get(job_id)
        if not state or state.status not in ("interrupted", "failed", "canceled"):
            return None
        self.db.update_status(job_id, "downloading")
        self._set(state, "downloading", phase="downloading", percent=0)
        self.enqueue(job_id)
        return self.to_api(state)

    def delete_job(self, job_id: str) -> str:
        """Delete a job record. Returns 'ok' / 'busy' (running or queued) / 'missing'."""
        state = self.states.get(job_id)
        if state and state.status in ("downloading", "merging", "queued"):
            return "busy"
        self.states.pop(job_id, None)
        return "ok" if self.db.delete(job_id) else "missing"


def probe_info(settings: Settings, url: str, cookies: str = "") -> dict:
    """Prefetch video info (including the quality list) via the yt_dlp library extract_info(download=False).

    Bangumi season URLs are special-cased: a flat probe lists the episodes in one request (fast,
    no per-episode format resolution), and only the currently displayed/first episode is fully
    resolved to build the shared quality list. Parsed results are cached for a few minutes so
    reopening the season page does not re-do the slow first probe.
    """
    cookie = (cookies or "").strip()
    logged_in = bool(cookie)
    cache_key = (url, logged_in)
    hit = _PROBE_CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < _PROBE_CACHE_TTL:
        return hit[1]

    params = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "http_headers": {"Referer": "https://www.bilibili.com/"},
    }
    if cookie:
        write_cookies_file(cookie, settings.cookie_file)
        params["cookiefile"] = settings.cookie_file
    if settings.network.get("proxy"):
        params["proxy"] = settings.network["proxy"]

    try:
        if is_bangumi_url(url):
            # both ss (season) and ep (episode) links belong to a bangumi series; list the whole
            # season so the panel can offer every episode, not just the currently-open one
            data = _probe_season_any(settings, url, params)
        else:
            with yt_dlp.YoutubeDL(params) as ydl:
                data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        raise RuntimeError(_clean_err(str(e))) from e

    info = parse_probe(data, url, logged_in)
    if len(_PROBE_CACHE) > 64:
        # crude cap: drop the oldest entry (dict preserves insertion order)
        _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)))
    _PROBE_CACHE[cache_key] = (time.monotonic(), info)
    return info


_PROBE_CACHE: dict[tuple[str, bool], tuple[float, dict]] = {}
_PROBE_CACHE_TTL = 600.0  # seconds; page reopen stays instant, stale quality lists are re-probed after 10 min


def _probe_season_any(settings: Settings, url: str, params: dict) -> dict:
    """Run the season probe for any bangumi URL.

    ss links are used directly; ep links are resolved to the parent season first (an ep page
    exposes the season_id), then the season probe lists every episode. Falls back to a plain
    single-video extraction if the season cannot be resolved.
    """
    if is_bangumi_season(url):
        return _probe_season(settings, url, params)
    with yt_dlp.YoutubeDL(params) as ydl:
        ep_data = ydl.extract_info(url, download=False)
    season_id = ep_data.get("season_id")
    if season_id:
        season_url = f"https://www.bilibili.com/bangumi/play/ss{season_id}"
        try:
            return _probe_season(settings, season_url, params)
        except DownloadError as e:
            logger.warning("season probe for %s failed, fall back to single episode: %s",
                           season_url, _clean_err(str(e))[:200])
    return ep_data


def _probe_season(settings: Settings, url: str, params: dict) -> dict:
    """Resolve a bangumi season into a playlist-like structure with per-episode URLs and a quality sample.

    Two probes: (1) a flat playlist extraction lists all episode ids in one pass; (2) the first
    episode is fully resolved to build the shared quality list. The episode titles and formats are
    not resolved individually — that is what made the naive season probe take ~20 s for 43 episodes.
    """
    flat = dict(params)
    flat["extract_flat"] = True
    with yt_dlp.YoutubeDL(flat) as ydl:
        root = ydl.extract_info(url, download=False)

    entries = [e for e in (root.get("entries") or []) if isinstance(e, dict)]
    # bilibili flat entries expose the ep id; the canonical ep URL is constructed from it
    for i, e in enumerate(entries):
        e.setdefault("webpage_url", f"https://www.bilibili.com/bangumi/play/ep{e.get('id')}")
        e.setdefault("title", f"EP {i + 1}")

    # resolve the first episode fully for a representative quality list
    sample = {}
    if entries:
        first = entries[0].get("webpage_url")
        if first:
            with yt_dlp.YoutubeDL(params) as ydl:
                try:
                    sample = ydl.extract_info(first, download=False)
                except DownloadError as e:
                    logger.warning("season sample probe failed: %s", _clean_err(str(e))[:200])
                    sample = {}
    root = dict(root)
    root["formats"] = sample.get("formats") or []
    return root


def _clean_err(msg: str) -> str:
    """Strip yt-dlp's "ERROR: ..." prefix and return a readable error."""
    msg = (msg or "").strip()
    for prefix in ("ERROR: ", "WARNING: "):
        msg = msg.removeprefix(prefix)
    return msg


def _probe_qualities(formats: list[dict]) -> tuple[list[dict], str]:
    """Group yt-dlp formats into a bilibili quality list + the auto (highest) label.

    No tiers are mapped by hand here. Each quality entry exposes:
      - label:   yt-dlp's own display name (e.g. "4K 超高清", "HDR 真彩")
      - format_ids: {vcodec prefix: format_id} — one concrete stream per codec, e.g. {"hev1": "100036"}
                   preference and sends it to the download endpoint (no height/codec math needed)
      - codecs / size: informational, for display only
    """
    videos = [f for f in formats if f.get("vcodec") and f.get("vcodec") != "none"]
    audios = [f for f in formats if f.get("acodec") and f.get("acodec") != "none"]
    groups: dict[int, list[dict]] = {}
    for f in videos:
        groups.setdefault(f.get("quality") or 0, []).append(f)

    # largest audio track (bilibili keeps audio separate; every video tier pairs with the same audio)
    audio_size = max((f.get("filesize") or f.get("filesize_approx") or 0) for f in audios) if audios else 0

    qualities = []
    for qn in sorted(groups, reverse=True):
        fs = groups[qn]
        height = max((f.get("height") or 0 for f in fs), default=0)
        labels = {f.get("format") for f in fs if f.get("format")}
        label = next(iter(labels), "") or (f"{height}P" if height else f"Q{qn}")
        codecs = sorted({codec_family(f.get("vcodec") or "") for f in fs}, key=codec_rank)
        format_ids = {codec_family(f.get("vcodec") or ""): f.get("format_id")
                      for f in fs if f.get("format_id")}
        sizes = [(f.get("filesize") or f.get("filesize_approx") or 0) for f in fs]
        total = (max(sizes, default=0) + audio_size) if sizes and audio_size else (max(sizes, default=0))
        qualities.append({"qn": qn, "label": label, "height": height, "codecs": codecs,
                          "format_ids": format_ids, "size": _fmt_size(total)})

    highest_qn = max(groups, default=0)
    auto = next((q["label"] for q in qualities if q["qn"] == highest_qn), "auto")
    return qualities, auto


def _fmt_size(n: float) -> str:
    """Human-readable file size (bilibili reports filesize_approx in bytes)."""
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return ""


def parse_probe(data: dict, url: str, logged_in: bool) -> dict:
    """Output the quality list grouped by bilibili quality code (qn) and the part list.

    Handles both a single video dict and a bangumi season playlist (`_type == "playlist"`), whose
    entries become the downloadable parts (one episode URL each). Quality for seasons is unioned
    across the resolved episode entries.
    """
    if data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        all_formats = list(data.get("formats") or [])
        for e in entries:
            all_formats.extend(e.get("formats") or [])
        qualities, auto = _probe_qualities(all_formats)
        first = entries[0] if entries else {}
        return {
            "bvid": data.get("id") or url.rsplit("/", 1)[-1].split("?")[0],
            "title": data.get("title") or url,
            "uploader": first.get("uploader") or "",
            "duration": sum(int(e.get("duration") or 0) for e in entries),
            "logged_in": logged_in, "vip_type": "none",
            "auto_resolution": auto, "available_qualities": qualities,
            "pages": [
                {"cid": e.get("id", 0), "page": i + 1,
                 "title": e.get("title") or f"EP{i + 1}",
                 "url": e.get("webpage_url") or url}
                for i, e in enumerate(entries)
            ],
        }

    qualities, auto = _probe_qualities(data.get("formats", []))
    return {
        "bvid": data.get("id") or "", "title": data.get("title") or url,
        "uploader": data.get("uploader") or "", "duration": int(data.get("duration") or 0),
        "logged_in": logged_in, "vip_type": "none",
        "auto_resolution": auto,
        "available_qualities": qualities,
        "pages": [
            {"cid": p.get("id", 0), "page": p.get("page", 1), "title": p.get("title", "")}
            for p in (data.get("pages") or [])
        ],
    }