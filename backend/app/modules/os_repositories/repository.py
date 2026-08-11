from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


def object_id() -> str:
    return uuid.uuid4().hex


class RepositoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "repositories.sqlite3"
        self._lock = threading.RLock()
        self._prepare()
        self._initialize()

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        for name in ("content", "incoming", "published", "snapshots", "builds", "temporary", "gnupg", "backups", "logs", "mirrors", "config"):
            (self.root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root / "published", 0o755)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS repositories(
          id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT NOT NULL, kind TEXT NOT NULL,
          format TEXT NOT NULL, distribution TEXT NOT NULL, distribution_version TEXT NOT NULL, architectures_json TEXT NOT NULL,
          source_url TEXT NOT NULL, active INTEGER NOT NULL, schedule TEXT NOT NULL, retention_count INTEGER NOT NULL,
          signing_key_id TEXT, allow_private_network INTEGER NOT NULL, allow_private_http INTEGER NOT NULL,
          auth_type TEXT NOT NULL DEFAULT 'none', auth_username TEXT NOT NULL DEFAULT '', encrypted_auth_secret TEXT NOT NULL DEFAULT '',
          last_sync_at REAL, last_sync_status TEXT NOT NULL DEFAULT '', package_count INTEGER NOT NULL DEFAULT 0,
          size_bytes INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS repository_sources(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, url TEXT NOT NULL, resolved_addresses_json TEXT NOT NULL DEFAULT '[]', validated_at REAL);
        CREATE TABLE IF NOT EXISTS repository_architectures(repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, architecture TEXT NOT NULL, PRIMARY KEY(repository_id, architecture));
        CREATE TABLE IF NOT EXISTS repository_filters(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, version INTEGER NOT NULL, name TEXT NOT NULL, rules_json TEXT NOT NULL, active INTEGER NOT NULL, created_at REAL NOT NULL, created_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repository_sync_jobs(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, operation TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL, current_item TEXT NOT NULL, downloaded_count INTEGER NOT NULL, downloaded_bytes INTEGER NOT NULL, speed_bps INTEGER NOT NULL, warnings_json TEXT NOT NULL, error TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0, retry_of TEXT, created_at REAL NOT NULL, started_at REAL, finished_at REAL, created_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repository_sync_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES repository_sync_jobs(id) ON DELETE CASCADE, stream TEXT NOT NULL, line TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, name TEXT NOT NULL, version TEXT NOT NULL, release TEXT NOT NULL, epoch TEXT NOT NULL, architecture TEXT NOT NULL, format TEXT NOT NULL, distribution TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, relative_path TEXT NOT NULL, signed INTEGER NOT NULL, signature_status TEXT NOT NULL, maintainer TEXT NOT NULL, vendor TEXT NOT NULL, description TEXT NOT NULL, license TEXT NOT NULL, dependencies_json TEXT NOT NULL, conflicts_json TEXT NOT NULL, source TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0, published_at REAL, created_at REAL NOT NULL, created_by TEXT NOT NULL, UNIQUE(repository_id, sha256));
        CREATE TABLE IF NOT EXISTS package_files(id TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE, path TEXT NOT NULL, owner TEXT NOT NULL, group_name TEXT NOT NULL, mode TEXT NOT NULL, size_bytes INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, name TEXT NOT NULL, description TEXT NOT NULL, package_count INTEGER NOT NULL, logical_size INTEGER NOT NULL, physical_size INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, created_by TEXT NOT NULL, UNIQUE(repository_id, name));
        CREATE TABLE IF NOT EXISTS snapshot_packages(snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE RESTRICT, PRIMARY KEY(snapshot_id, package_id));
        CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, name TEXT NOT NULL, snapshot_id TEXT REFERENCES snapshots(id) ON DELETE RESTRICT, previous_snapshot_id TEXT REFERENCES snapshots(id) ON DELETE RESTRICT, updated_at REAL NOT NULL, updated_by TEXT NOT NULL, UNIQUE(repository_id, name));
        CREATE TABLE IF NOT EXISTS channel_publications(id TEXT PRIMARY KEY, channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE, snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE RESTRICT, previous_snapshot_id TEXT, action TEXT NOT NULL, created_at REAL NOT NULL, created_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signing_keys(id TEXT PRIMARY KEY, name TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, public_key TEXT NOT NULL, encrypted_private_key TEXT NOT NULL, secret_configured INTEGER NOT NULL, expires_at REAL, status TEXT NOT NULL, created_at REAL NOT NULL, created_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS package_builds(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, format TEXT NOT NULL, definition_json TEXT NOT NULL, status TEXT NOT NULL, log_path TEXT NOT NULL, package_id TEXT, error TEXT NOT NULL, created_at REAL NOT NULL, finished_at REAL, created_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS package_build_files(id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES package_builds(id) ON DELETE CASCADE, source_name TEXT NOT NULL, target_path TEXT NOT NULL, owner TEXT NOT NULL, group_name TEXT NOT NULL, mode TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS host_assignments(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, channel TEXT NOT NULL, host_id TEXT, group_id TEXT, created_at REAL NOT NULL, created_by TEXT NOT NULL, UNIQUE(repository_id, channel, host_id, group_id));
        CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, expression TEXT NOT NULL, active INTEGER NOT NULL, next_run_at REAL, last_run_at REAL);
        CREATE TABLE IF NOT EXISTS audit_metadata(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, details_json TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), value_json TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS packages_repository_name ON packages(repository_id, name, architecture);
        CREATE INDEX IF NOT EXISTS jobs_status_created ON repository_sync_jobs(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS audit_created ON audit_metadata(created_at DESC);
        """
        with self._lock, self.connect() as connection:
            connection.executescript(schema)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(repositories)")}
            for name, definition in (
                ("auth_type", "TEXT NOT NULL DEFAULT 'none'"),
                ("auth_username", "TEXT NOT NULL DEFAULT ''"),
                ("encrypted_auth_secret", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE repositories ADD COLUMN {name} {definition}")
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)", (SCHEMA_VERSION, time.time()))
            connection.execute(
                "INSERT OR IGNORE INTO settings(id,value_json,updated_at,updated_by) VALUES(1,?,?,?)",
                (
                    json.dumps({"listen_address": "0.0.0.0", "port": 8088, "public_base_url": "", "upload_limit_mb": 2048, "max_parallel_syncs": 1}),
                    time.time(),
                    "system",
                ),
            )
            connection.execute(
                "UPDATE repository_sync_jobs SET status='failed',stage='interrupted',error='Operation interrupted by WebNAS restart',finished_at=? WHERE status='running'",
                (time.time(),),
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in list(result):
            if key.endswith("_json"):
                result[key.removesuffix("_json")] = json.loads(result.pop(key) or "null")
        for key in ("active", "allow_private_network", "allow_private_http", "signed", "blocked", "archived", "secret_configured", "cancel_requested"):
            if key in result:
                result[key] = bool(result[key])
        return result

    def execute(self, sql: str, values: tuple[Any, ...] = ()) -> int:
        with self._lock, self.connect() as connection:
            return connection.execute(sql, values).rowcount

    def one(self, sql: str, values: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self.row(connection.execute(sql, values).fetchone())

    def all(self, sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [self.row(row) or {} for row in connection.execute(sql, values).fetchall()]

    def page(
        self, table: str, *, page: int, page_size: int, search: str = "", order: str = "created_at DESC", where: str = "", values: tuple[Any, ...] = ()
    ) -> dict[str, Any]:
        clauses, parameters = [], list(values)
        if where:
            clauses.append(where)
        if search:
            clauses.append("(name LIKE ? OR description LIKE ?)")
            parameters.extend([f"%{search}%", f"%{search}%"])
        condition = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM {table}{condition}", parameters).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM {table}{condition} ORDER BY {order} LIMIT ? OFFSET ?", (*parameters, page_size, (page - 1) * page_size)
            ).fetchall()
        return {"items": [self.row(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def audit(self, actor: str, action: str, target: str, details: dict[str, Any] | None = None) -> None:
        safe = json.dumps(details or {}, ensure_ascii=False)[:16384]
        self.execute("INSERT INTO audit_metadata(actor,action,target,details_json,created_at) VALUES(?,?,?,?,?)", (actor, action, target, safe, time.time()))
