from __future__ import annotations

import json
import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...core.events import bus
from ...identity.permissions import Permission, authorize, require_permission
from ...package_center.models import api_error
from ...security import SessionUser
from .endpoint import detect_endpoint
from .inventory import backups, cluster_health, list_nodes, list_storage, node_details, templates, vm_details
from .models import (
    ProxmoxCloneInput,
    ProxmoxConnectionInput,
    ProxmoxCreateVmInput,
    ProxmoxDeleteInput,
    ProxmoxDestructiveInput,
    ProxmoxDiskResizeInput,
    ProxmoxHardwareUpdateInput,
    ProxmoxMigrationInput,
    ProxmoxPowerInput,
    ProxmoxSnapshotCreateInput,
    ProxmoxSyncInput,
)
from .operations import (
    clone_vm,
    create_snapshot,
    create_vm,
    delete_snapshot,
    hardware_plan,
    list_snapshots,
    migrate_vm,
    resize_disk,
    rollback_snapshot,
    update_hardware,
    validate_migration,
)
from .runtime import (
    configure_connection_runtime,
    connection_lock,
    ensure_runtime_schema,
    mark_sync_finished,
    mark_sync_started,
)
from .service import ProxmoxApiError, register_host_capabilities, service
from .tasks import get_task, list_tasks, register_task, task_log


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/modules/proxmox-manager", tags=["proxmox-manager"])
register_host_capabilities()
ensure_runtime_schema(service())


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, *, failed: bool = False) -> None:
    record_activity(
        ActivityCategory.module,
        action,
        actor,
        target=target,
        details=details or {},
        status=ActivityStatus.failure if failed else ActivityStatus.success,
        source="proxmox-manager",
    )


def _api_failure(error: Exception, *, stage: str = "server", endpoint: str = "") -> NoReturn:
    if isinstance(error, KeyError):
        api_error(404, "PROXMOX_NOT_FOUND", str(error).strip("'"))
    if isinstance(error, PermissionError):
        api_error(422, "PROXMOX_CONFIRMATION_REQUIRED", str(error))
    if isinstance(error, ValueError):
        api_error(422, "PROXMOX_INVALID_CONFIGURATION", str(error))
    if isinstance(error, ProxmoxApiError):
        api_error(
            502,
            "PROXMOX_API_ERROR",
            str(error),
            upstream_status=error.status,
            **error.diagnostic_details(),
        )
    logger.exception("Unexpected Proxmox Manager failure during %s", stage)
    api_error(
        500,
        "PROXMOX_INTERNAL_ERROR",
        "Proxmox Manager encountered an unexpected server error.",
        stage=stage,
        endpoint=endpoint,
        reason=type(error).__name__,
        hint="Check the WebNAS backend logs for this Proxmox Manager failure. Verify service permissions, data-directory access, and the selected credential configuration.",
    )


def _safe_activity_error(error: Exception) -> str:
    if isinstance(error, ProxmoxApiError):
        return str(error)[:1000]
    return type(error).__name__


def _resolve_connection_endpoint(payload: ProxmoxConnectionInput) -> ProxmoxConnectionInput:
    endpoint = detect_endpoint(payload.endpoint)
    return payload.model_copy(update={"endpoint": endpoint})


def _task_details(result: dict[str, Any]) -> dict[str, Any]:
    task = result.get("task")
    if isinstance(task, dict):
        return {
            "upid": str(task.get("upid") or ""),
            "task_status": str(task.get("status") or ""),
        }
    if isinstance(task, str):
        return {"upid": task}
    return {}


def _resolve_node_connection(node: str, connection_id: str) -> str:
    if connection_id:
        return connection_id
    result = list_nodes(service())
    matches = [str(item["connection_id"]) for item in result["nodes"] if str(item.get("node") or "") == node]
    matches = list(dict.fromkeys(matches))
    if not matches:
        raise KeyError("Proxmox node not found")
    if len(matches) > 1:
        raise ValueError("Node name exists in more than one Proxmox connection; provide connection_id")
    return matches[0]


