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
from .models import ACTIVE_STATUSES, Job, JobLogEntry, JobPage, JobPriority, JobStatus


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
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, type TEXT NOT NULL, module TEXT NOT NULL,
                    status TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL,
                    finished_at REAL, created_by TEXT NOT NULL, progress INTEGER,
                    message TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}',
                    retry_count INTEGER NOT NULL DEFAULT 0, retryable INTEGER NOT NULL DEFAULT 0,
                    cancellable INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    parent_job_id TEXT
                );
                CREATE TABLE IF NOT EXISTS job_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    created_at REAL NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_dependencies (
                    job_id TEXT NOT NULL, depends_on_job_id TEXT NOT NULL,
                    PRIMARY KEY(job_id, depends_on_job_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY(depends_on_job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
            additions = {
                "name": "TEXT NOT NULL DEFAULT ''",
                "description": "TEXT NOT NULL DEFAULT ''",
                "priority": "TEXT NOT NULL DEFAULT 'normal'",
                "queued_at": "REAL",
                "current_step": "TEXT NOT NULL DEFAULT ''",
                "total_steps": "INTEGER",
                "worker": "TEXT NOT NULL DEFAULT ''",
                "max_retries": "INTEGER NOT NULL DEFAULT 0",
                "timeout": "REAL",
                "correlation_id": "TEXT",
                "dedup_key": "TEXT",
            }
            for column, ddl in additions.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")  # nosec B608
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_module_created ON jobs(module, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_type_created ON jobs(type, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_actor_created ON jobs(created_by, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_correlation ON jobs(correlation_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_key, status);
                CREATE INDEX IF NOT EXISTS idx_job_logs_job_created ON job_logs(job_id, created_at, id);
                PRAGMA user_version=2;
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        keys = set(row.keys())

        def value(name: str, default: Any = None) -> Any:
            return row[name] if name in keys else default

        return Job(
            id=str(row["id"]),
            type=str(row["type"]),
            module=str(row["module"]),
            name=str(value("name", "") or ""),
            description=str(value("description", "") or ""),
            status=JobStatus(str(row["status"])),
            priority=JobPriority(str(value("priority", "normal"))),
            progress=row["progress"],
            current_step=str(value("current_step", "") or ""),
            total_steps=value("total_steps"),
            created_at=float(row["created_at"]),
            queued_at=value("queued_at", row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_by=str(row["created_by"]),
            worker=str(value("worker", "") or ""),
            retry_count=int(row["retry_count"] or 0),
            max_retries=int(value("max_retries", 0) or 0),
            timeout=value("timeout"),
            result=json.loads(row["result_json"] or "{}"),
            error=str(row["error"] or ""),
            message=str(row["message"] or ""),
            metadata=json.loads(row["metadata_json"] or "{}"),
            retryable=bool(row["retryable"]),
            cancellable=bool(row["cancellable"]),
            cancel_requested=bool(row["cancel_requested"]),
            parent_job_id=row["parent_job_id"],
            correlation_id=value("correlation_id"),
            dedup_key=value("dedup_key"),
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
        name: str = "",
        description: str = "",
        priority: JobPriority = JobPriority.normal,
        max_retries: int = 0,
        timeout: float | None = None,
        correlation_id: str | None = None,
        dedup_key: str | None = None,
        status: JobStatus = JobStatus.queued,
        total_steps: int | None = None,
    ) -> Job:
        job_id, now = uuid4().hex, time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs
                (id,type,module,name,description,status,priority,created_at,queued_at,created_by,metadata_json,
                 retryable,cancellable,parent_job_id,retry_count,max_retries,timeout,correlation_id,dedup_key,total_steps)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    job_type,
                    module,
                    name,
                    description,
                    status.value,
                    priority.value,
                    now,
                    now,
                    created_by,
                    json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                    int(retryable),
                    int(cancellable),
                    parent_job_id,
                    retry_count,
                    max_retries,
                    timeout,
                    correlation_id,
                    dedup_key,
                    total_steps,
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

    def find_active_by_dedup(self, dedup_key: str) -> Job | None:
        statuses = sorted(status.value for status in ACTIVE_STATUSES)
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM jobs WHERE dedup_key=? AND status IN ({placeholders}) ORDER BY created_at DESC LIMIT 1",  # nosec B608
                [dedup_key, *statuses],
            ).fetchone()
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
        for column, candidate in (("status", status.value if status else None), ("module", module), ("type", job_type), ("created_by", created_by)):
            if candidate is not None:
                clauses.append(f"{column}=?")
                params.append(candidate)
        if since is not None:
            clauses.append("created_at>=?")
            params.append(since)
        if until is not None:
            clauses.append("created_at<=?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit, safe_offset = min(max(limit, 1), 500), max(offset, 0)
        with self._connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0])  # nosec B608
            rows = connection.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",  # nosec B608
                [*params, safe_limit, safe_offset],
            ).fetchall()
        return JobPage(items=[self._job(row) for row in rows], total=total, limit=safe_limit, offset=safe_offset)

    def update(self, job_id: str, **values: Any) -> Job | None:
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "progress",
            "message",
            "result",
            "error",
            "metadata",
            "retry_count",
            "retryable",
            "cancellable",
            "cancel_requested",
            "parent_job_id",
            "current_step",
            "total_steps",
            "worker",
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

    def add_dependencies(self, job_id: str, dependencies: list[str]) -> None:
        if not dependencies:
            return
        with self._lock, self._connect() as connection:
            for dependency in dependencies:
                if dependency == job_id:
                    raise ValueError("job cannot depend on itself")
                if connection.execute("SELECT 1 FROM jobs WHERE id=?", (dependency,)).fetchone() is None:
                    raise ValueError(f"dependency does not exist: {dependency}")
            connection.executemany(
                "INSERT OR IGNORE INTO job_dependencies(job_id,depends_on_job_id) VALUES (?,?)",
                [(job_id, dependency) for dependency in dependencies],
            )

    def dependency_states(self, job_id: str) -> list[JobStatus]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT j.status FROM job_dependencies d JOIN jobs j ON j.id=d.depends_on_job_id WHERE d.job_id=?",
                (job_id,),
            ).fetchall()
        return [JobStatus(str(row["status"])) for row in rows]

    def dependents(self, job_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT job_id FROM job_dependencies WHERE depends_on_job_id=?", (job_id,)).fetchall()
        return [str(row["job_id"]) for row in rows]

    def append_log(self, job_id: str, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO job_logs(job_id,created_at,level,message,data_json) VALUES (?,?,?,?,?)",
                (job_id, time.time(), level[:16], message[:4000], json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))),
            )
            connection.execute(
                "DELETE FROM job_logs WHERE job_id=? AND id NOT IN (SELECT id FROM job_logs WHERE job_id=? ORDER BY id DESC LIMIT 2000)",
                (job_id, job_id),
            )

    def logs(self, job_id: str, *, limit: int = 250, offset: int = 0) -> list[JobLogEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_logs WHERE job_id=? ORDER BY id ASC LIMIT ? OFFSET ?",
                (job_id, min(max(limit, 1), 2000), max(offset, 0)),
            ).fetchall()
        return [
            JobLogEntry(
                id=int(row["id"]),
                job_id=str(row["job_id"]),
                created_at=float(row["created_at"]),
                level=str(row["level"]),
                message=str(row["message"]),
                data=json.loads(row["data_json"] or "{}"),
            )
            for row in rows
        ]

    def mark_running(self, job_id: str, worker: str = "") -> Job | None:
        return self.update(job_id, status=JobStatus.running, started_at=time.time(), worker=worker, message="Running")

    def mark_success(self, job_id: str, *, result: dict[str, Any] | None = None, message: str = "Completed") -> Job | None:
        current = self.get(job_id)
        if current is None or current.status in {JobStatus.cancelled, JobStatus.timed_out, JobStatus.blocked}:
            return current
        return self.update(job_id, status=JobStatus.success, progress=100, finished_at=time.time(), result=result or {}, message=message)

    def mark_failed(self, job_id: str, error: str, *, message: str = "Failed") -> Job | None:
        return self.update(job_id, status=JobStatus.failed, finished_at=time.time(), error=error, message=message)

    def mark_timed_out(self, job_id: str, error: str = "Job timed out") -> Job | None:
        return self.update(job_id, status=JobStatus.timed_out, finished_at=time.time(), error=error, message="Timed out")

    def mark_blocked(self, job_id: str, error: str) -> Job | None:
        return self.update(job_id, status=JobStatus.blocked, finished_at=time.time(), error=error, message="Blocked by dependency")

    def mark_cancelled(self, job_id: str, *, message: str = "Cancelled") -> Job | None:
        return self.update(job_id, status=JobStatus.cancelled, finished_at=time.time(), cancel_requested=True, message=message)

    def request_cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None:
            return None
        if job.status in {JobStatus.queued, JobStatus.waiting, JobStatus.retrying}:
            return self.mark_cancelled(job_id, message="Cancelled before execution")
        return self.update(job_id, status=JobStatus.cancel_requested, cancel_requested=True, message="Cancellation requested")

    def recover_interrupted(self) -> int:
        now = time.time()
        recoverable = (JobStatus.queued, JobStatus.waiting, JobStatus.running, JobStatus.cancel_requested, JobStatus.retrying)
        placeholders = ",".join("?" for _ in recoverable)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT id,status FROM jobs WHERE status IN ({placeholders})",  # nosec B608
                [status.value for status in recoverable],
            ).fetchall()
            for row in rows:
                previous = JobStatus(str(row["status"]))
                if previous in {JobStatus.queued, JobStatus.waiting, JobStatus.retrying}:
                    message = "Interrupted before execution"
                    error = "Application restarted before queued operation started"
                else:
                    message = "Interrupted"
                    error = f"Application restarted while job was {previous.value}"
                connection.execute(
                    "UPDATE jobs SET status=?,finished_at=?,message=?,error=? WHERE id=?",
                    (JobStatus.failed.value, now, message, error, row["id"]),
                )
        return len(rows)

    def summary(self, *, workers: int) -> dict[str, Any]:
        today = time.time() - 86400
        with self._connect() as connection:
            counts = {str(row["status"]): int(row["count"]) for row in connection.execute("SELECT status,COUNT(*) AS count FROM jobs GROUP BY status")}
            completed = int(
                connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status=? AND finished_at>=?",
                    (JobStatus.success.value, today),
                ).fetchone()[0]
            )
            average = connection.execute(
                "SELECT AVG(finished_at-started_at) FROM jobs WHERE status=? AND started_at IS NOT NULL AND finished_at IS NOT NULL",
                (JobStatus.success.value,),
            ).fetchone()[0]
        return {
            "running": counts.get(JobStatus.running.value, 0),
            "queued": counts.get(JobStatus.queued.value, 0) + counts.get(JobStatus.retrying.value, 0),
            "waiting": counts.get(JobStatus.waiting.value, 0),
            "failed": counts.get(JobStatus.failed.value, 0) + counts.get(JobStatus.timed_out.value, 0),
            "completed_today": completed,
            "average_execution_seconds": round(float(average or 0), 3),
            "workers": workers,
        }

    def cleanup(self, older_than: float) -> int:
        terminal = (JobStatus.success, JobStatus.failed, JobStatus.cancelled, JobStatus.timed_out, JobStatus.blocked)
        placeholders = ",".join("?" for _ in terminal)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM jobs WHERE finished_at<? AND status IN ({placeholders})",  # nosec B608
                [older_than, *[status.value for status in terminal]],
            )
            return int(cursor.rowcount)
