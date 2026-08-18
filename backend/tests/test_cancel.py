import asyncio

from backend.config import Settings
from backend.db import JobDB
from backend.downloader import DownloadManager


def make_manager(tmp_path):
    settings = Settings(tmp_path / "nonexistent.toml")
    db = JobDB(str(tmp_path / "jobs-test.db"))
    return DownloadManager(settings, db)


class TestCancelQueued:
    async def test_canceled_queued_job_not_run(self, tmp_path):
        m = make_manager(tmp_path)
        job = m.create_job("https://www.bilibili.com/video/BV1xx", "BV1xx", 1, "T", "auto", {})
        m.enqueue(job.id)
        m.cancel_job(job.id)
        assert m.states[job.id].status == "canceled"

        ran = []

        async def fake_run(state):
            ran.append(state.id)

        m._run = fake_run
        worker = asyncio.get_event_loop().create_task(m._worker())
        await asyncio.sleep(0.05)
        worker.cancel()
        assert ran == []

    async def test_queued_job_runs_when_not_canceled(self, tmp_path):
        m = make_manager(tmp_path)
        job = m.create_job("https://www.bilibili.com/video/BV1xx", "BV1xx", 1, "T", "auto", {})
        m.enqueue(job.id)

        ran = []

        async def fake_run(state):
            ran.append(state.id)

        m._run = fake_run
        worker = asyncio.get_event_loop().create_task(m._worker())
        await asyncio.sleep(0.05)
        worker.cancel()
        assert ran == [job.id]

    def test_cancel_queued_sets_terminal_status(self, tmp_path):
        m = make_manager(tmp_path)
        job = m.create_job("https://www.bilibili.com/video/BV1xx", "BV1xx", 1, "T", "auto", {})
        res = m.cancel_job(job.id)
        assert res["status"] == "canceled"
        assert m.states[job.id].status == "canceled"

    def test_cancel_missing_job(self, tmp_path):
        m = make_manager(tmp_path)
        assert m.cancel_job("nope") is None