from __future__ import annotations

import time
import urllib.parse
from typing import Any

from ..hosts_manager.public import registry as host_registry
from .runtime import ensure_runtime_schema
from .service import MODULE_ID, ProxmoxApiError, ProxmoxManagerService


TERMINAL_STATUSES = {"Completed", "Failed"}


def _node_from_upid(upid: str) -> str:
    parts = upid.split(":")
    return parts[1] if len(parts) > 1 and parts[0] == "UPID" else ""


def _extract_upid(value: Any) -> str:
    if isinstance(value, str) and value.startswith("UPID:"):
        return value
    if isinstance(value, dict):
        candidate = value.get("upid") or value.get("data") or value.get("task")
        if isinstance(candidate, str) and candidate.startswith("UPID:"):
            return candidate
    raise ProxmoxApiError("Proxmox write operation did not return a valid UPID")


def _decode(row: Any) -> dict[str, Any]:
    value = dict(row)
    value["sync_on_complete"] = bool(value.get("sync_on_complete"))
    value["synced_after_task"] = bool(value.get("synced_after_task"))
    return value


def register_task(
    manager: ProxmoxManagerService,
    connection: dict[str, Any],
    task_value: Any,
    *,
    action: str,
    actor: str,
    vmid: int | None = None,
    node: str = "",
    resource_type: str = "",
    host_id: str | None = None,
    sync_on_complete: bool = False,
) -> dict[str, Any]:
    ensure_runtime_schema(manager)
    upid = _extract_upid(task_value)
    task_node = node or _node_from_upid(upid)
    operation = host_registry().operation(
        host_id,
        f"proxmox.{action}",
        actor,
        module_id=MODULE_ID,
        status="queued",
        stage="proxmox-task",
        progress=10,
        details={
            "connection_id": connection["id"],
            "vmid": vmid,
            "node": task_node,
            "resource_type": resource_type,
            "upid": upid,
        },
    )
    now = time.time()
    with manager.connect() as db:
        db.execute(
            """
            INSERT INTO proxmox_tasks(
                connection_id,upid,action,vmid,node,resource_type,actor,host_id,operation_id,
                status,exitstatus,progress,started_at,ended_at,last_error,
                sync_on_complete,synced_after_task,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,'Queued','',10,?,NULL,'',?,0,?,?)
            ON CONFLICT(connection_id,upid) DO UPDATE SET
                action=excluded.action,vmid=excluded.vmid,node=excluded.node,
                resource_type=excluded.resource_type,actor=excluded.actor,host_id=excluded.host_id,
                operation_id=excluded.operation_id,sync_on_complete=excluded.sync_on_complete,
                updated_at=excluded.updated_at
            """,
            (
                str(connection["id"]),
                upid,
                action,
                vmid,
                task_node,
                resource_type,
                actor,
                host_id,
                operation.get("id") if isinstance(operation, dict) else None,
                now,
                int(sync_on_complete),
                now,
                now,
            ),
        )
    return get_task(manager, upid, connection_id=str(connection["id"]), refresh=False)


def _row_for_task(
    manager: ProxmoxManagerService,
    upid: str,
    *,
    connection_id: str = "",
) -> dict[str, Any]:
    ensure_runtime_schema(manager)
    with manager.connect() as db:
        if connection_id:
            row = db.execute(
                "SELECT * FROM proxmox_tasks WHERE connection_id=? AND upid=?",
                (connection_id, upid),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM proxmox_tasks WHERE upid=? ORDER BY updated_at DESC LIMIT 1",
                (upid,),
            ).fetchone()
    if row is None:
        raise KeyError("Proxmox task not found")
    return _decode(row)


def _persist_task_status(manager: ProxmoxManagerService, task: dict[str, Any]) -> None:
    with manager.connect() as db:
        db.execute(
            """
            UPDATE proxmox_tasks
            SET status=?,exitstatus=?,progress=?,started_at=?,ended_at=?,last_error=?,
                synced_after_task=?,updated_at=?
            WHERE connection_id=? AND upid=?
            """,
            (
                task["status"],
                task.get("exitstatus") or "",
                int(task.get("progress") or 0),
                task.get("started_at"),
                task.get("ended_at"),
                str(task.get("last_error") or "")[:2000],
                int(bool(task.get("synced_after_task"))),
                time.time(),
                task["connection_id"],
                task["upid"],
            ),
        )


