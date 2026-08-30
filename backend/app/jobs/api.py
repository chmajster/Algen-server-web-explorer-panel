from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..activity import ActivityCategory, record_activity
from ..identity.permissions import authorize, has_permission
from ..modules.infrastructure_permissions import register_infrastructure_permissions
from ..security import SessionUser, get_session_user, require_csrf
from .models import Job, JobPage, JobStatus, JobSummary
from .service import service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _allowed(user: SessionUser, permission: str) -> bool:
    try:
        return has_permission(user.username, permission)
    except KeyError, ValueError:
        return False


def _can_view_all(user: SessionUser) -> bool:
    return _allowed(user, "jobs.view") or _allowed(user, "audit.view_all") or _allowed(user, "access.manage_roles")


def _can_view_module(user: SessionUser, module: str) -> bool:
    return bool(module) and (_allowed(user, "jobs.view") or _allowed(user, "modules.view"))


def _visible(job: Job, user: SessionUser) -> bool:
    return job.created_by == user.username or _can_view_all(user) or _can_view_module(user, job.module)


def _audit(actor: str, action: str, target: str) -> None:
    record_activity(ActivityCategory.module, action, actor, target=target, source="job-queue-manager")


@router.get("/summary", response_model=JobSummary)
def summary(user: SessionUser = Depends(_user)):
    if not _can_view_all(user):
        authorize(user, "jobs.view")
    return service().summary()


@router.get("", response_model=JobPage)
def list_jobs(
    status: JobStatus | None = None,
    module: str | None = Query(default=None, max_length=96),
    type: str | None = Query(default=None, max_length=96),
    created_by: str | None = Query(default=None, max_length=128),
    since: float | None = Query(default=None, ge=0),
    until: float | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: SessionUser = Depends(_user),
):
    if not _can_view_all(user) and not (module and _can_view_module(user, module)):
        created_by = user.username
    return service().list(status=status, module=module, job_type=type, created_by=created_by, since=since, until=until, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str, user: SessionUser = Depends(_user)):
    job = service().get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if not _visible(job, user):
        raise HTTPException(403, "Job is not visible to this user")
    return job


@router.get("/{job_id}/logs")
def get_job_logs(job_id: str, limit: int = Query(250, ge=1, le=2000), offset: int = Query(0, ge=0), user: SessionUser = Depends(_user)):
    job = service().get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if not _visible(job, user):
        raise HTTPException(403, "Job is not visible to this user")
    return {"items": service().logs(job_id, limit=limit, offset=offset)}


@router.post("/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, user: SessionUser = Depends(_user)):
    job = service().get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.created_by != user.username:
        authorize(user, "jobs.cancel")
    try:
        cancelled = service().cancel(job_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if cancelled is None:
        raise HTTPException(404, "Job not found")
    _audit(user.username, "job_cancel", job_id)
    return cancelled


@router.post("/{job_id}/retry", response_model=Job)
def retry_job(job_id: str, user: SessionUser = Depends(_user)):
    job = service().get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.created_by != user.username:
        authorize(user, "jobs.retry")
    try:
        retried = service().retry(job_id, user.username)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    _audit(user.username, "job_retry", job_id)
    return retried


@router.delete("/history")
def cleanup_history(retention_days: int = Query(30, ge=1, le=3650), user: SessionUser = Depends(_user)):
    authorize(user, "jobs.manage")
    deleted = service().cleanup(retention_days=retention_days)
    _audit(user.username, "job_history_cleanup", str(retention_days))
    return {"deleted": deleted, "retention_days": retention_days}
