from __future__ import annotations

import builtins
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ...sqlite_utils import ClosingConnection
from .models import CronEnvironmentVariable, CronJob, CronJobCreate, CronJobSource, CronJobStatus, CronJobUpdate


SCHEMA_VERSION = 1


class CronRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.root = path.parent
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        connection = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cron_jobs(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    command TEXT NOT NULL,
                    working_directory TEXT,
                    environment_json TEXT NOT NULL DEFAULT '[]',
                    timeout_seconds INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cron_jobs_status_user ON cron_jobs(enabled,username,name);
                CREATE TABLE IF NOT EXISTS cron_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cron_history_job_time ON cron_history(job_id,created_at DESC,id DESC);
                """
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        os.chmod(self.path, 0o600)

    @staticmethod
    def _job(row: sqlite3.Row) -> CronJob:
        try:
            environment = json.loads(row["environment_json"])
        except (TypeError, ValueError):
            environment = []
        enabled = bool(row["enabled"])
        return CronJob(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            user=str(row["username"]),
            schedule=str(row["schedule"]),
            command=str(row["command"]),
            working_directory=row["working_directory"],
            environment=[CronEnvironmentVariable.model_validate(item) for item in environment],
            timeout_seconds=row["timeout_seconds"],
            enabled=enabled,
            status=CronJobStatus.enabled if enabled else CronJobStatus.disabled,
            source=CronJobSource.webnas,
            source_label="WebNAS",
            read_only=False,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            created_by=str(row["created_by"]),
            updated_by=str(row["updated_by"]),
        )

    def list(self) -> list[CronJob]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM cron_jobs ORDER BY name COLLATE NOCASE,id").fetchall()
        return [self._job(row) for row in rows]

    def get(self, job_id: str) -> CronJob | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM cron_jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row) if row else None

    @staticmethod
    def _values(payload: CronJobCreate | CronJobUpdate) -> tuple[Any, ...]:
        return (
            payload.name,
            payload.description,
            payload.user,
            payload.schedule,
            payload.command,
            payload.working_directory,
            json.dumps([item.model_dump(mode="json") for item in payload.environment], ensure_ascii=False, separators=(",", ":")),
            payload.timeout_seconds,
            int(payload.enabled),
        )

    @staticmethod
    def _history(connection: sqlite3.Connection, job_id: str | None, action: str, actor: str, details: dict[str, Any]) -> None:
        safe_details = {key: value for key, value in details.items() if key not in {"command", "environment", "password", "pam_password"}}
        connection.execute(
            "INSERT INTO cron_history(job_id,action,actor,details_json,created_at) VALUES(?,?,?,?,?)",
            (job_id, action, actor, json.dumps(safe_details, ensure_ascii=False, separators=(",", ":")), time.time()),
        )

    def create(self, payload: CronJobCreate, actor: str) -> CronJob:
        if not payload.id:
            raise ValueError("cron job id is required")
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO cron_jobs(
                    id,name,description,username,schedule,command,working_directory,environment_json,timeout_seconds,enabled,
                    created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payload.id, *self._values(payload), now, now, actor, actor),
            )
            self._history(connection, payload.id, "cron.job.created", actor, {"name": payload.name, "user": payload.user, "schedule": payload.schedule})
        created = self.get(payload.id)
        if not created:
            raise RuntimeError("cron job could not be read after creation")
        return created

    def update(self, job_id: str, payload: CronJobUpdate, actor: str, action: str = "cron.job.updated") -> CronJob:
        with self._lock, self.connect() as connection:
            changed = connection.execute(
                """UPDATE cron_jobs SET
                    name=?,description=?,username=?,schedule=?,command=?,working_directory=?,environment_json=?,timeout_seconds=?,enabled=?,updated_at=?,updated_by=?
                    WHERE id=?""",
                (*self._values(payload), time.time(), actor, job_id),
            ).rowcount
            if not changed:
                raise KeyError(job_id)
            self._history(connection, job_id, action, actor, {"name": payload.name, "user": payload.user, "schedule": payload.schedule})
        updated = self.get(job_id)
        if not updated:
            raise RuntimeError("cron job could not be read after update")
        return updated

    def delete(self, job_id: str, actor: str, name: str) -> None:
        with self._lock, self.connect() as connection:
            changed = connection.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,)).rowcount
            if not changed:
                raise KeyError(job_id)
            self._history(connection, job_id, "cron.job.deleted", actor, {"name": name})

    def history(self, job_id: str, limit: int = 200) -> builtins.list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,job_id,action,actor,details_json,created_at FROM cron_history WHERE job_id=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (job_id, min(max(limit, 1), 1000)),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json"))
            except (TypeError, ValueError):
                item["details"] = {}
            result.append(item)
        return result
