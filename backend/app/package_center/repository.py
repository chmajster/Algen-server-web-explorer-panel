from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import get_config
from ..sqlite_utils import ClosingConnection
from .detached_updates import detached_update_session, read_update_state, update_session_directory
from .models import PackageJobStatus, PackagePlan, PackageSourceInput


class PackageRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(get_config().paths.data_dir) / "package-center.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        self.recover_interrupted()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS package_jobs (
                    id TEXT PRIMARY KEY, module_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0, current_step TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL,
                    created_at REAL NOT NULL, started_at REAL, finished_at REAL, exit_code INTEGER, error TEXT NOT NULL DEFAULT '',
                    cancellation_requested INTEGER NOT NULL DEFAULT 0, requires_reboot INTEGER NOT NULL DEFAULT 0,
                    previous_version TEXT, target_version TEXT, plan_json TEXT NOT NULL, retry_of TEXT,
                    warnings_json TEXT NOT NULL DEFAULT '[]', result_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_package_jobs_status ON package_jobs(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_package_jobs_module ON package_jobs(module_id, created_at);
                CREATE TABLE IF NOT EXISTS package_job_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES package_jobs(id) ON DELETE CASCADE,
                    created_at REAL NOT NULL, stream TEXT NOT NULL, line TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_package_logs_job ON package_job_logs(job_id, id);
                CREATE TABLE IF NOT EXISTS installed_packages (
                    module_id TEXT PRIMARY KEY, version TEXT NOT NULL, installed_at REAL NOT NULL, updated_at REAL NOT NULL,
                    installed_by TEXT NOT NULL, requires_reboot INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS package_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, module_id TEXT NOT NULL, action TEXT NOT NULL,
                    status TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL, finished_at REAL, message TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS package_sources (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, github_url TEXT NOT NULL, branch TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, last_sync_at REAL, validation_error TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(package_jobs)").fetchall()}
            if "warnings_json" not in columns:
                connection.execute("ALTER TABLE package_jobs ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'")
            if "result_json" not in columns:
                connection.execute("ALTER TABLE package_jobs ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def _job(row: sqlite3.Row, logs: list[dict] | None = None) -> dict[str, Any]:
        result = dict(row)
        result["cancellation_requested"] = bool(result["cancellation_requested"])
        result["requires_reboot"] = bool(result["requires_reboot"])
        result["plan"] = json.loads(result.pop("plan_json") or "{}")
        result["warnings"] = json.loads(result.pop("warnings_json", "[]") or "[]")
        result["result"] = json.loads(result.pop("result_json", "{}") or "{}")
        result["cancellable"] = not (result["status"] == PackageJobStatus.running.value and detached_update_session(result["plan"]))
        result["log_tail"] = logs or []
        requested_operation = result["plan"].get("payload", {}).get("operation")
        result["operation"] = requested_operation if isinstance(requested_operation, str) and requested_operation else result["action"]
        result["stage"] = result["current_step"]
        result["requested_by"] = result["created_by"]
        return result

    def create_job(self, plan: PackagePlan, actor: str, *, previous_version: str | None = None, retry_of: str | None = None) -> dict:
        job_id = uuid4().hex
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO package_jobs
                (id,module_id,action,status,progress,current_step,created_by,created_at,requires_reboot,previous_version,target_version,plan_json,retry_of)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, plan.module_id, plan.action.value, PackageJobStatus.queued.value, 0, "Queued", actor, now, int(plan.requires_reboot), previous_version or plan.previous_version, plan.target_version, plan.model_dump_json(), retry_of),
            )
        return self.get_job(job_id) or {}

    def update_job(self, job_id: str, **values: Any) -> None:
        allowed = {"status", "progress", "current_step", "started_at", "finished_at", "exit_code", "error", "cancellation_requested", "warnings", "result"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        if "cancellation_requested" in updates:
            updates["cancellation_requested"] = int(bool(updates["cancellation_requested"]))
        if "warnings" in updates:
            updates["warnings_json"] = json.dumps(updates.pop("warnings"), ensure_ascii=False)
        if "result" in updates:
            updates["result_json"] = json.dumps(updates.pop("result"), ensure_ascii=False)
        columns = ", ".join(f"{key}=?" for key in updates)
        with self._lock, self.connect() as connection:
            # Dynamic column names come exclusively from the fixed allowlist above.
            connection.execute(f"UPDATE package_jobs SET {columns} WHERE id=?", [*updates.values(), job_id])  # nosec B608

    def append_log(self, job_id: str, line: str, stream: str = "stdout") -> None:
        cleaned = line.replace("\x00", "")[-4000:]
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO package_job_logs(job_id,created_at,stream,line) VALUES (?,?,?,?)", (job_id, time.time(), stream, cleaned))

    def logs(self, job_id: str, limit: int = 200, after: int = 0) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id,created_at,stream,line FROM package_job_logs WHERE job_id=? AND id>? ORDER BY id DESC LIMIT ?", (job_id, after, min(max(limit, 1), 1000))).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM package_jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row, self.logs(job_id, 500)) if row else None

    def list_jobs(self, status: str | None = None, module_id: str | None = None, limit: int = 200) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if module_id:
            clauses.append("module_id=?")
            params.append(module_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            # WHERE clauses are fixed literals; all external values remain parameterized.
            rows = connection.execute(f"SELECT * FROM package_jobs {where} ORDER BY created_at DESC LIMIT ?", [*params, min(max(limit, 1), 500)]).fetchall()  # nosec B608
        return [self._job(row, self.logs(row["id"], 80)) for row in rows]

    def active_jobs(self, module_id: str | None = None) -> list[dict]:
        active = (PackageJobStatus.queued.value, PackageJobStatus.running.value, PackageJobStatus.waiting_for_confirmation.value)
        query = "SELECT * FROM package_jobs WHERE status IN (?,?,?)"
        params: list[Any] = list(active)
        if module_id:
            query += " AND module_id=?"
            params.append(module_id)
        query += " ORDER BY created_at"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._job(row) for row in rows]

    def recover_interrupted(self) -> int:
        now = time.time()
        message = "Package operation was interrupted by a WebNAS restart"
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT id,module_id,action,created_by,created_at,plan_json FROM package_jobs WHERE status='running'").fetchall()
            recovered = 0
            for row in rows:
                try:
                    plan = json.loads(row["plan_json"] or "{}")
                except (TypeError, ValueError):
                    plan = {}
                session_id = detached_update_session(plan) if isinstance(plan, dict) else None
                if session_id and read_update_state(update_session_directory(self.path.parent, session_id)):
                    # A detached screen worker owns this operation. PackageJobManager
                    # reconnects to its atomic state file during application startup.
                    continue
                connection.execute("UPDATE package_jobs SET status='failed', finished_at=?, error=?, current_step='Interrupted' WHERE id=?", (now, message, row["id"]))
                connection.execute("INSERT INTO package_job_logs(job_id,created_at,stream,line) VALUES (?,?,?,?)", (row["id"], now, "stderr", message))
                connection.execute("INSERT INTO package_history(job_id,module_id,action,status,actor,created_at,finished_at,message) VALUES (?,?,?,?,?,?,?,?)", (row["id"], row["module_id"], row["action"], "failed", row["created_by"], row["created_at"], now, message))
                recovered += 1
        return recovered

    def finish_history(self, job: dict) -> None:
        action = job["action"]
        if action == "manage":
            operation = job.get("plan", {}).get("payload", {}).get("operation")
            if isinstance(operation, str) and operation:
                action = operation
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO package_history(job_id,module_id,action,status,actor,created_at,finished_at,message) VALUES (?,?,?,?,?,?,?,?)",
                (job["id"], job["module_id"], action, job["status"], job["created_by"], job["created_at"], job.get("finished_at"), job.get("error") or job.get("current_step") or ""),
            )

    def history(self, limit: int = 300) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM package_history ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 1000),)).fetchall()
        return [dict(row) for row in rows]

    def installed(self) -> dict[str, dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM installed_packages").fetchall()
        return {row["module_id"]: dict(row) for row in rows}

    def mark_installed(self, module_id: str, version: str, actor: str, requires_reboot: bool) -> None:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO installed_packages(module_id,version,installed_at,updated_at,installed_by,requires_reboot) VALUES (?,?,?,?,?,?)
                ON CONFLICT(module_id) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,installed_by=excluded.installed_by,requires_reboot=excluded.requires_reboot""",
                (module_id, version, now, now, actor, int(requires_reboot)),
            )

    def mark_uninstalled(self, module_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM installed_packages WHERE module_id=?", (module_id,))

    @staticmethod
    def _source(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def list_sources(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM package_sources ORDER BY name").fetchall()
        return [self._source(row) for row in rows]

    def create_source(self, source: PackageSourceInput) -> dict:
        source_id = uuid4().hex
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO package_sources(id,name,github_url,branch,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (source_id, source.name, str(source.github_url), source.branch, int(source.enabled), now, now))
            row = connection.execute("SELECT * FROM package_sources WHERE id=?", (source_id,)).fetchone()
        return self._source(row)

    def import_legacy_sources(self, sources: list[dict]) -> None:
        with self._lock, self.connect() as connection:
            for source in sources:
                source_id = str(source.get("id") or uuid4().hex)
                now = float(source.get("updated_at") or time.time())
                connection.execute(
                    """INSERT OR IGNORE INTO package_sources
                    (id,name,github_url,branch,enabled,created_at,updated_at,metadata_json) VALUES (?,?,?,?,?,?,?,?)""",
                    (source_id, str(source.get("name") or source_id), str(source.get("github_url") or ""), str(source.get("branch") or "main"), int(bool(source.get("enabled", True))), float(source.get("created_at") or now), now, json.dumps({"codex_instructions": source.get("codex_instructions", "")})),
                )

    def update_source(self, source_id: str, source: PackageSourceInput) -> dict | None:
        with self._lock, self.connect() as connection:
            connection.execute("UPDATE package_sources SET name=?,github_url=?,branch=?,enabled=?,updated_at=? WHERE id=?", (source.name, str(source.github_url), source.branch, int(source.enabled), time.time(), source_id))
            row = connection.execute("SELECT * FROM package_sources WHERE id=?", (source_id,)).fetchone()
        return self._source(row) if row else None

    def delete_source(self, source_id: str) -> bool:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM package_sources WHERE id=?", (source_id,))
        return cursor.rowcount > 0

    def sync_source(self, source_id: str, *, error: str = "", metadata: dict | None = None) -> dict | None:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("UPDATE package_sources SET last_sync_at=?,validation_error=?,metadata_json=?,updated_at=? WHERE id=?", (now, error, json.dumps(metadata or {}), now, source_id))
            row = connection.execute("SELECT * FROM package_sources WHERE id=?", (source_id,)).fetchone()
        return self._source(row) if row else None
