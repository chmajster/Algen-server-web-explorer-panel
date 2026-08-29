from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .models import BanInput, JailConfigInput, JailToggleInput, ServiceActionInput
from .service import Fail2BanCommandError, Fail2BanUnavailable, service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/modules/fail2ban-manager", tags=["fail2ban-manager"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, *, failed: bool = False) -> None:
    record_activity(
        ActivityCategory.module,
        action,
        actor,
        target=target,
        details=details or {},
        status=ActivityStatus.failure if failed else ActivityStatus.success,
        source="fail2ban-manager",
    )


def _controlled(operation):
    try:
        return operation()
    except Fail2BanUnavailable as error:
        api_error(503, "FAIL2BAN_UNAVAILABLE", str(error))
    except Fail2BanCommandError as error:
        api_error(502, "FAIL2BAN_COMMAND_FAILED", str(error), command=error.command, output=error.output)
    except ValueError as error:
        api_error(422, "FAIL2BAN_VALIDATION_FAILED", str(error))


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(current_user)):
    _allow(user, "fail2ban-manager.view")
    return _controlled(service().status)


@router.get("/jails")
def jails(user: SessionUser = Depends(current_user)):
    _allow(user, "fail2ban-manager.view")
    return _controlled(lambda: {"items": [service().jail_status(name) for name in service().jail_names()]})


@router.get("/jails/{jail}")
def jail(jail: str, user: SessionUser = Depends(current_user)):
    _allow(user, "fail2ban-manager.view")
    return _controlled(lambda: service().jail_status(jail))


@router.get("/jails/{jail}/config")
def jail_config(jail: str, user: SessionUser = Depends(current_user)):
    _allow(user, "fail2ban-manager.view")
    return _controlled(lambda: service().read_managed_config(jail))


@router.put("/jails/{jail}/config")
def save_jail_config(jail: str, payload: JailConfigInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "fail2ban-manager.configure")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Fail2Ban configuration changes require confirmation")
    try:
        result = _controlled(lambda: service().save_config(jail, payload))
    except Exception:
        _activity(user.username, "fail2ban_jail_config_update", jail, failed=True)
        raise
    _activity(user.username, "fail2ban_jail_config_update", jail, {"enabled": payload.enabled})
    return result


@router.put("/jails/{jail}/enabled")
def set_jail_enabled(jail: str, payload: JailToggleInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "fail2ban-manager.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Changing a jail state requires confirmation")
    result = _controlled(lambda: service().set_enabled(jail, payload.enabled))
    _activity(user.username, "fail2ban_jail_enable" if payload.enabled else "fail2ban_jail_disable", jail)
    return result


@router.get("/jails/{jail}/actions/plan")
def action_plan(
    jail: str,
    action: Literal["ban", "unban"],
    ip: str = Query(..., min_length=2, max_length=64),
    user: SessionUser = Depends(current_user),
):
    _allow(user, "fail2ban-manager.ban" if action == "ban" else "fail2ban-manager.unban")
    # Validation is intentionally performed before presenting the plan.
    normalized = _controlled(lambda: service()._ip(ip))  # noqa: SLF001 - plan uses the same strict validator as execution
    normalized_jail = _controlled(lambda: service()._jail(jail))  # noqa: SLF001
    return {
        "action": action,
        "jail": normalized_jail,
        "ip": normalized,
        "requires_confirmation": True,
        "steps": ["validate jail and IP", f"execute fail2ban-client set <jail> {action}ip <ip>", "record audit event"],
    }


@router.post("/jails/{jail}/ban")
def ban(jail: str, payload: BanInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "fail2ban-manager.ban")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Banning an IP requires confirmation")
    try:
        result = _controlled(lambda: service().ban(jail, payload.ip))
    except Exception:
        _activity(user.username, "fail2ban_ban", jail, {"ip": payload.ip}, failed=True)
        raise
    _activity(user.username, "fail2ban_ban", jail, {"ip": result["ip"]})
    return result


@router.post("/jails/{jail}/unban")
def unban(jail: str, payload: BanInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "fail2ban-manager.unban")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Unbanning an IP requires confirmation")
    try:
        result = _controlled(lambda: service().unban(jail, payload.ip))
    except Exception:
        _activity(user.username, "fail2ban_unban", jail, {"ip": payload.ip}, failed=True)
        raise
    _activity(user.username, "fail2ban_unban", jail, {"ip": result["ip"]})
    return result


@router.post("/reload")
def reload_fail2ban(payload: ServiceActionInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "fail2ban-manager.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Fail2Ban reload requires confirmation")
    result = _controlled(service().reload)
    _activity(user.username, "fail2ban_reload")
    return result


@router.post("/restart")
def restart_fail2ban(payload: ServiceActionInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "fail2ban-manager.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Fail2Ban restart requires confirmation")
    result = _controlled(service().restart)
    _activity(user.username, "fail2ban_restart")
    return result


@router.get("/logs")
def logs(
    limit: int = Query(250, ge=1, le=2000),
    query: str = Query("", max_length=160),
    jail: str = Query("", max_length=128),
    ip: str = Query("", max_length=64),
    action: str = Query("", max_length=16),
    user: SessionUser = Depends(current_user),
):
    _allow(user, "fail2ban-manager.logs.view")
    return _controlled(lambda: {"items": service().logs(limit=limit, query=query, jail=jail, address=ip, action=action)})
