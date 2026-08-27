from __future__ import annotations

import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...core.events import bus
from ...identity.permissions import Permission, authorize, require_permission
from ...package_center.models import api_error
from ...security import SessionUser
from .models import ProxmoxConnectionInput, ProxmoxDeleteInput, ProxmoxPowerInput, ProxmoxSyncInput
from .service import ProxmoxApiError, register_host_capabilities, service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/modules/proxmox-manager", tags=["proxmox-manager"])
register_host_capabilities()


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


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    connections = service().connections()
    result = service().list_vms()
    vms = result["vms"]
    return {
        "connections": len(connections),
        "active_connections": sum(bool(item["active"]) for item in connections),
        "vms": len(vms),
        "running": sum(item["status"] == "running" for item in vms),
        "stopped": sum(item["status"] == "stopped" for item in vms),
        "synced": sum(bool(item.get("host_id")) for item in vms),
        "errors": result["errors"],
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
        item = service().save_connection(payload, user.username)
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
        item = service().save_connection(payload, user.username, connection_id)
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
        result = service().sync(
            connection_id,
            user.username,
            resolve_addresses=payload.resolve_addresses,
            disable_missing=payload.disable_missing,
        )
    except Exception as error:
        _activity(user.username, "proxmox_sync", connection_id, {"error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="synchronization")
    details = {
        "created": result["created"],
        "updated": result["updated"],
        "disabled": result["disabled"],
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
    except Exception as error:
        _activity(user.username, f"proxmox_vm_{payload.action}", str(vm.get("host_id") or vmid), {"connection_id": connection_id, "vmid": vmid, "error": _safe_activity_error(error)}, failed=True)
        _api_failure(error, stage="power_action")
    _activity(user.username, f"proxmox_vm_{payload.action}", str(vm.get("host_id") or vmid), {"connection_id": connection_id, "vmid": vmid, "task": result.get("task")})
    return result
