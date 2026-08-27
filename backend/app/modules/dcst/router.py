from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, Query

from ...identity.permissions import require_permission
from ...package_center.models import api_error
from ...security import SessionUser
from .models import BulkServiceInput, IPSetInput, PortInput, ServiceInput, SyncInput
from .rbac import (
    DCST_BLOCK_TRAFFIC,
    DCST_MANAGE_IPSETS,
    DCST_MANAGE_PORTS,
    DCST_MANAGE_SERVICES,
    DCST_MANAGE_TAGS,
    DCST_READ,
    DCST_SYNC,
    DCST_VIEW_LOGS,
)
from .service import DcstConflict, DcstHighRisk, DcstNotFound, service

router = APIRouter(prefix="/api/modules/dcst", tags=["dcst"])


def _failure(error: Exception) -> NoReturn:
    if isinstance(error, DcstNotFound):
        api_error(404, "DCST_NOT_FOUND", str(error))
    if isinstance(error, DcstHighRisk):
        api_error(422, "DCST_HIGH_RISK_CONFIRMATION_REQUIRED", str(error))
    if isinstance(error, DcstConflict):
        api_error(409, "DCST_CONFLICT", str(error))
    if isinstance(error, (KeyError, ValueError)):
        api_error(422, "DCST_INVALID_REQUEST", str(error).strip("'"))
    raise error


@router.get("/overview")
def overview(user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().overview()


@router.get("/tags")
def tags(user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().tags()


@router.post("/tags/sync")
def sync_tags(
    payload: SyncInput,
    user: SessionUser = Depends(require_permission(DCST_MANAGE_TAGS)),
):
    try:
        return service().sync_inventory(user.username, apply=not payload.dry_run)
    except Exception as error:
        _failure(error)


@router.post("/tags/{tag_id}/sync")
def sync_tag(
    tag_id: str,
    payload: SyncInput,
    user: SessionUser = Depends(require_permission(DCST_MANAGE_TAGS)),
):
    tag = next((item for item in service().tags() if str(item["id"]) == tag_id), None)
    if not tag:
        api_error(404, "DCST_TAG_NOT_FOUND", "TAG not found")
    ipset = next((item for item in service().ipsets() if item["name"] == tag["name"] and item["type"] == "dynamic"), None)
    if not ipset:
        service().sync_inventory(user.username, apply=False)
        ipset = next((item for item in service().ipsets() if item["name"] == tag["name"] and item["type"] == "dynamic"), None)
    if not ipset:
        api_error(409, "DCST_TAG_IPSET_MISSING", "Dynamic IPSet for TAG is missing")
    try:
        return service().sync_ipset(str(ipset["id"]), user.username, dry_run=payload.dry_run)
    except Exception as error:
        _failure(error)


@router.get("/ipsets")
def ipsets(user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().ipsets()


@router.post("/ipsets")
def create_ipset(payload: IPSetInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_IPSETS))):
    try:
        return service().save_ipset(payload, user.username)
    except Exception as error:
        _failure(error)


@router.get("/ipsets/{item_id}")
def get_ipset(item_id: str, user: SessionUser = Depends(require_permission(DCST_READ))):
    item = next((value for value in service().ipsets() if value["id"] == item_id), None)
    if not item:
        api_error(404, "DCST_IPSET_NOT_FOUND", "IPSet not found")
    return item


@router.put("/ipsets/{item_id}")
def update_ipset(item_id: str, payload: IPSetInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_IPSETS))):
    try:
        return service().save_ipset(payload, user.username, item_id)
    except Exception as error:
        _failure(error)


@router.delete("/ipsets/{item_id}")
def delete_ipset(item_id: str, user: SessionUser = Depends(require_permission(DCST_MANAGE_IPSETS))):
    try:
        return {"ok": service().delete_ipset(item_id, user.username)}
    except Exception as error:
        _failure(error)


@router.post("/ipsets/{item_id}/sync")
def sync_ipset(item_id: str, payload: SyncInput, user: SessionUser = Depends(require_permission(DCST_SYNC))):
    try:
        return service().sync_ipset(item_id, user.username, dry_run=payload.dry_run)
    except Exception as error:
        _failure(error)


@router.get("/ports")
def ports(user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().ports()


@router.post("/ports")
def create_port(payload: PortInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_PORTS))):
    try:
        return service().save_port(payload, user.username)
    except Exception as error:
        _failure(error)


@router.get("/ports/{item_id}")
def get_port(item_id: str, user: SessionUser = Depends(require_permission(DCST_READ))):
    item = next((value for value in service().ports() if value["id"] == item_id), None)
    if not item:
        api_error(404, "DCST_PORT_NOT_FOUND", "Port not found")
    return item | {"dependencies": service().repository.port_dependencies(item_id)}


@router.put("/ports/{item_id}")
def update_port(item_id: str, payload: PortInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_PORTS))):
    try:
        return service().save_port(payload, user.username, item_id)
    except Exception as error:
        _failure(error)


@router.delete("/ports/{item_id}")
def delete_port(item_id: str, user: SessionUser = Depends(require_permission(DCST_MANAGE_PORTS))):
    try:
        return {"ok": service().delete_port(item_id, user.username)}
    except Exception as error:
        _failure(error)


