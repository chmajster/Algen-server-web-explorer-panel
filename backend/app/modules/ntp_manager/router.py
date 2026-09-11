from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .diagnostics import collect_diagnostics
from .models import (
    NtpConfiguration,
    NtpConfigurationMutation,
    NtpFirewallInput,
    NtpRestoreInput,
    NtpSourceInput,
    NtpSourcesMutation,
    NtpTestInput,
    NtpTimezoneInput,
    ServiceActionInput,
)
from .preview import build_config_preview
from .service import NtpBackend, NtpUnavailable, service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/modules/ntp-manager", tags=["ntp-manager"])


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, *, failed: bool = False) -> None:
    record_activity(
        ActivityCategory.module,
        action,
        actor,
        target=target,
        details=details or {},
        status=ActivityStatus.failure if failed else ActivityStatus.success,
        source="ntp-manager",
    )


def _controlled(
    operation: Callable[[], Any],
    *,
    actor: str | None = None,
    action: str | None = None,
    target: str = "",
    details: dict[str, Any] | None = None,
):
    try:
        return operation()
    except NtpUnavailable:
        if actor and action:
            _activity(actor, action, target, details, failed=True)
        api_error(503, "NTP_UNAVAILABLE", "NTP backend is unavailable")
    except FileNotFoundError:
        if actor and action:
            _activity(actor, action, target, details, failed=True)
        api_error(404, "NTP_NOT_FOUND", "NTP resource was not found")
    except PermissionError:
        if actor and action:
            _activity(actor, action, target, details, failed=True)
        api_error(503, "NTP_PERMISSION_DENIED", "NTP operation is not permitted")
    except (OSError, RuntimeError):
        if actor and action:
            _activity(actor, action, target, details, failed=True)
        api_error(502, "NTP_OPERATION_FAILED", "NTP operation failed")
    except ValueError:
        if actor and action:
            _activity(actor, action, target, details, failed=True)
        api_error(422, "NTP_VALIDATION_FAILED", "NTP request is invalid")
    except Exception:  # fail closed at the HTTP boundary; never expose exception details
        if actor and action:
            _activity(actor, action, target, details, failed=True)
        api_error(500, "NTP_INTERNAL_ERROR", "NTP operation failed")


