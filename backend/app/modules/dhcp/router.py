from __future__ import annotations

from typing import Literal, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, Query

from ...auth import authenticate
from ...identity.permissions import Permission, authorize
from ...package_center.jobs import manager
from ...package_center.models import PackageAction, PackagePlan, api_error
from ...package_center.service import get_module, repository as package_repository
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .models import (
    DhcpActionRequest,
    DhcpBackupRequest,
    DhcpConfiguration,
    DhcpConfigurationMutationRequest,
    DhcpReservationCreateRequest,
    DhcpSubnetCreateRequest,
    HostToReservationRequest,
    LeaseToHostRequest,
    LeaseToReservationRequest,
)
from .service import DhcpConflictError, DhcpNotFoundError, service


router = APIRouter(prefix="/api/modules/dhcp", tags=["dhcp-manager"])


def _installed() -> bool:
    return "dhcp" in package_repository().installed()


def _ready() -> None:
    if not _installed():
        api_error(404, "MODULE_NOT_INSTALLED", "DHCP Manager module is not installed")


def _allow(user: SessionUser, permission: str | Permission) -> None:
    authorize(user, permission)


def _critical(user: SessionUser, password: str, confirmation: str, expected: str) -> None:
    if confirmation != expected:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "The exact DHCP Manager confirmation value is required", expected=expected)
    authenticate(user.username, password)


def _failure(error: Exception) -> NoReturn:
    if isinstance(error, DhcpNotFoundError):
        api_error(404, "DHCP_RESOURCE_NOT_FOUND", str(error).strip("'"))
    if isinstance(error, DhcpConflictError):
        api_error(409, "DHCP_CONFLICT", str(error))
    if isinstance(error, ValueError):
        api_error(422, "DHCP_VALIDATION_FAILED", str(error))
    raise error


def _mutation_ready() -> dict:
    _ready()
    module = get_module("dhcp")
    if module["blocked_by_proxmox"]:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "DHCP mutations are blocked by Proxmox Safe Mode")
    return module


def _enqueue(operation: str, user: SessionUser, *, object_id: str = "", staged: dict | None = None) -> dict:
    module = _mutation_ready()
    reference = service().stage_input(staged) if staged is not None else ""
    plan = PackagePlan(
        module_id="dhcp",
        action=PackageAction.manage,
        distribution=module["distribution"],
        compatible=bool(module["compatible"]),
        blocked_by_proxmox=bool(module["blocked_by_proxmox"]),
        config_paths=["/etc/kea/kea-dhcp4.conf", "/etc/dhcp/dhcpd.conf", "/etc/default/isc-dhcp-server"],
        data_paths=[str(service().root), str(service().backups_root)],
        steps=[
            "Validate typed request", "Generate candidate configuration", "Run native DHCP validation",
            "Create backup", "Write atomically", "Reload or restart DHCP", "Verify service and configuration", "Roll back on failure", "Write audit event",
        ],
        payload={"operation": operation, "input_ref": reference, "object_id": object_id},
    )
    try:
        return {"job": manager(package_repository()).enqueue(plan, user.username)}
    except Exception:
        service().discard_input(reference)
        raise


@router.get("/access")
def access(user: SessionUser = Depends(current_user)):
    allowed = True
    try:
        _allow(user, Permission.DHCP_VIEW)
    except Exception:
        allowed = False
    module = get_module("dhcp")
    return {"installed": _installed(), "allowed": allowed and _installed(), "blocked_by_proxmox": bool(module["blocked_by_proxmox"])}