@router.get("/services")
def services(
    search: str = Query("", max_length=256),
    apmid: str = Query("", max_length=128),
    environment: str = Query("", max_length=128),
    direction: str = Query("", pattern="^(|IN|OUT)$"),
    action: str = Query("", pattern="^(|ACCEPT|DROP|REJECT)$"),
    state: str = Query("", pattern="^(|ACTIVE|BLOCKED|DISABLED|PENDING|ERROR)$"),
    user: SessionUser = Depends(require_permission(DCST_READ)),
):
    return service().services(search=search, apmid=apmid, environment=environment, direction=direction, action=action, state=state)


@router.post("/services")
def create_service(payload: ServiceInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    try:
        return service().save_service(payload, user.username)
    except Exception as error:
        _failure(error)


@router.get("/services/{item_id}")
def get_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_READ))):
    item = service().repository.service(item_id)
    if not item:
        api_error(404, "DCST_SERVICE_NOT_FOUND", "Service not found")
    return item


@router.put("/services/{item_id}")
def update_service(item_id: str, payload: ServiceInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    try:
        return service().save_service(payload, user.username, item_id)
    except Exception as error:
        _failure(error)


@router.delete("/services/{item_id}")
def delete_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    try:
        return {"ok": service().delete_service(item_id, user.username)}
    except Exception as error:
        _failure(error)


@router.post("/services/{item_id}/clone")
def clone_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    try:
        return service().clone_service(item_id, user.username)
    except Exception as error:
        _failure(error)


@router.get("/services/{item_id}/preview")
def preview_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_READ))):
    try:
        return service().preview_service(item_id)
    except Exception as error:
        _failure(error)


@router.post("/services/{item_id}/sync")
def sync_service(item_id: str, payload: SyncInput, user: SessionUser = Depends(require_permission(DCST_SYNC))):
    try:
        return service().sync_service(item_id, user.username, dry_run=payload.dry_run, confirm_high_risk=payload.confirm_high_risk)
    except Exception as error:
        _failure(error)


@router.post("/services/{item_id}/block")
def block_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_BLOCK_TRAFFIC))):
    try:
        return service().change_service_state(item_id, user.username, "block")
    except Exception as error:
        _failure(error)


@router.post("/services/{item_id}/unblock")
def unblock_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_BLOCK_TRAFFIC))):
    try:
        return service().change_service_state(item_id, user.username, "unblock")
    except Exception as error:
        _failure(error)


@router.post("/services/{item_id}/enable")
def enable_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    try:
        return service().change_service_state(item_id, user.username, "enable")
    except Exception as error:
        _failure(error)


@router.post("/services/{item_id}/disable")
def disable_service(item_id: str, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    try:
        return service().change_service_state(item_id, user.username, "disable")
    except Exception as error:
        _failure(error)


def _bulk(operation: str, payload: BulkServiceInput, user: SessionUser):
    try:
        return service().bulk(payload.ids, user.username, operation)
    except Exception as error:
        _failure(error)


@router.post("/services/bulk/block")
def bulk_block(payload: BulkServiceInput, user: SessionUser = Depends(require_permission(DCST_BLOCK_TRAFFIC))):
    return _bulk("block", payload, user)


@router.post("/services/bulk/unblock")
def bulk_unblock(payload: BulkServiceInput, user: SessionUser = Depends(require_permission(DCST_BLOCK_TRAFFIC))):
    return _bulk("unblock", payload, user)


@router.post("/services/bulk/enable")
def bulk_enable(payload: BulkServiceInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    return _bulk("enable", payload, user)


@router.post("/services/bulk/disable")
def bulk_disable(payload: BulkServiceInput, user: SessionUser = Depends(require_permission(DCST_MANAGE_SERVICES))):
    return _bulk("disable", payload, user)


@router.post("/services/bulk/sync")
def bulk_sync(payload: BulkServiceInput, user: SessionUser = Depends(require_permission(DCST_SYNC))):
    return _bulk("sync", payload, user)


@router.get("/firewall/status")
def firewall_status(user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().provider.status()


@router.get("/firewall/logs")
def firewall_logs(limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(DCST_VIEW_LOGS))):
    return service().firewall_logs(limit)


@router.post("/firewall/sync")
def firewall_sync(payload: SyncInput, user: SessionUser = Depends(require_permission(DCST_SYNC))):
    try:
        return service().sync_all(user.username, dry_run=payload.dry_run, confirm_high_risk=payload.confirm_high_risk)
    except Exception as error:
        _failure(error)


@router.get("/firewall/drift")
def firewall_drift(user: SessionUser = Depends(require_permission(DCST_SYNC, mutating=False))):
    try:
        return service().drift(user.username)
    except Exception as error:
        _failure(error)


@router.post("/firewall/test")
def firewall_test(user: SessionUser = Depends(require_permission(DCST_SYNC))):
    try:
        return service().test_proxmox()
    except Exception as error:
        _failure(error)


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().diagnostics()


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=1000), user: SessionUser = Depends(require_permission(DCST_READ))):
    return service().audits(limit)
