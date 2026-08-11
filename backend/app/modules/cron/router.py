from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ...auth import authenticate
from ...identity.permissions import Permission, authorize
from ...package_center.jobs import manager
from ...package_center.models import PackageAction, PackagePlan, api_error
from ...package_center.service import get_module, repository as package_repository
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .models import (
    CronJobCreate,
    CronJobCreateRequest,
    CronJobUpdateRequest,
    CronStatus,
    CronValidationRequest,
)
from .schedule import server_timezone
from .service import CronNotFoundError, CronReadOnlyError, service


router = APIRouter(prefix="/api/modules/cron", tags=["cron-manager"])


class CronActionRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=160)
    pam_password: str = Field(min_length=1, max_length=1024)


def _installed() -> bool:
    return "cron" in package_repository().installed()


def _ready() -> None:
    if not _installed():
        api_error(404, "MODULE_NOT_INSTALLED", "Cron Manager module is not installed")


def _allow(user: SessionUser, permission: str | Permission) -> None:
    authorize(user, permission)


def _job_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        if value.startswith("external-") and len(value) == 33 and all(character in "0123456789abcdef" for character in value[9:]):
            return value
        api_error(422, "INVALID_CRON_JOB_ID", "Invalid cron job identifier")


def _critical(user: SessionUser, password: str, confirmation: str, expected: str) -> None:
    if confirmation != expected:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "The exact Cron Manager confirmation value is required", expected=expected)
    authenticate(user.username, password)


def _controlled(operation):
    try:
        return operation()
    except CronNotFoundError:
        api_error(404, "CRON_JOB_NOT_FOUND", "Cron job was not found")
    except CronReadOnlyError:
        api_error(409, "CRON_JOB_READ_ONLY", "External cron entries are read only")
    except ValueError as error:
        api_error(422, "CRON_VALIDATION_FAILED", str(error))


def _enqueue(operation: str, user: SessionUser, *, job_id: str = "", staged: dict | None = None, new_id: str = "") -> dict:
    _ready()
    module = get_module("cron")
    if module["blocked_by_proxmox"]:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Cron mutations are blocked by Proxmox Safe Mode")
    reference = service().stage_input(staged) if staged is not None else ""
    plan = PackagePlan(
        module_id="cron",
        action=PackageAction.manage,
        distribution=module["distribution"],
        compatible=bool(module["compatible"]),
        blocked_by_proxmox=bool(module["blocked_by_proxmox"]),
        config_paths=[str(service().config_path)],
        steps=["Validate typed request", "Prepare managed cron candidate", "Create backup", "Write atomically", "Verify or roll back", "Write audit event"],
        payload={"operation": operation, "input_ref": reference, "job_id": job_id, "new_id": new_id},
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
        _allow(user, Permission.CRON_VIEW)
    except Exception:
        allowed = False
    return {"installed": _installed(), "allowed": allowed and _installed(), "blocked_by_proxmox": bool(get_module("cron")["blocked_by_proxmox"])}


@router.get("/status", response_model=CronStatus)
def status(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.CRON_VIEW)
    _ready()
    module = get_module("cron")
    daemon = service().system.daemon()
    state, enabled = service().system.service_state(daemon)
    return CronStatus(
        installed=True,
        crontab_available=bool(__import__("shutil").which("crontab")),
        daemon=daemon,
        service_state=state,
        service_enabled=enabled,
        configuration_valid=service().config_valid(),
        timezone=str(server_timezone()),
        config_path=str(service().config_path),
        blocked_by_proxmox=bool(module["blocked_by_proxmox"]),
        dashboard=service().dashboard(),
    )


@router.get("/jobs")
def jobs(
    search: str = Query("", max_length=200),
    username: str = Query("", max_length=32),
    status: Literal["", "enabled", "disabled", "external", "invalid"] = "",
    include_external: bool = True,
    user: SessionUser = Depends(current_user),
):
    _allow(user, Permission.CRON_VIEW)
    _ready()
    values = service().list_jobs(search=search, username=username, status=status, include_external=include_external)
    return {"items": [item.model_dump(mode="json") for item in values], "total": len(values)}


@router.get("/jobs/{job_id}")
def job(job_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, Permission.CRON_VIEW)
    _ready()
    return _controlled(lambda: service().get(_job_id(job_id)))


@router.post("/jobs")
def create_job(payload: CronJobCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.CRON_CREATE)
    _critical(user, payload.pam_password, payload.confirmation, "cron:create")
    job_id = str(uuid4())
    definition = CronJobCreate(id=job_id, **payload.model_dump(exclude={"confirmation", "pam_password"}))
    _controlled(lambda: service().validate_definition(definition))
    return _enqueue("job_create", user, job_id=job_id, staged={"job": definition.model_dump(mode="json")})


@router.put("/jobs/{job_id}")
def update_job(job_id: str, payload: CronJobUpdateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.CRON_EDIT)
    job_id = _job_id(job_id)
    _critical(user, payload.pam_password, payload.confirmation, job_id)
    definition = payload.model_dump(exclude={"confirmation", "pam_password"})
    _controlled(lambda: service().validate_definition(payload))
    return _enqueue("job_update", user, job_id=job_id, staged={"job": definition})


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, payload: CronActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.CRON_DELETE)
    job_id = _job_id(job_id)
    existing = _controlled(lambda: service().get(job_id))
    _critical(user, payload.pam_password, payload.confirmation, existing.name)
    return _enqueue("job_delete", user, job_id=job_id)


