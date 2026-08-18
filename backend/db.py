import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobDB:
    """SQLite job persistence. Cookies are never stored."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                bvid TEXT NOT NULL,
                page INTEGER DEFAULT 1,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                quality TEXT NOT NULL,
                params_json TEXT,
                out_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )
        self._conn.commit()

    def insert(self, job: dict) -> None:
        self._conn.execute(
            """INSERT INTO jobs
               (id,url,bvid,page,title,status,quality,params_json,out_path,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                job["id"], job["url"], job["bvid"], job["page"], job["title"],
                job["status"], job["quality"], json.dumps(job.get("params", {})),
                job.get("out_path"), job["created_at"],
            ),
        )
        self._conn.commit()

    def get(self, job_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list_jobs(self, limit: int = 50, status: str | None = None) -> list[dict]:
        if status and status != "all":
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def update_status(self, job_id: str, status: str, **fields) -> None:
        sets = ["status=?"]
        values: list = [status]
        for k, v in fields.items():
            sets.append(f"{k}=?")
            values.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
        values.append(job_id)
        self._conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", values)
        self._conn.commit()

    def mark_done(self, job_id: str, out_path: str) -> None:
        self.update_status(job_id, "done", out_path=out_path, finished_at=utcnow())

    def mark_failed(self, job_id: str, error: str) -> None:
        self.update_status(job_id, "failed", error=error, finished_at=utcnow())

    def delete(self, job_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def scan_interrupted(self, active_ids: set[str]) -> list[str]:
        """Startup recovery: non-terminal jobs with no live process → interrupted."""
        pending = self._conn.execute(
            "SELECT id FROM jobs WHERE status IN ('queued','downloading','merging','paused')"
        ).fetchall()
        ids = []
        for (job_id,) in pending:
            if job_id not in active_ids:
                self.update_status(job_id, "interrupted", error="background interrupted (.part kept for resume)")
                ids.append(job_id)
        return ids

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["params"] = json.loads(d.pop("params_json") or "{}")
        return d