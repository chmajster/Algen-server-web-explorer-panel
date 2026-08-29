from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .models import KeyRotationInput, RestoreInput, SECRET_TYPES, SecretDeleteInput, SecretInput
from .service import service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/modules/secrets-manager", tags=["secrets-manager"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _controlled(operation):
    try:
        return operation()
    except KeyError as error:
        api_error(404, "SECRET_NOT_FOUND", str(error).strip("'"))
    except PermissionError as error:
        api_error(403, "SECRET_ACCESS_DENIED", str(error))
    except ValueError as error:
        api_error(422, "SECRET_VALIDATION_FAILED", str(error))


@router.get("/status")
def status(user: SessionUser = Depends(current_user)):
    _allow(user, "secrets-manager.view")
    return service().status()


@router.get("/types")
def types(user: SessionUser = Depends(current_user)):
    _allow(user, "secrets-manager.view")
    return {"types": list(SECRET_TYPES)}


@router.get("/share-targets")
def share_targets(request: Request, user: SessionUser = Depends(current_user)):
    _allow(user, "secrets-manager.view")
    manifests = getattr(request.app.state.modules, "manifests", ())
    return {
        "modules": [
            {"id": item.id, "name": item.name}
            for item in manifests
            if item.id != "secrets-manager"
        ]
    }


@router.get("/secrets")
def secrets(user: SessionUser = Depends(current_user)):
    _allow(user, "secrets-manager.view")
    return service().secrets()


@router.get("/secrets/{secret_id}")
def secret(secret_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, "secrets-manager.view")
    item = service().secret(secret_id)
    if not item:
        api_error(404, "SECRET_NOT_FOUND", "Secret not found")
    return item


@router.post("/secrets")
def create_secret(payload: SecretInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "secrets-manager.manage")
    return _controlled(lambda: service().save(payload, user.username))


@router.put("/secrets/{secret_id}")
def update_secret(secret_id: str, payload: SecretInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "secrets-manager.manage")
    if not service().secret(secret_id):
        api_error(404, "SECRET_NOT_FOUND", "Secret not found")
    return _controlled(lambda: service().save(payload, user.username, secret_id))


@router.delete("/secrets/{secret_id}")
def delete_secret(secret_id: str, payload: SecretDeleteInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "secrets-manager.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Secret removal requires confirmation")
    return {"ok": _controlled(lambda: service().delete(secret_id, user.username))}


@router.get("/audit")
def audit(
    secret_id: str = Query("", max_length=64),
    limit: int = Query(250, ge=1, le=1000),
    user: SessionUser = Depends(current_user),
):
    _allow(user, "secrets-manager.audit.view")
    return {"items": service().audit(secret_id=secret_id, limit=limit)}


@router.post("/backup")
def backup(user: SessionUser = Depends(mutating_user)):
    _allow(user, "secrets-manager.backup")
    return service().encrypted_backup(user.username)


@router.post("/restore")
def restore(payload: RestoreInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "secrets-manager.restore")
    if payload.confirmation != "RESTORE SECRETS":
        api_error(422, "CONFIRMATION_REQUIRED", "Type RESTORE SECRETS to confirm restore")
    return _controlled(lambda: service().restore_encrypted_backup(payload.payload, user.username))


@router.post("/rotate-key")
def rotate_key(payload: KeyRotationInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "secrets-manager.rotate")
    if payload.confirmation != "ROTATE SECRETS KEY":
        api_error(422, "CONFIRMATION_REQUIRED", "Type ROTATE SECRETS KEY to request a rotation plan")
    return {"requires_offline_maintenance": True, "plan": service().rotation_plan()}
