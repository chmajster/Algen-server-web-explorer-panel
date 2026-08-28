from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..identity.permissions import Permission, authorize, has_permission
from ..security import SessionUser, get_session_user, require_csrf
from .models import Job, JobPage, JobStatus
from .service import service


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _can_view_all(user: SessionUser) -> bool:
    return has_permission(user.username, Permission.AUDIT_VIEW_ALL) or has_permission(user.username, Permission.MODULES_VIEW)


def _visible(job: Job, user: SessionUser) -> bool:
    return job.created_by == user.username or _can_view_all(user)


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
    if not _can_view_all(user):
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


@router.post("/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, user: SessionUser = Depends(_user)):
    job = service().get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.created_by != user.username:
        authorize(user, Permission.MODULES_CONFIGURE)
    try:
        cancelled = service().cancel(job_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if cancelled is None:
        raise HTTPException(404, "Job not found")
    return cancelled


@router.post("/{job_id}/retry", response_model=Job)
def retry_job(job_id: str, user: SessionUser = Depends(_user)):
    job = service().get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.created_by != user.username:
        authorize(user, Permission.MODULES_CONFIGURE)
    try:
        return service().retry(job_id, user.username)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