def _run_sync(connection_id: str, payload: ProxmoxSyncInput, actor: str) -> dict[str, Any]:
    lock = connection_lock(connection_id)
    if not lock.acquire(blocking=False):
        raise ValueError("A synchronization for this Proxmox connection is already running")
    started = mark_sync_started(service(), connection_id)
    try:
        result = service().sync(
            connection_id,
            actor,
            resolve_addresses=payload.resolve_addresses,
            disable_missing=payload.disable_missing,
        )
        summary = json.dumps(
            {
                "created": result["created"],
                "updated": result["updated"],
                "disabled": result["disabled"],
                "tagged": result["tagged"],
                "skipped": len(result["skipped"]),
                "tag_errors": len(result["tag_errors"]),
            },
            separators=(",", ":"),
        )
        mark_sync_finished(service(), connection_id, started_at=started, success=True, result=summary)
        return result
    except Exception as error:
        mark_sync_finished(
            service(),
            connection_id,
            started_at=started,
            success=False,
            result="failed",
            error=_safe_activity_error(error),
        )
        raise
    finally:
        lock.release()


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    manager = service()
    connections = manager.connections()
    vm_result = manager.list_vms()
    node_result = list_nodes(manager)
    storage_result = list_storage(manager)
    cluster_result = cluster_health(manager)
    template_result = templates(manager)
    tasks = list_tasks(manager, limit=100, refresh_active=True)
    vms = vm_result["vms"]
    nodes = node_result["nodes"]
    storage_rows = storage_result["storage"]
    clusters = cluster_result["clusters"]
    ram_used = sum(int(item.get("mem") or 0) for item in nodes)
    ram_total = sum(int(item.get("maxmem") or 0) for item in nodes)
    storage_used = sum(int(item.get("used") or 0) for item in storage_rows)
    storage_total = sum(int(item.get("total") or 0) for item in storage_rows)
    last_sync = max((float(item.get("last_sync_at") or 0) for item in connections), default=0)
    future_syncs = [float(item["next_sync_at"]) for item in connections if item.get("next_sync_at")]
    return {
        "connections": len(connections),
        "active_connections": sum(bool(item["active"]) for item in connections),
        "nodes": len(nodes),
        "nodes_online": sum(str(item.get("status") or "") in {"online", "running"} for item in nodes),
        "vms": sum(item["type"] == "qemu" and not item.get("template") for item in vms),
        "lxc": sum(item["type"] == "lxc" and not item.get("template") for item in vms),
        "running": sum(item["status"] == "running" for item in vms),
        "stopped": sum(item["status"] == "stopped" for item in vms),
        "templates": template_result["total"],
        "synced": sum(bool(item.get("host_id")) for item in vms),
        "cpu_utilization": (sum(float(item.get("cpu") or 0) for item in nodes) / len(nodes)) if nodes else 0.0,
        "ram_used": ram_used,
        "ram_total": ram_total,
        "ram_utilization": (ram_used / ram_total) if ram_total else 0.0,
        "storage_used": storage_used,
        "storage_total": storage_total,
        "storage_utilization": (storage_used / storage_total) if storage_total else 0.0,
        "quorum": all(bool(item.get("quorate", True)) for item in clusters) if clusters else None,
        "ha_resources": sum(len(item.get("ha_resources") or []) for item in clusters),
        "last_sync_at": last_sync or None,
        "next_sync_at": min(future_syncs) if future_syncs else None,
        "active_tasks": sum(item["status"] not in {"Completed", "Failed"} for item in tasks),
        "failed_tasks": sum(item["status"] == "Failed" for item in tasks),
        "errors": [*vm_result["errors"], *node_result["errors"], *storage_result["errors"], *cluster_result["errors"]],
    }


