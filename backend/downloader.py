import asyncio
import logging
import re
import threading
from dataclasses import dataclass, field
from uuid import uuid4

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError, format_bytes, formatSeconds

from .config import Settings
from .db import JobDB, utcnow

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

# codec preference: hvc (HEVC, incl. hvc1/hev1) > av01 (AV1) > avc (H.264)
# the frontend settings panel may override the order; format: comma-separated codec families, e.g. "hvc,av01,avc"
CODEC_PRIORITY_ORDER = ["hvc", "av01", "avc"]
CODEC_ALIASES = {"hev1": "hvc"}


def normalize_codec_order(codec: str) -> list[str]:
    """Normalize a requested codec preference ("auto" or "hvc,av01,avc") into an ordered family list.

    - "auto"/empty → default order (hvc > av01 > avc)
    - explicit list → dedupe in the given order, append any families not mentioned to the end
    """
    if not codec or codec.strip().lower() in ("", "auto"):
        return list(CODEC_PRIORITY_ORDER)
    wanted = []
    for item in (codec or "").replace(" ", "").split(","):
        fam = CODEC_ALIASES.get(item.lower(), item.lower())
        if fam in CODEC_PRIORITY_ORDER and fam not in wanted:
            wanted.append(fam)
    if not wanted:
        return list(CODEC_PRIORITY_ORDER)
    wanted.extend(c for c in CODEC_PRIORITY_ORDER if c not in wanted)
    return wanted


def codec_family(vcodec: str) -> str:
    """Normalize the first segment of vcodec: hvc1.1.6.L150.90 → hvc; hev1... → hvc."""
    fam = (vcodec or "").split(".", 1)[0].lower()
    fam = CODEC_ALIASES.get(fam, fam)
    for key in CODEC_PRIORITY_ORDER:
        if fam.startswith(key):
            return key
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


def quality_to_format(quality: str, codec: str = "auto") -> str:
    """Map a quality label to a yt-dlp -f expression; codec preference defaults to hvc>av01>avc, overridable per request.

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
            tpl = f"%(uploader)s/{tpl}"

        params = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": quality_to_format(state.quality, (state.params.get("codec") or "")),
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
    """Prefetch video info (including the quality list) via the yt_dlp library extract_info(download=False)."""
    params = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "http_headers": {"Referer": "https://www.bilibili.com/"},
    }
    cookie = (cookies or "").strip()
    if cookie:
        write_cookies_file(cookie, settings.cookie_file)
        params["cookiefile"] = settings.cookie_file
    if settings.network.get("proxy"):
        params["proxy"] = settings.network["proxy"]
    try:
        with yt_dlp.YoutubeDL(params) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        raise RuntimeError(_clean_err(str(e))) from e
    return parse_probe(data, url, bool(cookie))


def _clean_err(msg: str) -> str:
    """Strip yt-dlp's "ERROR: ..." prefix and return a readable error."""
    msg = (msg or "").strip()
    for prefix in ("ERROR: ", "WARNING: "):
        msg = msg.removeprefix(prefix)
    return msg


def parse_probe(data: dict, url: str, logged_in: bool) -> dict:
    """Output the quality list grouped by bilibili quality code (qn).

    yt-dlp's bilibili extractor reports fps as 30 for everything (no hfr field), and 1080P vs
    1080P high-frame-rate share the same height (1080), so they can only be told apart by quality (=qn):
      80→1080P, 112→1080P60, 116→1080P60, 74→720P60…
    codec is sorted by hvc>av01>avc preference.
    """
    height_labels = {360: "360P", 480: "480P", 720: "720P", 1080: "1080P", 1440: "2K", 2160: "4K", 4320: "8K"}
    # qn (bilibili quality code) → display label; high-frame-rate tiers (60fps) are separated from the regular ones
    qn_labels = {6: "240P", 16: "360P", 32: "480P", 64: "720P", 74: "720P60",
                 80: "1080P", 112: "1080P60", 116: "1080P60", 120: "4K", 127: "8K"}

    videos = [f for f in data.get("formats", [])
              if f.get("vcodec") and f.get("vcodec") != "none"]
    groups: dict[int, list[dict]] = {}
    for f in videos:
        groups.setdefault(f.get("quality") or 0, []).append(f)

    qualities = []
    for qn in sorted(groups, reverse=True):
        fs = groups[qn]
        height = max((f.get("height") or 0 for f in fs), default=0)
        label = qn_labels.get(qn) or height_labels.get(height, f"{height}P")
        codecs = sorted({codec_family(f.get("vcodec") or "") for f in fs}, key=codec_rank)
        qualities.append({"qn": qn, "label": label, "codecs": codecs})

    highest_qn = max(groups, default=0)
    auto = next((q["label"] for q in qualities if q["qn"] == highest_qn), "auto")
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