def refresh_task(manager: ProxmoxManagerService, task: dict[str, Any]) -> dict[str, Any]:
    if task.get("status") in TERMINAL_STATUSES:
        return task
    connection = manager.connection(str(task["connection_id"]))
    if not connection or not connection.get("active"):
        task["last_error"] = "Proxmox connection is unavailable"
        _persist_task_status(manager, task)
        return task
    node = str(task.get("node") or _node_from_upid(str(task["upid"])))
    if not node:
        task["last_error"] = "Unable to resolve task node from UPID"
        _persist_task_status(manager, task)
        return task
    encoded_node = urllib.parse.quote(node, safe="")
    encoded_upid = urllib.parse.quote(str(task["upid"]), safe="")
    try:
        status = manager._client(connection).get(f"nodes/{encoded_node}/tasks/{encoded_upid}/status")
    except ProxmoxApiError as error:
        task["last_error"] = str(error)[:2000]
        _persist_task_status(manager, task)
        return task
    if not isinstance(status, dict):
        task["last_error"] = "Proxmox returned an invalid task status response"
        _persist_task_status(manager, task)
        return task

    raw_status = str(status.get("status") or "").casefold()
    exitstatus = str(status.get("exitstatus") or "")
    if raw_status in {"stopped", "completed"}:
        task["status"] = "Completed" if exitstatus in {"", "OK"} else "Failed"
        task["progress"] = 100
        task["ended_at"] = float(status.get("endtime") or time.time())
    elif raw_status in {"running", "active"}:
        task["status"] = "Running"
        task["progress"] = max(25, int(task.get("progress") or 0))
    else:
        task["status"] = "Queued"
        task["progress"] = max(10, int(task.get("progress") or 0))
    task["started_at"] = float(status.get("starttime") or task.get("started_at") or task.get("created_at") or time.time())
    task["exitstatus"] = exitstatus
    task["last_error"] = "" if task["status"] != "Failed" else exitstatus

    if task["status"] == "Completed" and task.get("sync_on_complete") and not task.get("synced_after_task"):
        try:
            manager.sync(
                str(task["connection_id"]),
                str(task.get("actor") or "proxmox-task"),
                resolve_addresses=True,
                disable_missing=False,
            )
            task["synced_after_task"] = True
        except Exception as error:  # noqa: BLE001 - task completion remains valid even if registry refresh fails
            task["last_error"] = f"Task completed; Host Registry sync failed: {type(error).__name__}"[:2000]

    _persist_task_status(manager, task)
    return task


def get_task(
    manager: ProxmoxManagerService,
    upid: str,
    *,
    connection_id: str = "",
    refresh: bool = True,
) -> dict[str, Any]:
    task = _row_for_task(manager, upid, connection_id=connection_id)
    return refresh_task(manager, task) if refresh else task


def list_tasks(
    manager: ProxmoxManagerService,
    *,
    connection_id: str = "",
    active_only: bool = False,
    limit: int = 100,
    refresh_active: bool = True,
) -> list[dict[str, Any]]:
    ensure_runtime_schema(manager)
    clauses: list[str] = []
    parameters: list[Any] = []
    if connection_id:
        clauses.append("connection_id=?")
        parameters.append(connection_id)
    if active_only:
        clauses.append("status NOT IN ('Completed','Failed')")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(max(1, min(500, limit)))
    with manager.connect() as db:
        rows = db.execute(
            f"SELECT * FROM proxmox_tasks{where} ORDER BY updated_at DESC LIMIT ?",
            tuple(parameters),
        ).fetchall()
    tasks = [_decode(row) for row in rows]
    if refresh_active:
        for index, task in enumerate(tasks):
            if task["status"] not in TERMINAL_STATUSES:
                tasks[index] = refresh_task(manager, task)
    return tasks


def task_log(
    manager: ProxmoxManagerService,
    upid: str,
    *,
    connection_id: str = "",
    start: int = 0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    task = _row_for_task(manager, upid, connection_id=connection_id)
    connection = manager.connection(str(task["connection_id"]))
    if not connection or not connection.get("active"):
        raise KeyError("Proxmox connection not found")
    node = str(task.get("node") or _node_from_upid(str(task["upid"])))
    encoded_node = urllib.parse.quote(node, safe="")
    encoded_upid = urllib.parse.quote(str(task["upid"]), safe="")
    data = manager._client(connection).get(
        f"nodes/{encoded_node}/tasks/{encoded_upid}/log?start={max(0, start)}&limit={max(1, min(5000, limit))}"
    )
    return [dict(item) for item in (data or []) if isinstance(item, dict)]
