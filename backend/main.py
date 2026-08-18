import asyncio
import json
import logging
import urllib.request
from contextlib import asynccontextmanager

import anyio
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .db import JobDB
from .downloader import TERMINAL, DownloadManager, probe_info
from .urls import is_bilibili_url, with_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("bilibili.main")

settings = Settings()
settings.ensure_dirs()
db = JobDB(settings.db_path)
manager = DownloadManager(settings, db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.start()
    yield
    for task in manager._workers:
        task.cancel()


app = FastAPI(title="bilibili-download", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    # Unified error shape: code = -http status (401 special-cased to -401), msg for frontend display
    code = -401 if exc.status_code == 401 else -exc.status_code
    return JSONResponse(status_code=exc.status_code,
                        content={"code": code, "msg": str(exc.detail)})


def _check_auth(request: Request) -> None:
    token = settings.server.get("auth_token", "")
    if token and request.headers.get("X-Auth-Token") != token:
        raise HTTPException(status_code=401, detail="authentication failed")


class InfoBody(BaseModel):
    url: str
    cookies: str = ""


class DownloadBody(BaseModel):
    url: str
    pages: list[int] = Field(default_factory=lambda: [1])
    quality: str = "auto"
    codec: str = "auto"
    audio_only: bool = False
    cookies: str = ""
    overwrite: bool = False
    title: str = ""


class ResumeBody(BaseModel):
    cookies: str = ""


@app.get("/api/health")
async def health():
    return {"code": 0, "data": {
        "ok": True,
        "version": "1.0.0",
        "yt_dlp": _ytdlp_version(),
        "ffmpeg": _ffmpeg_ok(),
        "max_concurrent": settings.download["max_concurrent"],
    }}


def _ytdlp_version() -> str:
    try:
        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return ""


def _ffmpeg_ok() -> bool:
    import shutil

    return shutil.which(settings.download.get("ffmpeg_path", "ffmpeg")) is not None


def _nav_is_login(cookies: str) -> bool:
    """Validate the cookie via bilibili /x/web-interface/nav. On network errors treat as valid (don't break anonymous downloads)."""
    cookies = (cookies or "").strip()
    if not cookies:
        return True
    req = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"Cookie": cookies, "User-Agent": "Mozilla/5.0 bilibili-download"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        return bool(data.get("data", {}).get("isLogin"))
    except Exception:  # noqa: BLE001
        logger.debug("nav cookie check failed, treat as valid")
        return True


def _check_cookies(cookies: str) -> dict | None:
    """Return an error response if the cookie is invalid, otherwise None."""
    if (cookies or "").strip() and not _nav_is_login(cookies):
        return {"code": -3, "msg": "cookie invalid or expired, please re-login to Bilibili and retry"}
    return None


@app.post("/api/info")
async def api_info(body: InfoBody, request: Request):
    _check_auth(request)
    if not is_bilibili_url(body.url):
        return {"code": -1, "msg": "only bilibili video page URLs are supported"}
    err = await anyio.to_thread.run_sync(_check_cookies, body.cookies or "")
    if err:
        return err
    try:
        info = await anyio.to_thread.run_sync(probe_info, settings, body.url, body.cookies or "")
    except Exception as e:  # noqa: BLE001
        logger.warning("info failed: %s", str(e)[:300])
        return {"code": -2, "msg": f"parse failed: {str(e)[:200]}"}
    return {"code": 0, "data": info}


@app.post("/api/download")
async def api_download(body: DownloadBody, request: Request):
    _check_auth(request)
    if not is_bilibili_url(body.url):
        return {"code": -1, "msg": "only bilibili video page URLs are supported"}
    err = await anyio.to_thread.run_sync(_check_cookies, body.cookies or "")
    if err:
        return err
    quality = body.quality
    if body.audio_only or quality == "audio":
        quality = "audio"

    jobs = []
    base_title = (body.title or "").strip()
    for page in body.pages or [1]:
        url = with_page(body.url, page)
        params = {"cookies": body.cookies or "", "overwrite": body.overwrite,
                   "codec": (body.codec or "auto").strip() or "auto"}
        title = f"{base_title} P{page}" if base_title else f"P{page}"
        job = manager.create_job(url=url, bvid=body.url.rsplit("/", 1)[-1].split("?")[0],
                                 page=page, title=title, quality=quality, params=params)
        manager.enqueue(job.id)
        jobs.append(manager.to_api(job))
    return {"code": 0, "data": {"jobs": jobs}}


@app.get("/api/jobs")
async def api_jobs(request: Request, limit: int = 50, status: str = "all"):
    _check_auth(request)
    rows = db.list_jobs(limit=min(limit, 200), status=status)
    jobs = [manager.to_api(manager.states.get(r["id"]), r) or r for r in rows]
    return {"code": 0, "data": {"total": len(jobs), "jobs": jobs}}


@app.get("/api/jobs/stream")
async def api_stream_all(request: Request):
    """Global job event stream: a single SSE broadcasts progress and terminal states for all jobs, replacing one SSE per job.

    Event names match the per-job stream but avoid 'error' (that is the EventSource network-layer event name):
      - event: progress  -> {id, status, phase, progress:{percent,speed,eta}}
      - event: status    -> {id, status, out_path, error} (terminal: done/failed/canceled)
    """
    _check_auth(request)
    return StreamingResponse(_sse_all(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _sse_all() -> None:
    """Scan manager.states every 500ms and broadcast incremental changes keyed by (status, phase, percent, speed, eta).

    The first scan of a connection pushes all current jobs as initial sync; terminal jobs are pushed once per connection.
    Compared to one SSE per job, the browser holds exactly one connection and never hits the 6-connection-per-host limit.
    """
    seen_terminal: set[str] = set()
    last_snap: dict[str, str] = {}
    while True:
        for job_id, st in list(manager.states.items()):
            status = st.status
            if status in TERMINAL:
                if job_id in seen_terminal:
                    continue
                seen_terminal.add(job_id)
                payload = {"id": job_id, "status": status,
                           "out_path": st.out_path or "", "error": st.error or None}
                yield f"event: status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                continue
            snap = "|".join((status, st.phase or "", str(st.percent), st.speed or "", st.eta or ""))
            if last_snap.get(job_id) == snap:
                continue
            last_snap[job_id] = snap
            payload = {"id": job_id, "status": status, "phase": st.phase or "",
                       "progress": {"percent": st.percent, "speed": st.speed or "", "eta": st.eta or ""}}
            yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        try:
            await asyncio.wait_for(asyncio.Event().wait(), timeout=0.5)
        except TimeoutError:
            pass


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str, request: Request):
    _check_auth(request)
    state = manager.states.get(job_id)
    row = db.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return {"code": 0, "data": manager.to_api(state, row)}


@app.get("/api/jobs/{job_id}/stream")
async def api_stream(job_id: str, request: Request):
    _check_auth(request)
    if not db.get(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return StreamingResponse(_sse(job_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _sse(job_id: str):
    state = manager.states.get(job_id)
    sent_terminal = False
    while True:
        st = state or (db.get(job_id) or {})
        status = getattr(st, "status", None) or (st.get("status") if isinstance(st, dict) else None)
        if status in {"done", "failed", "canceled"} and not sent_terminal:
            kind = "error" if status == "failed" else "done"
            out_path = getattr(st, "out_path", "") if not isinstance(st, dict) else (st.get("out_path") or "")
            error = getattr(st, "error", "") if not isinstance(st, dict) else (st.get("error") or "")
            payload = {"id": job_id, "status": status, "out_path": out_path or "", "error": error or None}
            yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            sent_terminal = True
            break
        if status not in {"done", "failed", "canceled"}:
            obj = manager.to_api(state, None) if state else None
            if obj:
                payload = {"id": obj["id"], "status": obj["status"], "progress": obj["progress"],
                           "phase": obj["phase"]}
                yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        try:
            await asyncio.wait_for(asyncio.Event().wait(), timeout=0.5)
        except TimeoutError:
            pass


def _handle(job_id: str, op: str):
    fn = {"pause": manager.pause_job, "resume": manager.resume_job,
          "cancel": manager.cancel_job, "resume_after_interrupt": manager.resume_interrupted}.get(op)
    if not fn:
        raise HTTPException(status_code=404, detail="unknown operation")
    res = fn(job_id)
    if not res:
        raise HTTPException(status_code=409, detail="job status does not support this operation")
    return {"code": 0, "data": res}


@app.post("/api/jobs/{job_id}/pause")
async def pause(job_id: str, _: Request):
    return _handle(job_id, "pause")


@app.post("/api/jobs/{job_id}/resume")
async def resume(job_id: str, _: Request):
    return _handle(job_id, "resume")


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str, _: Request):
    return _handle(job_id, "cancel")


@app.post("/api/jobs/{job_id}/resume_after_interrupt")
async def resume_interrupted(job_id: str, body: ResumeBody | None = None, _: Request = None):
    if body is not None and (body.cookies or "").strip():
        err = await anyio.to_thread.run_sync(_check_cookies, body.cookies or "")
        if err:
            return err
    state = manager.states.get(job_id)
    if state and body is not None and body.cookies:
        state.params["cookies"] = body.cookies
    return _handle(job_id, "resume_after_interrupt")


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, _: Request):
    _check_auth(_)
    res = manager.delete_job(job_id)
    if res == "missing":
        raise HTTPException(status_code=404, detail="job not found")
    if res == "busy":
        raise HTTPException(status_code=409, detail="job is downloading or queued, cannot delete")
    return {"code": 0, "data": {"id": job_id}}


@app.get("/api/config")
async def api_config(_: Request):
    return {"code": 0, "data": {
        "download_dir": settings.download_dir,
        "staging_dir": settings.staging_dir,
        "max_concurrent": settings.download["max_concurrent"],
        "file_template": settings.download["file_template"],
        "subdir_by_uploader": settings.download["subdir_by_uploader"],
        "proxy": settings.network.get("proxy", ""),
        "auth_token_required": bool(settings.server.get("auth_token", "")),
        "yt_dlp_version": _ytdlp_version(),
    }}