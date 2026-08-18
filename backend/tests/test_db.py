import json

from backend.config import Settings
from backend.db import JobDB, utcnow
from backend.downloader import DownloadManager


def make_db(tmp_path):
    return JobDB(str(tmp_path / "jobs.db"))


def make_manager(tmp_path):
    settings = Settings(tmp_path / "nonexistent.toml")
    db = JobDB(str(tmp_path / "jobs-test.db"))
    return DownloadManager(settings, db)


def base_job():
    return {
        "id": "j1", "url": "https://www.bilibili.com/video/BV1xx",
        "bvid": "BV1xx", "page": 1, "title": "P1", "status": "queued",
        "quality": "auto", "params": {}, "out_path": None, "created_at": utcnow(),
    }


class TestDB:
    def test_insert_and_get(self, tmp_path):
        db = make_db(tmp_path)
        db.insert(base_job())
        row = db.get("j1")
        assert row["id"] == "j1"
        assert row["status"] == "queued"
        assert db.get("missing") is None

    def test_list_jobs_desc_order(self, tmp_path):
        db = make_db(tmp_path)
        for i in range(3):
            j = base_job()
            j["id"] = f"j{i}"
            j["created_at"] = f"2026-08-09T0{i + 1}:00:00+00:00"
            db.insert(j)
        rows = db.list_jobs(limit=10)
        assert [r["id"] for r in rows] == ["j2", "j1", "j0"]

    def test_status_filter(self, tmp_path):
        db = make_db(tmp_path)
        j = base_job()
        db.insert(j)
        db.update_status("j1", "done")
        assert db.list_jobs(limit=10, status="done")[0]["id"] == "j1"
        assert db.list_jobs(limit=10, status="queued") == []

    def test_update_status_with_fields(self, tmp_path):
        db = make_db(tmp_path)
        db.insert(base_job())
        db.update_status("j1", "failed", error="boom", params_json=json.dumps({"a": 1}))
        row = db.get("j1")
        assert row["status"] == "failed"
        assert row["error"] == "boom"
        assert row["params"] == {"a": 1}

    def test_delete(self, tmp_path):
        db = make_db(tmp_path)
        db.insert(base_job())
        assert db.delete("j1") is True
        assert db.delete("j1") is False

    def test_scan_interrupted_marks_and_excludes_active(self, tmp_path):
        db = make_db(tmp_path)
        for i, status in enumerate(["queued", "downloading", "done", "failed"]):
            j = base_job()
            j["id"] = f"j{i}"
            j["status"] = status
            db.insert(j)
        ids = db.scan_interrupted(active_ids={"j1"})
        # j0 (queued) is not active → interrupted; j1 (downloading) is active → skipped; done/failed are not pending → untouched
        assert sorted(ids) == ["j0"]
        assert db.get("j0")["status"] == "interrupted"
        assert db.get("j1")["status"] == "downloading"
        assert db.get("j2")["status"] == "done"
        assert db.get("j3")["status"] == "failed"


class TestCreateJob:
    def test_cookies_never_persisted(self, tmp_path):
        m = make_manager(tmp_path)
        job = m.create_job(
            url="https://www.bilibili.com/video/BV1xx", bvid="BV1xx", page=1,
            title="P1", quality="auto",
            params={"cookies": "SESSDATA=secret", "codec": "avc", "overwrite": True},
        )
        row = m.db.get(job.id)
        assert "cookies" not in row["params"]
        assert row["params"]["codec"] == "avc"
        assert row["params"]["overwrite"] is True
        assert "secret" not in __import__("json").dumps(row)

    def test_params_cookie_variant_filtered(self, tmp_path):
        m = make_manager(tmp_path)
        job = m.create_job(
            url="u", bvid="b", page=1, title="t", quality="auto",
            params={"cookies": "SESSDATA=x", "cookie_extra": "y"},
        )
        row = m.db.get(job.id)
        assert "cookies" not in row["params"]
        assert "cookie_extra" not in row["params"]