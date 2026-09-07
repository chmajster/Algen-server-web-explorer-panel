from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .ldap_authentication import repository as ldap_repository
from .ldap_rbac import LdapSyncInput, sync_directory
from .rbac import rbac_read, rbac_write
from .security import SessionUser


class LdapPeriodicSyncSettings(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=5, le=10080)
    nested_groups: bool = True
    max_depth: int = Field(default=8, ge=1, le=16)
    max_nodes: int = Field(default=5000, ge=1, le=10000)
    auto_create_local_groups: bool = False


def _connection() -> sqlite3.Connection:
    connection = ldap_repository().connect()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ldap_rbac_periodic_sync(
            id INTEGER PRIMARY KEY CHECK(id=1),
            enabled INTEGER NOT NULL DEFAULT 0,
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            nested_groups INTEGER NOT NULL DEFAULT 1,
            max_depth INTEGER NOT NULL DEFAULT 8,
            max_nodes INTEGER NOT NULL DEFAULT 5000,
            auto_create_local_groups INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0,
            updated_by TEXT NOT NULL DEFAULT '',
            last_run_at REAL NOT NULL DEFAULT 0,
            last_status TEXT NOT NULL DEFAULT 'Never',
            last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute("INSERT OR IGNORE INTO ldap_rbac_periodic_sync(id) VALUES(1)")
    return connection


def _settings() -> dict:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM ldap_rbac_periodic_sync WHERE id=1").fetchone()
    if row is None:
        return LdapPeriodicSyncSettings().model_dump()
    value = dict(row)
    for key in ("enabled", "nested_groups", "auto_create_local_groups"):
        value[key] = bool(value[key])
    return value


def _save(payload: LdapPeriodicSyncSettings, actor: str) -> dict:
    with _connection() as connection:
        connection.execute(
            """
            UPDATE ldap_rbac_periodic_sync SET
                enabled=?,interval_minutes=?,nested_groups=?,max_depth=?,max_nodes=?,
                auto_create_local_groups=?,updated_at=?,updated_by=?
            WHERE id=1
            """,
            (
                int(payload.enabled),
                payload.interval_minutes,
                int(payload.nested_groups),
                payload.max_depth,
                payload.max_nodes,
                int(payload.auto_create_local_groups),
                time.time(),
                actor,
            ),
        )
    return _settings()


def _record(status: str, error: str = "") -> None:
    # Persist only sanitized exception class/message fragments. LDAP bind secrets
    # are never supplied to this function.
    with _connection() as connection:
        connection.execute(
            "UPDATE ldap_rbac_periodic_sync SET last_run_at=?,last_status=?,last_error=? WHERE id=1",
            (time.time(), status[:64], error[:512]),
        )


async def _periodic_loop() -> None:
    while True:
        state = _settings()
        sleep_seconds = max(60, int(state.get("interval_minutes") or 60) * 60)
        if bool(state.get("enabled")):
            last_run = float(state.get("last_run_at") or 0)
            due_in = max(0.0, last_run + sleep_seconds - time.time())
            if due_in > 0:
                await asyncio.sleep(min(due_in, 60.0))
                continue
            payload = LdapSyncInput(
                nested_groups=bool(state.get("nested_groups", True)),
                max_depth=int(state.get("max_depth") or 8),
                max_nodes=int(state.get("max_nodes") or 5000),
                auto_create_local_groups=bool(state.get("auto_create_local_groups", False)),
            )
            try:
                result = await asyncio.to_thread(
                    sync_directory,
                    payload,
                    "ldap-periodic-sync",
                )
                _record(str(result.get("status") or "Degraded"))
            except Exception as error:
                _record("Offline", f"{type(error).__name__}: {error}")
        await asyncio.sleep(60.0)


@asynccontextmanager
async def lifespan(_app) -> AsyncIterator[None]:
    task = asyncio.create_task(_periodic_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


router = APIRouter(prefix="/api/ldap", tags=["ldap", "rbac"], lifespan=lifespan)


@router.get("/sync-settings")
def get_sync_settings(_user: SessionUser = Depends(rbac_read)):
    return _settings()


@router.put("/sync-settings")
def save_sync_settings(
    payload: LdapPeriodicSyncSettings,
    request: Request,
    user: SessionUser = Depends(rbac_write),
):
    _ = request
    return _save(payload, user.username)


@router.get("/sync-status")
def sync_status(_user: SessionUser = Depends(rbac_read)):
    state = _settings()
    return {
        "mode": "periodic" if state.get("enabled") else "manual/login",
        "last_run_at": state.get("last_run_at", 0),
        "status": state.get("last_status", "Never"),
        "last_error": state.get("last_error", ""),
        "settings": {
            key: state[key]
            for key in (
                "enabled",
                "interval_minutes",
                "nested_groups",
                "max_depth",
                "max_nodes",
                "auto_create_local_groups",
            )
        },
    }