@router.get("/status")
def status(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    module = get_module("dhcp")
    return service().status(installed=True, blocked_by_proxmox=bool(module["blocked_by_proxmox"]))


@router.get("/subnets")
def subnets(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    config = service().configuration()
    utilization = {item.subnet_id: item.model_dump(mode="json") for item in service().utilization(config)}
    return {"items": [{**item.model_dump(mode="json"), "utilization": utilization.get(item.id)} for item in config.subnets], "total": len(config.subnets)}


@router.get("/subnets/{subnet_id}")
def subnet(subnet_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    item = next((item for item in service().configuration().subnets if item.id == subnet_id), None)
    if not item:
        api_error(404, "DHCP_SUBNET_NOT_FOUND", "DHCP subnet was not found")
    return item


@router.post("/subnets")
def create_subnet(payload: DhcpSubnetCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_SUBNETS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, "dhcp:subnet:create")
    subnet = payload.subnet
    if not subnet.id:
        subnet.id = uuid4().hex
    return _enqueue("subnet_create", user, object_id=subnet.id, staged={"subnet": subnet.model_dump(mode="json")})


@router.put("/subnets/{subnet_id}")
def update_subnet(subnet_id: str, payload: DhcpSubnetCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_SUBNETS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, subnet_id)
    if payload.subnet.id != subnet_id:
        api_error(422, "DHCP_SUBNET_ID_MISMATCH", "Subnet identifier cannot be changed")
    return _enqueue("subnet_update", user, object_id=subnet_id, staged={"subnet": payload.subnet.model_dump(mode="json")})


@router.delete("/subnets/{subnet_id}")
def delete_subnet(subnet_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_SUBNETS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, subnet_id)
    return _enqueue("subnet_delete", user, object_id=subnet_id)


def _subnet_toggle(subnet_id: str, payload: DhcpActionRequest, user: SessionUser, enabled: bool):
    _allow(user, Permission.DHCP_SUBNETS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, subnet_id)
    return _enqueue("subnet_enable" if enabled else "subnet_disable", user, object_id=subnet_id)


@router.post("/subnets/{subnet_id}/enable")
def enable_subnet(subnet_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    return _subnet_toggle(subnet_id, payload, user, True)


@router.post("/subnets/{subnet_id}/disable")
def disable_subnet(subnet_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    return _subnet_toggle(subnet_id, payload, user, False)


@router.post("/subnets/{subnet_id}/clone")
def clone_subnet(subnet_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_SUBNETS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, subnet_id)
    return _enqueue("subnet_clone", user, object_id=subnet_id, staged={"new_id": uuid4().hex})


@router.get("/reservations")
def reservations(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    values = service().configuration().reservations
    return {"items": values, "total": len(values)}


@router.post("/reservations")
def create_reservation(payload: DhcpReservationCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, "dhcp:reservation:create")
    return _enqueue("reservation_create", user, object_id=payload.reservation.id, staged={"reservation": payload.reservation.model_dump(mode="json")})


@router.put("/reservations/{reservation_id}")
def update_reservation(reservation_id: str, payload: DhcpReservationCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, reservation_id)
    if payload.reservation.id != reservation_id:
        api_error(422, "DHCP_RESERVATION_ID_MISMATCH", "Reservation identifier cannot be changed")
    return _enqueue("reservation_update", user, object_id=reservation_id, staged={"reservation": payload.reservation.model_dump(mode="json")})


@router.delete("/reservations/{reservation_id}")
def delete_reservation(reservation_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, reservation_id)
    return _enqueue("reservation_delete", user, object_id=reservation_id)


def _reservation_toggle(reservation_id: str, payload: DhcpActionRequest, user: SessionUser, enabled: bool):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, reservation_id)
    return _enqueue("reservation_enable" if enabled else "reservation_disable", user, object_id=reservation_id)


@router.post("/reservations/{reservation_id}/enable")
def enable_reservation(reservation_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    return _reservation_toggle(reservation_id, payload, user, True)


@router.post("/reservations/{reservation_id}/disable")
def disable_reservation(reservation_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    return _reservation_toggle(reservation_id, payload, user, False)


@router.get("/leases")
def leases(
    search: str = Query("", max_length=200), subnet_id: str = Query("", max_length=64),
    state: Literal["", "active", "expired", "declined", "released", "unknown", "reserved"] = "",
    sort: Literal["ipv4_address", "hostname", "lease_end", "remaining", "state"] = "ipv4_address",
    user: SessionUser = Depends(current_user),
):
    _allow(user, Permission.DHCP_LEASES_VIEW)
    _ready()
    values = service().leases(search=search, subnet_id=subnet_id, state=state, sort=sort)
    return {"items": values, "total": len(values)}


@router.post("/leases/{lease_id}/reservation")
def lease_to_reservation(lease_id: str, payload: LeaseToReservationRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, lease_id)
    return _enqueue("lease_to_reservation", user, object_id=lease_id, staged=payload.model_dump(exclude={"confirmation", "pam_password"}, mode="json"))


@router.post("/leases/{lease_id}/hosts")
def lease_to_host(lease_id: str, payload: LeaseToHostRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _allow(user, Permission.HOSTS_MANAGER_HOSTS_MANAGE)
    _critical(user, payload.pam_password, payload.confirmation, lease_id)
    return _enqueue("lease_to_host", user, object_id=lease_id, staged={"ssh_user": payload.ssh_user})


@router.post("/hosts/{host_id}/reservation")
def host_to_reservation(host_id: str, payload: HostToReservationRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESERVATIONS_MANAGE)
    _allow(user, Permission.HOSTS_MANAGER_HOSTS_VIEW)
    _critical(user, payload.pam_password, payload.confirmation, host_id)
    return _enqueue("host_to_reservation", user, object_id=host_id, staged=payload.model_dump(exclude={"confirmation", "pam_password"}, mode="json"))


@router.get("/interfaces")
def interfaces(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    values = service().interfaces()
    return {"items": values, "total": len(values)}


@router.get("/config")
def config(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    return service().configuration()


@router.post("/config/validate")
def validate_config(configuration: DhcpConfiguration, user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_CONFIGURE)
    _ready()
    return service().validate_configuration(configuration)


@router.post("/config/plan")
def plan_config(configuration: DhcpConfiguration, user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_CONFIGURE)
    _ready()
    return service().plan(configuration)


@router.post("/config/apply")
def apply_config(payload: DhcpConfigurationMutationRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_CONFIGURE)
    _critical(user, payload.pam_password, payload.confirmation, "dhcp:apply")
    return _enqueue("config_apply", user, staged={"configuration": payload.configuration.model_dump(mode="json")})


@router.get("/backups")
def backups(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_BACKUP)
    _ready()
    return {"items": service().list_backups()}


@router.post("/backups")
def create_backup(payload: DhcpBackupRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_BACKUP)
    _critical(user, payload.pam_password, payload.confirmation, "dhcp:backup")
    return _enqueue("backup_create", user, staged={"description": payload.description})


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_RESTORE)
    _critical(user, payload.pam_password, payload.confirmation, backup_id)
    return _enqueue("backup_restore", user, object_id=backup_id)


@router.delete("/backups/{backup_id}")
def delete_backup(backup_id: str, payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_BACKUP)
    _critical(user, payload.pam_password, payload.confirmation, backup_id)
    return _enqueue("backup_delete", user, object_id=backup_id)


@router.get("/logs")
def logs(
    search: str = Query("", max_length=200), level: str = Query("", max_length=32),
    limit: int = Query(200, ge=1, le=1000), since: Literal["", "1h", "6h", "24h", "7d"] = "",
    user: SessionUser = Depends(current_user),
):
    _allow(user, Permission.DHCP_VIEW)
    _ready()
    return service().logs(limit=limit, search=search, level=level, since=since)


@router.post("/diagnostics")
def diagnostics(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.DHCP_DIAGNOSTICS)
    _ready()
    module = get_module("dhcp")
    return {"items": service().diagnostics(installed=True, blocked_by_proxmox=bool(module["blocked_by_proxmox"]))}


@router.post("/service/{action}")
def service_control(action: Literal["start", "stop", "restart", "reload", "enable", "disable"], payload: DhcpActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.DHCP_SERVICE_CONTROL)
    _critical(user, payload.pam_password, payload.confirmation, f"dhcp:{action}")
    return _enqueue("service_control", user, staged={"action": action})