def _require_confirmation(
    confirmed: bool,
    user: SessionUser,
    action: str,
    message: str,
    *,
    target: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    if confirmed:
        return
    _activity(
        user.username,
        action,
        target,
        {**(details or {}), "reason": "confirmation_required"},
        failed=True,
    )
    api_error(422, "CONFIRMATION_REQUIRED", message)


def _managed_sources() -> list[NtpSourceInput]:
    instance = service()
    backend = instance.detect_backend()
    if backend == NtpBackend.none:
        return []
    path = instance._config_path(backend)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return instance._managed_sources(text)


def _dashboard_payload() -> dict[str, Any]:
    instance = service()
    diagnostics = collect_diagnostics(instance)
    clients = instance.clients()
    firewall = instance.firewall_status()
    return {
        **diagnostics["status"],
        "health": diagnostics["health"],
        "metrics": diagnostics["metrics"],
        "sources": diagnostics["sources"],
        "summary": {**diagnostics["summary"], "client_count": len(clients)},
        "firewall": firewall,
        "warnings": diagnostics["warnings"],
        "collected_at": diagnostics["collected_at"],
    }


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(_dashboard_payload)


@router.get("/status")
def status(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(service().status)


@router.get("/config")
def config(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(service().configuration)


@router.put("/config")
def update_config(payload: NtpConfigurationMutation, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    details = {
        "mode": payload.configuration.mode.value,
        "sources": len(payload.configuration.sources),
        "allowed_networks": len(payload.configuration.allowed_networks),
    }
    _require_confirmation(payload.confirm, user, "ntp_config_update", "NTP configuration changes require confirmation", details=details)
    result = _controlled(
        lambda: service().apply_configuration(payload.configuration, actor=user.username),
        actor=user.username,
        action="ntp_config_update",
        details=details,
    )
    _activity(user.username, "ntp_config_update", details=details)
    return result


@router.post("/config/validate")
def validate_config(payload: NtpConfiguration, user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.manage")
    instance = service()
    backend = instance.detect_backend()
    if payload.mode.value in {"server", "client_server"} and backend != NtpBackend.chrony:
        api_error(422, "CHRONY_REQUIRED", "NTP server mode requires chrony")
    path = _controlled(lambda: instance._config_path(backend))
    original = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    candidate = _controlled(lambda: instance._render(backend, original, payload))
    validation = _controlled(lambda: instance._validate_candidate(backend, candidate))
    return build_config_preview(
        original=original,
        candidate=candidate,
        path=str(path),
        backend=backend.value,
        validation=validation,
    )


@router.get("/sources")
def sources(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(lambda: {"items": service().sources()})


@router.put("/sources")
def replace_sources(payload: NtpSourcesMutation, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    details = {"count": len(payload.sources), "order": [item.server for item in payload.sources]}
    _require_confirmation(payload.confirm, user, "ntp_sources_replace", "NTP source changes require confirmation", details=details)
    sources = [item.model_copy(update={"confirm": False}) for item in payload.sources]
    result = _controlled(
        lambda: service().save_sources(sources, actor=user.username),
        actor=user.username,
        action="ntp_sources_replace",
        details=details,
    )
    _activity(user.username, "ntp_sources_replace", details=details)
    return result


@router.post("/sources")
def add_source(payload: NtpSourceInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    details = {"kind": payload.kind.value, "prefer": payload.prefer, "enabled": payload.enabled}
    _require_confirmation(payload.confirm, user, "ntp_source_add", "NTP configuration changes require confirmation", target=payload.server, details=details)
    current = _controlled(_managed_sources)
    if (payload.kind, payload.server) not in {(item.kind, item.server) for item in current}:
        current.append(payload.model_copy(update={"confirm": False}))
    result = _controlled(
        lambda: service().save_sources(current, actor=user.username),
        actor=user.username,
        action="ntp_source_add",
        target=payload.server,
        details=details,
    )
    _activity(user.username, "ntp_source_add", payload.server, details)
    return result


@router.put("/sources/{server}")
def update_source(server: str, payload: NtpSourceInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    details = {"new_server": payload.server, "kind": payload.kind.value, "prefer": payload.prefer, "enabled": payload.enabled}
    _require_confirmation(payload.confirm, user, "ntp_source_update", "NTP configuration changes require confirmation", target=server, details=details)
    current = _controlled(_managed_sources)
    replaced = False
    next_items: list[NtpSourceInput] = []
    for item in current:
        if item.server == server and not replaced:
            next_items.append(payload.model_copy(update={"confirm": False}))
            replaced = True
        else:
            next_items.append(item)
    if not replaced:
        _activity(user.username, "ntp_source_update", server, {**details, "reason": "source_not_found"}, failed=True)
        api_error(404, "NTP_SOURCE_NOT_FOUND", "NTP source was not found")
    result = _controlled(
        lambda: service().save_sources(next_items, actor=user.username),
        actor=user.username,
        action="ntp_source_update",
        target=server,
        details=details,
    )
    _activity(user.username, "ntp_source_update", server, details)
    return result


@router.delete("/sources/{server}")
def delete_source(server: str, confirm: bool = False, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    _require_confirmation(confirm, user, "ntp_source_remove", "NTP configuration changes require confirmation", target=server)
    current = [item for item in _controlled(_managed_sources) if item.server != server]
    result = _controlled(
        lambda: service().save_sources(current, actor=user.username),
        actor=user.username,
        action="ntp_source_remove",
        target=server,
    )
    _activity(user.username, "ntp_source_remove", server)
    return result


@router.post("/test")
def test_source(payload: NtpTestInput, user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(lambda: service().test_server(payload.server))


@router.post("/sources/test")
def test_source_compat(payload: NtpSourceInput, user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(lambda: service().test_server(payload.server))


@router.get("/clients")
def clients(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    values = _controlled(service().clients)
    return {"items": values, "total": len(values)}


@router.post("/sync")
def synchronize(user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.sync")
    job = _controlled(
        lambda: service().enqueue_resync(user.username),
        actor=user.username,
        action="ntp_synchronization_forced",
    )
    _activity(user.username, "ntp_synchronization_forced", details={"job_id": job.id})
    return job


@router.post("/resync")
def resync_compat(user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.sync")
    job = _controlled(
        lambda: service().enqueue_resync(user.username),
        actor=user.username,
        action="ntp_synchronization_forced",
    )
    _activity(user.username, "ntp_synchronization_forced", details={"job_id": job.id})
    return job


@router.post("/service")
def service_action(payload: ServiceActionInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.service.control")
    action = f"ntp_service_{payload.action}"
    _require_confirmation(payload.confirm, user, action, "NTP service changes require confirmation")
    result = _controlled(
        lambda: service().service_action(payload.action, actor=user.username),
        actor=user.username,
        action=action,
    )
    _activity(user.username, action)
    return result


@router.get("/timezones")
def timezones(search: str = Query("", max_length=128), user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    values = _controlled(service().timezones)
    if search:
        needle = search.casefold()
        values = [item for item in values if needle in item.casefold()]
    return {"items": values[:1000], "total": len(values)}


@router.put("/timezone")
def set_timezone(payload: NtpTimezoneInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    _require_confirmation(payload.confirm, user, "ntp_timezone_changed", "Timezone changes require confirmation", target=payload.timezone)
    result = _controlled(
        lambda: service().set_timezone(payload.timezone, actor=user.username),
        actor=user.username,
        action="ntp_timezone_changed",
        target=payload.timezone,
    )
    _activity(user.username, "ntp_timezone_changed", payload.timezone)
    return result


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    base = _controlled(lambda: collect_diagnostics(service()))
    checks = _controlled(service().diagnostics)
    return {**base, "checks": checks}


@router.get("/firewall")
def firewall_status(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(service().firewall_status)


@router.post("/firewall/open")
def firewall_open(payload: NtpFirewallInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.firewall.manage")
    _require_confirmation(payload.confirm, user, "ntp_firewall_udp_123_open", "Opening UDP/123 requires confirmation")
    result = _controlled(
        lambda: service().open_firewall(actor=user.username),
        actor=user.username,
        action="ntp_firewall_udp_123_open",
    )
    _activity(user.username, "ntp_firewall_udp_123_open")
    return result


@router.get("/backups")
def backups(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return {"items": _controlled(service().list_backups)}


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: str, payload: NtpRestoreInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    _require_confirmation(payload.confirm, user, "ntp_configuration_restored", "NTP configuration restore requires confirmation", target=backup_id)
    result = _controlled(
        lambda: service().restore_backup(backup_id, actor=user.username),
        actor=user.username,
        action="ntp_configuration_restored",
        target=backup_id,
    )
    _activity(user.username, "ntp_configuration_restored", backup_id)
    return result


@router.get("/history")
def history(limit: int = Query(200, ge=1, le=2000), user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    values = _controlled(lambda: service().history(limit))
    return {"items": values, "total": len(values)}


@router.post("/chrony/install")
def install_chrony(user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    result = _controlled(
        lambda: service().install_chrony(actor=user.username),
        actor=user.username,
        action="ntp_chrony_installed",
    )
    _activity(user.username, "ntp_chrony_installed", details=result)
    return result
