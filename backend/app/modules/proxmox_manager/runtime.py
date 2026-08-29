from __future__ import annotations

import threading
import time
from typing import Any

from .service import ProxmoxManagerService


_schema_lock = threading.Lock()
_connection_locks_guard = threading.Lock()
_connection_locks: dict[str, threading.Lock] = {}


def ensure_runtime_schema(manager: ProxmoxManagerService) -> None:
    """Apply additive, backward-compatible Proxmox Manager runtime migrations."""
    with _schema_lock, manager.connect() as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(connections)").fetchall()}
        additions = {
            "sync_interval_seconds": "INTEGER NOT NULL DEFAULT 300",
            "last_sync_started_at": "REAL",
            "next_sync_at": "REAL",
            "last_sync_duration": "REAL",
            "last_sync_result": "TEXT NOT NULL DEFAULT ''",
            "consecutive_sync_failures": "INTEGER NOT NULL DEFAULT 0",
            "backoff_until": "REAL",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE connections ADD COLUMN {name} {definition}")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS proxmox_tasks(
                connection_id TEXT NOT NULL,
                upid TEXT NOT NULL,
                action TEXT NOT NULL,
                vmid INTEGER,
                node TEXT NOT NULL DEFAULT '',
                resource_type TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL,
                host_id TEXT,
                operation_id TEXT,
                status TEXT NOT NULL DEFAULT 'Queued',
                exitstatus TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 10,
                started_at REAL,
                ended_at REAL,
                last_error TEXT NOT NULL DEFAULT '',
                sync_on_complete INTEGER NOT NULL DEFAULT 0,
                synced_after_task INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(connection_id, upid),
                FOREIGN KEY(connection_id) REFERENCES connections(id)
            );
            CREATE INDEX IF NOT EXISTS idx_proxmox_tasks_status_updated
                ON proxmox_tasks(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_proxmox_tasks_vmid
                ON proxmox_tasks(connection_id, vmid, updated_at DESC);
            """
        )


def configure_connection_runtime(
    manager: ProxmoxManagerService,
    connection_id: str,
    *,
    auto_sync: bool,
    sync_interval_seconds: int,
) -> None:
    ensure_runtime_schema(manager)
    now = time.time()
    with manager.connect() as connection:
        current = connection.execute(
            "SELECT next_sync_at FROM connections WHERE id=?",
            (connection_id,),
        ).fetchone()
        if current is None:
            return
        next_sync = current["next_sync_at"]
        if auto_sync and next_sync is None:
            next_sync = now + sync_interval_seconds
        if not auto_sync:
            next_sync = None
        connection.execute(
            """
            UPDATE connections
            SET sync_interval_seconds=?,next_sync_at=?,updated_at=?
            WHERE id=?
            """,
            (sync_interval_seconds, next_sync, now, connection_id),
        )


def connection_lock(connection_id: str) -> threading.Lock:
    with _connection_locks_guard:
        lock = _connection_locks.get(connection_id)
        if lock is None:
            lock = threading.Lock()
            _connection_locks[connection_id] = lock
        return lock


def mark_sync_started(manager: ProxmoxManagerService, connection_id: str) -> float:
    ensure_runtime_schema(manager)
    started = time.time()
    with manager.connect() as connection:
        connection.execute(
            "UPDATE connections SET last_sync_started_at=?,updated_at=? WHERE id=?",
            (started, started, connection_id),
        )
    return started


def mark_sync_finished(
    manager: ProxmoxManagerService,
    connection_id: str,
    *,
    started_at: float,
    success: bool,
    result: str,
    error: str = "",
) -> None:
    ensure_runtime_schema(manager)
    now = time.time()
    with manager.connect() as connection:
        row = connection.execute(
            "SELECT sync_interval_seconds,consecutive_sync_failures FROM connections WHERE id=?",
            (connection_id,),
        ).fetchone()
        if row is None:
            return
        interval = max(60, min(86400, int(row["sync_interval_seconds"] or 300)))
        previous_failures = int(row["consecutive_sync_failures"] or 0)
        failures = 0 if success else previous_failures + 1
        backoff = 0 if success else min(3600, 60 * (2 ** min(failures - 1, 6)))
        next_sync = now + (interval if success else max(interval, backoff))
        connection.execute(
            """
            UPDATE connections
            SET last_sync_duration=?,last_sync_result=?,last_error=?,
                consecutive_sync_failures=?,backoff_until=?,next_sync_at=?,updated_at=?
            WHERE id=?
            """,
            (
                max(0.0, now - started_at),
                result[:2000],
                error[:2000],
                failures,
                None if success else now + backoff,
                next_sync,
                now,
                connection_id,
            ),
        )


def sync_due(connection: dict[str, Any], now: float | None = None) -> bool:
    if not connection.get("active") or not connection.get("auto_sync"):
        return False
    current = time.time() if now is None else now
    backoff_until = float(connection.get("backoff_until") or 0)
    if backoff_until and current < backoff_until:
        return False
    next_sync = float(connection.get("next_sync_at") or 0)
    return not next_sync or current >= next_sync