@router.get("/connections")
def connections(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return service().connections()


@router.post("/connections")
def create_connection(
    payload: ProxmoxConnectionInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    try:
        item = service().save_connection(_resolve_connection_endpoint(payload), user.username)
        configure_connection_runtime(
            service(),
            item["id"],
            auto_sync=payload.auto_sync,
            sync_interval_seconds=payload.sync_interval_seconds,
        )
        item = service().connection(item["id"]) or item
    except Exception as error:
        _api_failure(error, stage="configuration", endpoint=str(payload.endpoint))
    _activity(user.username, "proxmox_connection_create", item["id"], {"endpoint": item["endpoint"]})
    return item


@router.put("/connections/{connection_id}")
def update_connection(
    connection_id: str,
    payload: ProxmoxConnectionInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    if not service().connection(connection_id):
        api_error(404, "PROXMOX_CONNECTION_NOT_FOUND", "Proxmox connection not found")
    try:
        item = service().save_connection(_resolve_connection_endpoint(payload), user.username, connection_id)
        configure_connection_runtime(
            service(),
            connection_id,
            auto_sync=payload.auto_sync,
            sync_interval_seconds=payload.sync_interval_seconds,
        )
        item = service().connection(connection_id) or item
    except Exception as error:
        _api_failure(error, stage="configuration", endpoint=str(payload.endpoint))
    _activity(user.username, "proxmox_connection_update", connection_id, {"endpoint": item["endpoint"]})
    return item


@router.delete("/connections/{connection_id}")
def delete_connection(
    connection_id: str,
    payload: ProxmoxDeleteInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    item = service().connection(connection_id)
    if not item:
        api_error(404, "PROXMOX_CONNECTION_NOT_FOUND", "Proxmox connection not found")
    if not payload.confirm or payload.confirmation_text != item["name"]:
        api_error(422, "CONFIRMATION_REQUIRED", "Type the Proxmox connection name to confirm removal")
    removed = service().delete_connection(connection_id)
    _activity(user.username, "proxmox_connection_disable", connection_id, {"name": item["name"]})
    return {"ok": removed}


@router.post("/connections/{connection_id}/test")
def test_connection(
    connection_id: str,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    try:
        result = service().test_connection(connection_id)
    except Exception as error:
        _activity(user.username, "proxmox_connection_test", connection_id, {"error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="connection_test")
    _activity(user.username, "proxmox_connection_test", connection_id, {"ok": True})
    return result


@router.post("/connections/{connection_id}/sync")
def sync_connection(
    connection_id: str,
    payload: ProxmoxSyncInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = _run_sync(connection_id, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_sync", connection_id, {"error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="synchronization")
    details = {
        "created": result["created"],
        "updated": result["updated"],
        "disabled": result["disabled"],
        "tagged": result["tagged"],
        "skipped": len(result["skipped"]),
    }
    _activity(user.username, "proxmox_sync", connection_id, details)
    bus.publish("PROXMOX_INVENTORY_CHANGED", {"actor": user.username, "connection_id": connection_id, **details})
    return result


@router.get("/vms")
def virtual_machines(
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return service().list_vms(connection_id)
    except Exception as error:
        _api_failure(error, stage="inventory")


@router.get("/connections/{connection_id}/vms/{vmid}")
def virtual_machine_details(
    connection_id: str,
    vmid: int,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return vm_details(service(), connection_id, vmid)
    except Exception as error:
        _api_failure(error, stage="vm_details")


@router.get("/nodes")
def nodes(
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return list_nodes(service(), connection_id)
    except Exception as error:
        _api_failure(error, stage="nodes")


@router.get("/nodes/{node}")
def node_detail(
    node: str,
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        resolved_connection = _resolve_node_connection(node, connection_id)
        return node_details(service(), resolved_connection, node)
    except Exception as error:
        _api_failure(error, stage="node_details")


@router.get("/nodes/{node}/status")
def node_status(
    node: str,
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        resolved_connection = _resolve_node_connection(node, connection_id)
        item = node_details(service(), resolved_connection, node)
        return {
            "connection_id": resolved_connection,
            "node": node,
            "status": item.get("status"),
            "error": item.get("errors", {}).get("status", ""),
        }
    except Exception as error:
        _api_failure(error, stage="node_status")


@router.get("/storage")
def storage(
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return list_storage(service(), connection_id)
    except Exception as error:
        _api_failure(error, stage="storage")


@router.get("/cluster")
def cluster(
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return cluster_health(service(), connection_id)
    except Exception as error:
        _api_failure(error, stage="cluster")


@router.get("/templates")
def vm_templates(
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return templates(service(), connection_id)
    except Exception as error:
        _api_failure(error, stage="templates")


@router.get("/connections/{connection_id}/vms/{vmid}/backups")
def vm_backups(
    connection_id: str,
    vmid: int,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return backups(service(), connection_id, vmid)
    except Exception as error:
        _api_failure(error, stage="backups")


@router.get("/connections/{connection_id}/vms/{vmid}/snapshots")
def vm_snapshots(
    connection_id: str,
    vmid: int,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    try:
        return {"snapshots": list_snapshots(service(), connection_id, vmid)}
    except Exception as error:
        _api_failure(error, stage="snapshots")


@router.post("/connections/{connection_id}/vms/{vmid}/snapshots")
def vm_snapshot_create(
    connection_id: str,
    vmid: int,
    payload: ProxmoxSnapshotCreateInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = create_snapshot(service(), connection_id, vmid, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_snapshot_create", str(vmid), {"connection_id": connection_id, "vmid": vmid, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="snapshot_create")
    _activity(user.username, "proxmox_snapshot_create", str(vmid), {"connection_id": connection_id, "vmid": vmid, "snapshot": payload.name, **_task_details(result)})
    return result


@router.delete("/connections/{connection_id}/vms/{vmid}/snapshots/{snapshot}")
def vm_snapshot_delete(
    connection_id: str,
    vmid: int,
    snapshot: str,
    payload: ProxmoxDestructiveInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = delete_snapshot(service(), connection_id, vmid, snapshot, actor=user.username, confirm=payload.confirm, confirmation_text=payload.confirmation_text)
    except Exception as error:
        _activity(user.username, "proxmox_snapshot_delete", str(vmid), {"connection_id": connection_id, "vmid": vmid, "snapshot": snapshot, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="snapshot_delete")
    _activity(user.username, "proxmox_snapshot_delete", str(vmid), {"connection_id": connection_id, "vmid": vmid, "snapshot": snapshot, **_task_details(result)})
    return result


@router.post("/connections/{connection_id}/vms/{vmid}/snapshots/{snapshot}/rollback")
def vm_snapshot_rollback(
    connection_id: str,
    vmid: int,
    snapshot: str,
    payload: ProxmoxDestructiveInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = rollback_snapshot(service(), connection_id, vmid, snapshot, actor=user.username, confirm=payload.confirm, confirmation_text=payload.confirmation_text)
    except Exception as error:
        _activity(user.username, "proxmox_snapshot_rollback", str(vmid), {"connection_id": connection_id, "vmid": vmid, "snapshot": snapshot, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="snapshot_rollback")
    _activity(user.username, "proxmox_snapshot_rollback", str(vmid), {"connection_id": connection_id, "vmid": vmid, "snapshot": snapshot, **_task_details(result)})
    return result


@router.post("/connections/{connection_id}/vms/{vmid}/clone")
def vm_clone(
    connection_id: str,
    vmid: int,
    payload: ProxmoxCloneInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = clone_vm(service(), connection_id, vmid, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_clone", str(vmid), {"connection_id": connection_id, "vmid": vmid, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="clone")
    _activity(user.username, "proxmox_clone", str(vmid), {"connection_id": connection_id, "vmid": vmid, "new_vmid": payload.new_vmid, **_task_details(result)})
    return result


@router.post("/connections/{connection_id}/vms/{vmid}/migration/validate")
def vm_migration_validate(
    connection_id: str,
    vmid: int,
    payload: ProxmoxMigrationInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        return validate_migration(service(), connection_id, vmid, payload)
    except Exception as error:
        _api_failure(error, stage="migration_validation")


@router.post("/connections/{connection_id}/vms/{vmid}/migration")
def vm_migration(
    connection_id: str,
    vmid: int,
    payload: ProxmoxMigrationInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = migrate_vm(service(), connection_id, vmid, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_migrate", str(vmid), {"connection_id": connection_id, "vmid": vmid, "target_node": payload.target_node, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="migration")
    _activity(user.username, "proxmox_migrate", str(vmid), {"connection_id": connection_id, "vmid": vmid, "target_node": payload.target_node, **_task_details(result)})
    return result


@router.post("/connections/{connection_id}/vms/{vmid}/hardware/plan")
def vm_hardware_plan(
    connection_id: str,
    vmid: int,
    payload: ProxmoxHardwareUpdateInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        return hardware_plan(service(), connection_id, vmid, payload)
    except Exception as error:
        _api_failure(error, stage="hardware_plan")


@router.put("/connections/{connection_id}/vms/{vmid}/hardware")
def vm_hardware_update(
    connection_id: str,
    vmid: int,
    payload: ProxmoxHardwareUpdateInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = update_hardware(service(), connection_id, vmid, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_hardware_update", str(vmid), {"connection_id": connection_id, "vmid": vmid, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="hardware_update")
    _activity(user.username, "proxmox_hardware_update", str(vmid), {"connection_id": connection_id, "vmid": vmid, "changes": result.get("changes", []), **_task_details(result)})
    return result


@router.put("/connections/{connection_id}/vms/{vmid}/disks/resize")
def vm_disk_resize(
    connection_id: str,
    vmid: int,
    payload: ProxmoxDiskResizeInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = resize_disk(service(), connection_id, vmid, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_disk_resize", str(vmid), {"connection_id": connection_id, "vmid": vmid, "disk": payload.disk, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="disk_resize")
    _activity(user.username, "proxmox_disk_resize", str(vmid), {"connection_id": connection_id, "vmid": vmid, "disk": payload.disk, "current_gb": result.get("current_gb"), "new_gb": result.get("new_gb"), **_task_details(result)})
    return result


@router.post("/connections/{connection_id}/vms")
def vm_create(
    connection_id: str,
    payload: ProxmoxCreateVmInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = create_vm(service(), connection_id, payload, user.username)
    except Exception as error:
        _activity(user.username, "proxmox_vm_create", str(payload.vmid), {"connection_id": connection_id, "vmid": payload.vmid, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="vm_create")
    _activity(user.username, "proxmox_vm_create", str(payload.vmid), {"connection_id": connection_id, "vmid": payload.vmid, "name": payload.name, **_task_details(result)})
    return result


@router.get("/tasks")
def tasks(
    connection_id: str = Query("", max_length=64),
    active_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW)),
):
    try:
        items = list_tasks(service(), connection_id=connection_id, active_only=active_only, limit=limit, refresh_active=True)
        return {"tasks": items, "total": len(items)}
    except Exception as error:
        _api_failure(error, stage="tasks")


@router.get("/tasks/{upid}")
def task_details(
    upid: str,
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW)),
):
    try:
        return get_task(service(), upid, connection_id=connection_id, refresh=True)
    except Exception as error:
        _api_failure(error, stage="task_status")


@router.get("/tasks/{upid}/log")
def task_logs(
    upid: str,
    connection_id: str = Query("", max_length=64),
    start: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW)),
):
    try:
        return {"log": task_log(service(), upid, connection_id=connection_id, start=start, limit=limit)}
    except Exception as error:
        _api_failure(error, stage="task_log")


@router.post("/connections/{connection_id}/vms/{vmid}/power")
def vm_power(
    connection_id: str,
    vmid: int,
    payload: ProxmoxPowerInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_POWER_VIEW)),
):
    permission = {
        "start": Permission.HOSTS_MANAGER_POWER_ON,
        "stop": Permission.HOSTS_MANAGER_POWER_SHUTDOWN,
        "shutdown": Permission.HOSTS_MANAGER_POWER_SHUTDOWN,
        "reboot": Permission.HOSTS_MANAGER_POWER_REBOOT,
    }[payload.action]
    authorize(user, permission)
    try:
        inventory = service().list_vms(connection_id)
    except Exception as error:
        _api_failure(error, stage="inventory")
    vm = next((item for item in inventory["vms"] if int(item["vmid"]) == vmid), None)
    if not vm:
        api_error(404, "PROXMOX_VM_NOT_FOUND", "Proxmox VM not found")
    dangerous = payload.action in {"stop", "shutdown", "reboot"}
    if not payload.confirm or (dangerous and payload.confirmation_text != vm["name"]):
        api_error(422, "CONFIRMATION_REQUIRED", "Power action requires confirmation and the exact VM name for destructive actions")
    try:
        result = service().execute_vm_action(connection_id, vmid, payload.action, user.username)
        raw_task = result.get("task")
        if isinstance(raw_task, str) and raw_task.startswith("UPID:"):
            connection = service().connection(connection_id)
            if not connection:
                raise KeyError("Proxmox connection not found")
            result["task"] = register_task(
                service(),
                connection,
                raw_task,
                action=payload.action,
                actor=user.username,
                vmid=vmid,
                node=str(vm["node"]),
                resource_type=str(vm["type"]),
                host_id=str(vm["host_id"]) if vm.get("host_id") else None,
                operation=result.get("operation") if isinstance(result.get("operation"), dict) else None,
            )
    except Exception as error:
        _activity(user.username, f"proxmox_vm_{payload.action}", str(vm.get("host_id") or vmid), {"connection_id": connection_id, "vmid": vmid, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="power_action")
    _activity(user.username, f"proxmox_vm_{payload.action}", str(vm.get("host_id") or vmid), {"connection_id": connection_id, "vmid": vmid, **_task_details(result)})
    return result
