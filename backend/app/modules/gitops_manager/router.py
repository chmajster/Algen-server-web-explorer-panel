from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .models import CommitInput, FileRestoreInput, RefInput, RepositoryInput
from .service import GitOpsConflict, GitOpsUnavailable, service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/modules/gitops-config-manager", tags=["gitops-config-manager"])


def _controlled(operation):
    try:
        return operation()
    except GitOpsUnavailable as error:
        api_error(503, "GITOPS_UNAVAILABLE", str(error))
    except GitOpsConflict as error:
        api_error(409, "GITOPS_CONFLICT", str(error))
    except ValueError as error:
        api_error(422, "GITOPS_VALIDATION_FAILED", str(error))
    except RuntimeError as error:
        api_error(502, "GITOPS_OPERATION_FAILED", str(error))


def _audit(actor: str, action: str, target: str = "") -> None:
    record_activity(ActivityCategory.module, action, actor, target=target, source="gitops-config-manager")


@router.get("/overview")
def overview(user: SessionUser = Depends(current_user)):
    authorize(user, "gitops.view")
    return _controlled(service().overview)


@router.get("/changes")
def changes(user: SessionUser = Depends(current_user)):
    authorize(user, "gitops.view")
    return _controlled(lambda: {"items": service().changes(), "diff": service().diff()})


@router.get("/history")
def history(limit: int = Query(100, ge=1, le=500), user: SessionUser = Depends(current_user)):
    authorize(user, "gitops.view")
    return _controlled(lambda: {"items": service().history(limit)})


@router.get("/secret-scan")
def secret_scan(user: SessionUser = Depends(current_user)):
    authorize(user, "gitops.view")
    return _controlled(lambda: {"items": service().scan_secrets()})


@router.put("/repository")
def configure(payload: RepositoryInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "gitops.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "GitOps repository configuration requires confirmation")
    result = _controlled(lambda: service().configure(payload.remote, payload.branch))
    _audit(user.username, "gitops_configure", payload.branch)
    return result


@router.post("/commit")
def commit(payload: CommitInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "gitops.commit")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Git commit requires confirmation")
    result = _controlled(lambda: service().commit(payload.message))
    _audit(user.username, "gitops_commit")
    if payload.push and result.get("committed"):
        authorize(user, "gitops.push")
        job = _controlled(lambda: service().enqueue("push", user.username))
        return {**result, "push_job": job}
    return result


@router.post("/branch/checkout")
def checkout(payload: RefInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "gitops.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Branch changes require confirmation")
    result = _controlled(lambda: service().checkout_branch(payload.ref))
    _audit(user.username, "gitops_branch_change", payload.ref)
    return result


@router.post("/restore")
def restore(payload: FileRestoreInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "gitops.rollback")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "File restore requires confirmation")
    result = _controlled(lambda: service().restore_file(payload.path, payload.ref))
    _audit(user.username, "gitops_restore", payload.path)
    return result


@router.post("/revert")
def revert(payload: RefInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "gitops.rollback")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Commit revert requires confirmation")
    result = _controlled(lambda: service().revert(payload.ref))
    _audit(user.username, "gitops_revert", payload.ref)
    return result


@router.post("/sync/{action}")
def job_action(action: str, user: SessionUser = Depends(mutating_user)):
    permission = {"fetch": "gitops.pull", "pull": "gitops.pull", "push": "gitops.push"}.get(action)
    if not permission:
        api_error(404, "GITOPS_ACTION_UNKNOWN", "Unknown GitOps action")
    authorize(user, permission)
    job = _controlled(lambda: service().enqueue(action, user.username))
    _audit(user.username, f"gitops_{action}", job.id)
    return job