def _toggle(job_id: str, payload: CronActionRequest, user: SessionUser, enabled: bool) -> dict:
    _allow(user, Permission.CRON_ENABLE)
    job_id = _job_id(job_id)
    existing = _controlled(lambda: service().get(job_id))
    if existing.read_only:
        api_error(409, "CRON_JOB_READ_ONLY", "External cron entries are read only")
    _critical(user, payload.pam_password, payload.confirmation, job_id)
    return _enqueue("job_enable" if enabled else "job_disable", user, job_id=job_id)


@router.post("/jobs/{job_id}/enable")
def enable_job(job_id: str, payload: CronActionRequest, user: SessionUser = Depends(mutating_user)):
    return _toggle(job_id, payload, user, True)


@router.post("/jobs/{job_id}/disable")
def disable_job(job_id: str, payload: CronActionRequest, user: SessionUser = Depends(mutating_user)):
    return _toggle(job_id, payload, user, False)


@router.post("/jobs/{job_id}/duplicate")
def duplicate_job(job_id: str, payload: CronActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.CRON_CREATE)
    job_id = _job_id(job_id)
    existing = _controlled(lambda: service().get(job_id))
    if existing.read_only:
        api_error(409, "CRON_JOB_READ_ONLY", "External cron entries are read only")
    _critical(user, payload.pam_password, payload.confirmation, job_id)
    return _enqueue("job_duplicate", user, job_id=job_id, new_id=str(uuid4()))


@router.post("/validate")
def validate(payload: CronValidationRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, Permission.CRON_EDIT)
    _ready()
    definition = _controlled(payload.definition)
    result, _ = _controlled(lambda: service().validate_definition(definition))
    return result


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(current_user)):
    _allow(user, Permission.CRON_VIEW)
    _ready()
    blocked = bool(get_module("cron")["blocked_by_proxmox"])
    return {"items": [item.model_dump(mode="json") for item in service().diagnostics(blocked_by_proxmox=blocked)]}


@router.get("/logs")
def logs(
    source: str = "",
    limit: int = Query(200, ge=1, le=1000),
    search: str = Query("", max_length=200),
    username: str = Query("", max_length=32),
    job_id: str = Query("", max_length=40),
    user: SessionUser = Depends(current_user),
):
    _allow(user, Permission.CRON_LOGS)
    _ready()
    sources = service().log_sources()
    selected = source or (sources[0]["id"] if sources else "")
    if not selected:
        return {"source": "", "sources": [], "entries": [], "truncated": False}
    return _controlled(lambda: service().logs(selected, limit=limit, search=search, username=username, job_id=_job_id(job_id) if job_id else ""))


@router.get("/jobs/{job_id}/history")
def history(job_id: str, limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(current_user)):
    _allow(user, Permission.CRON_LOGS)
    _ready()
    return _controlled(lambda: service().history(_job_id(job_id), limit))
