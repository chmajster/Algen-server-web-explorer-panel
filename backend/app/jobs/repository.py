from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..sqlite_utils import ClosingConnection
from .models import Job, JobPage, JobStatus


class JobRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    module TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    created_by TEXT NOT NULL,
                    progress INTEGER,
                    message TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    cancellable INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    parent_job_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_module_created ON jobs(module, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_type_created ON jobs(type, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_actor_created ON jobs(created_by, created_at DESC);
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=str(row["id"]),
            type=str(row["type"]),
            module=str(row["module"]),
            status=JobStatus(str(row["status"])),
            created_at=float(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_by=str(row["created_by"]),
            progress=row["progress"],
            message=str(row["message"] or ""),
            result=json.loads(row["result_json"] or "{}"),
            error=str(row["error"] or ""),
            metadata=json.loads(row["metadata_json"] or "{}"),
            retry_count=int(row["retry_count"] or 0),
            retryable=bool(row["retryable"]),
            cancellable=bool(row["cancellable"]),
            cancel_requested=bool(row["cancel_requested"]),
            parent_job_id=row["parent_job_id"],
        )

    def create(
        self,
        *,
        job_type: str,
        module: str,
        created_by: str,
        metadata: dict[str, Any] | None = None,
        retryable: bool = False,
        cancellable: bool = False,
        parent_job_id: str | None = None,
        retry_count: int = 0,
    ) -> Job:
        job_id = uuid4().hex
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs
                    (id,type,module,status,created_at,created_by,metadata_json,retryable,cancellable,parent_job_id,retry_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    job_type,
                    module,
                    JobStatus.queued.value,
                    now,
                    created_by,
                    json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                    int(retryable),
                    int(cancellable),
                    parent_job_id,
                    retry_count,
                ),
            )
        job = self.get(job_id)
        if job is None:
            raise RuntimeError("Job could not be read after creation")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def list(
        self,
        *,
        status: JobStatus | None = None,
        module: str | None = None,
        job_type: str | None = None,
        created_by: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> JobPage:
        clauses: list[str] = []
        params: list[Any] = []
        filters = (
            ("status", status.value if status else None),
            ("module", module),
            ("type", job_type),
            ("created_by", created_by),
        )
        for column, value in filters:
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        if since is not None:
            clauses.append("created_at>=?")
            params.append(since)
        if until is not None:
            clauses.append("created_at<=?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = min(max(limit, 1), 500)
        safe_offset = max(offset, 0)
        with self._connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0])  # nosec B608
            rows = connection.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",  # nosec B608
                [*params, safe_limit, safe_offset],
            ).fetchall()
        return JobPage(items=[self._job(row) for row in rows], total=total, limit=safe_limit, offset=safe_offset)

    def update(self, job_id: str, **values: Any) -> Job | None:
        allowed = {
            "status", "started_at", "finished_at", "progress", "message", "result", "error",
            "metadata", "retry_count", "retryable", "cancellable", "cancel_requested", "parent_job_id",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get(job_id)
        if isinstance(updates.get("status"), JobStatus):
            updates["status"] = updates["status"].value
        for name in ("result", "metadata"):
            if name in updates:
                updates[f"{name}_json"] = json.dumps(updates.pop(name), ensure_ascii=False, separators=(",", ":"))
        for name in ("retryable", "cancellable", "cancel_requested"):
            if name in updates:
                updates[name] = int(bool(updates[name]))
        columns = ", ".join(f"{column}=?" for column in updates)
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {columns} WHERE id=?", [*updates.values(), job_id])  # nosec B608
        return self.get(job_id)

    def mark_running(self, job_id: str) -> Job | None:
        return self.update(job_id, status=JobStatus.running, started_at=time.time(), message="Running")

    def mark_success(self, job_id: str, *, result: dict[str, Any] | None = None, message: str = "Completed") -> Job | None:
        return self.update(job_id, status=JobStatus.success, progress=100, finished_at=time.time(), result=result or {}, message=message)

    def mark_failed(self, job_id: str, error: str, *, message: str = "Failed") -> Job | None:
        return self.update(job_id, status=JobStatus.failed, finished_at=time.time(), error=error, message=message)

    def mark_cancelled(self, job_id: str, *, message: str = "Cancelled") -> Job | None:
        return self.update(job_id, status=JobStatus.cancelled, finished_at=time.time(), cancel_requested=True, message=message)

    def request_cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        if job.status == JobStatus.queued:
            return self.mark_cancelled(job_id, message="Cancelled before execution")
        return self.update(job_id, status=JobStatus.cancel_requested, cancel_requested=True, message="Cancellation requested")

    def recover_interrupted(self) -> int:
        now = time.time()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id,status FROM jobs WHERE status IN (?,?,?)",
                (JobStatus.queued.value, JobStatus.running.value, JobStatus.cancel_requested.value),
            ).fetchall()
            for row in rows:
                was_queued = row["status"] == JobStatus.queued.value
                message = "Application restarted before queued operation started" if was_queued else "Application restarted while operation was running"
                state_message = "Interrupted before execution" if was_queued else "Interrupted"
                connection.execute(
                    "UPDATE jobs SET status=?,finished_at=?,message=?,error=? WHERE id=?",
                    (JobStatus.failed.value, now, state_message, message, row["id"]),
                )
        return len(rows)
