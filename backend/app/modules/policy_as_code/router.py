from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .models import PolicyEvaluateRequest, PolicySourceRequest
from .rbac import POLICY_EVALUATE, POLICY_MANAGE, POLICY_VIEW
from .repository import PolicyConflictError, PolicyNotFoundError, PolicyRepository, PolicyRepositoryError, PolicyValidationError


router = APIRouter(prefix="/api/modules/policy-as-code", tags=["policy-as-code"])
_repository: PolicyRepository | None = None


def repository() -> PolicyRepository:
    global _repository
    if _repository is None:
        _repository = PolicyRepository()
    return _repository


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _raise_repository_error(exc: PolicyRepositoryError) -> None:
    if isinstance(exc, PolicyNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PolicyConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, PolicyValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="policy repository operation failed") from exc


@router.get("/summary")
def summary(user: SessionUser = Depends(current_user)):
    _allow(user, POLICY_VIEW)
    return repository().summary()


@router.get("/policies")
def list_policies(user: SessionUser = Depends(current_user)):
    _allow(user, POLICY_VIEW)
    items = repository().list()
    return {"items": items, "total": len(items)}


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, POLICY_VIEW)
    try:
        return repository().get(policy_id).to_dict(include_source=True)
    except PolicyRepositoryError as exc:
        _raise_repository_error(exc)


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicySourceRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, POLICY_MANAGE)
    try:
        record = repository().save(payload.source, payload.format, create=True)
    except PolicyRepositoryError as exc:
        _raise_repository_error(exc)
    record_activity(
        ActivityCategory.module,
        "policy.create",
        user.username,
        target=record.id,
        status=ActivityStatus.success,
        details={"format": record.format, "rule_count": len(record.document.spec.rules)},
        source="policy-as-code",
    )
    return record.to_dict(include_source=True)


@router.put("/policies/{policy_id}")
def update_policy(policy_id: str, payload: PolicySourceRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, POLICY_MANAGE)
    try:
        if repository()._existing_path(policy_id) is None:
            raise PolicyNotFoundError(f"policy not found: {policy_id}")
        record = repository().save(payload.source, payload.format, expected_id=policy_id)
    except PolicyRepositoryError as exc:
        _raise_repository_error(exc)
    record_activity(
        ActivityCategory.module,
        "policy.update",
        user.username,
        target=record.id,
        status=ActivityStatus.success,
        details={"format": record.format, "rule_count": len(record.document.spec.rules)},
        source="policy-as-code",
    )
    return record.to_dict(include_source=True)


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, POLICY_MANAGE)
    try:
        repository().delete(policy_id)
    except PolicyRepositoryError as exc:
        _raise_repository_error(exc)
    record_activity(
        ActivityCategory.module,
        "policy.delete",
        user.username,
        target=policy_id,
        status=ActivityStatus.success,
        source="policy-as-code",
    )
    return {"deleted": policy_id}


@router.post("/validate")
def validate_policy(payload: PolicySourceRequest, user: SessionUser = Depends(current_user)):
    _allow(user, POLICY_EVALUATE)
    try:
        return repository().validate_source(payload.source, payload.format)
    except PolicyRepositoryError as exc:
        _raise_repository_error(exc)


@router.post("/evaluate")
def evaluate_policy(payload: PolicyEvaluateRequest, user: SessionUser = Depends(current_user)):
    _allow(user, POLICY_EVALUATE)
    try:
        if payload.policy_id is not None:
            return repository().evaluate(payload.policy_id, payload.facts)
        if payload.source is not None and payload.format is not None:
            return repository().evaluate_source(payload.source, payload.format, payload.facts)
        return repository().evaluate_enabled(payload.facts)
    except PolicyRepositoryError as exc:
        _raise_repository_error(exc)
