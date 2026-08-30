from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .models import NtpSourceInput, ServiceActionInput
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


def _controlled(operation):
    try:
        return operation()
    except NtpUnavailable:
        api_error(503, "NTP_UNAVAILABLE", "NTP backend is unavailable")
    except PermissionError:
        api_error(503, "NTP_PERMISSION_DENIED", "NTP operation is not permitted")
    except (OSError, RuntimeError):
        api_error(502, "NTP_OPERATION_FAILED", "NTP operation failed")
    except ValueError:
        api_error(422, "NTP_VALIDATION_FAILED", "NTP request is invalid")


def _managed_sources() -> list[NtpSourceInput]:
    instance = service()
    backend = instance.detect_backend()
    if backend == NtpBackend.none:
        return []
    path = instance._config_path(backend)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return instance._managed_sources(text)


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(service().status)


@router.get("/sources")
def sources(user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(lambda: {"items": service().sources()})


@router.post("/sources")
def add_source(payload: NtpSourceInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "NTP configuration changes require confirmation")
    current = _controlled(_managed_sources)
    if payload.server not in {item.server for item in current}:
        current.append(payload)
    result = _controlled(lambda: service().save_sources(current, actor=user.username))
    _activity(user.username, "ntp_source_add", payload.server)
    return result


@router.delete("/sources/{server}")
def delete_source(server: str, confirm: bool = False, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    if not confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "NTP configuration changes require confirmation")
    current = [item for item in _controlled(_managed_sources) if item.server != server]
    result = _controlled(lambda: service().save_sources(current, actor=user.username))
    _activity(user.username, "ntp_source_remove", server)
    return result


@router.post("/sources/test")
def test_source(payload: NtpSourceInput, user: SessionUser = Depends(current_user)):
    authorize(user, "ntp.view")
    return _controlled(lambda: service().test_server(payload.server))


@router.post("/resync")
def resync(user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.resync")
    job = _controlled(lambda: service().enqueue_resync(user.username))
    _activity(user.username, "ntp_resync", details={"job_id": job.id})
    return job


@router.post("/service")
def service_action(payload: ServiceActionInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "ntp.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "NTP service changes require confirmation")
    result = _controlled(lambda: service().service_action(payload.action, actor=user.username))
    _activity(user.username, f"ntp_service_{payload.action}")
    return result
