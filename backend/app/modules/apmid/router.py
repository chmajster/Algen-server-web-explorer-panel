from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ...identity import linux_accounts
from ...identity.permissions import Permission, has_permission, require_permission
from ...package_center.models import api_error
from ...package_center.service import repository as package_repository
from ...security import SessionUser, get_session_user, require_csrf
from ..hosts_manager.public import ManagedGroupConflictError, ManagedGroupProtectedError, registry as hosts_registry
from .models import (
    ApmidBackupInput, ApmidInput, ApmidMemberCreate, ApmidMemberUpdate, ApmidPermissionUpdate,
    ApmidResourcePermission, ApmidRestoreInput,
)
from .service import (
    ApmidConflictError, ApmidInUseError, ApmidNotFoundError, LastOwnerError, service,
)


router = APIRouter(prefix="/api/modules/apmid", tags=["apmid"])


def _installed() -> bool:
    return "apmid" in package_repository().installed()


def _module_ready() -> None:
    if not _installed():
        api_error(404, "MODULE_NOT_INSTALLED", "APMID module is not installed")


def _resource(user: SessionUser, apmid_id: str, permission: ApmidResourcePermission) -> None:
    _module_ready()
    if not service().get(apmid_id):
        api_error(404, "APMID_NOT_FOUND", "APMID not found")
    if not service().can(user.username, apmid_id, permission):
        api_error(403, "APMID_PERMISSION_REQUIRED", "The operation is not allowed for this APMID", details={"permission": permission.value})


def _mutation(request: Request, user: SessionUser, apmid_id: str, permission: ApmidResourcePermission) -> None:
    require_csrf(request, user)
    _resource(user, apmid_id, permission)


def _controlled(operation):
    try:
        return operation()
    except ApmidNotFoundError:
        api_error(404, "APMID_NOT_FOUND", "APMID or member not found")
    except ApmidConflictError as error:
        api_error(409, "APMID_CONFLICT", str(error))
    except LastOwnerError as error:
        api_error(409, "APMID_LAST_OWNER", str(error))
    except PermissionError as error:
        api_error(422, "APMID_USER_NOT_ASSIGNABLE", str(error))
    except ValueError as error:
        api_error(422, "APMID_INVALID_OPERATION", str(error))


@router.get("/access")
def access(user: SessionUser = Depends(get_session_user)):
    installed = _installed()
    return {"installed": installed, "allowed": bool(installed and service().has_access(user.username))}


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(get_session_user)):
    _module_ready()
    if not service().has_access(user.username):
        api_error(403, "APMID_PERMISSION_REQUIRED", "APMID access is required")
    return service().dashboard(user.username)


@router.get("/items")
def items(
    page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=128),
    status: str = Query("", pattern=r"^(|active|inactive)$"),
    sort: str = Query("code", pattern=r"^(code|name|status|updated_at)$"),
    direction: str = Query("asc", pattern=r"^(asc|desc)$"),
    user: SessionUser = Depends(get_session_user),
):
    _module_ready()
    if not service().has_access(user.username):
        api_error(403, "APMID_PERMISSION_REQUIRED", "APMID access is required")
    return service().list_items(user.username, page=page, page_size=page_size, search=search, status=status, sort=sort, direction=direction)


@router.post("/items")
def create_item(payload: ApmidInput, user: SessionUser = Depends(require_permission(Permission.APMID_CREATE))):
    _module_ready()
    item = _controlled(lambda: service().create(payload, user.username))
    try:
        hosts_registry().sync_apmid_environment_groups(user.username)
    except (ManagedGroupConflictError, ManagedGroupProtectedError) as error:
        service().delete(str(item["id"]), user.username)
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    return item


@router.get("/items/{apmid_id}")
def item(apmid_id: str, user: SessionUser = Depends(get_session_user)):
    _resource(user, apmid_id, ApmidResourcePermission.view)
    result = service().get(apmid_id)
    assert result is not None
    return result | {"effective_permissions": service().effective_permissions(apmid_id, user.username)}


@router.put("/items/{apmid_id}")
def update_item(apmid_id: str, payload: ApmidInput, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.update)
    previous = service().get(apmid_id)
    item = _controlled(lambda: service().update(apmid_id, payload, user.username))
    try:
        hosts_registry().sync_apmid_environment_groups(user.username)
    except (ManagedGroupConflictError, ManagedGroupProtectedError) as error:
        if previous:
            service().update(
                apmid_id,
                ApmidInput(
                    code=str(previous["code"]), name=str(previous["name"]), description=str(previous["description"]),
                    active=bool(previous["active"]), business_owner=previous.get("business_owner"),
                ),
                user.username,
            )
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    return item


@router.delete("/items/{apmid_id}")
def delete_item(apmid_id: str, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.delete)
    try:
        hosts_registry().delete_apmid(apmid_id, user.username)
    except ApmidInUseError as error:
        api_error(409, "APMID_IN_USE", "APMID is used by another resource", details={"usages": error.usages})
    except ApmidNotFoundError:
        api_error(404, "APMID_NOT_FOUND", "APMID not found")
    return {"ok": True}


@router.get("/items/{apmid_id}/members")
def members(apmid_id: str, user: SessionUser = Depends(get_session_user)):
    _resource(user, apmid_id, ApmidResourcePermission.members_view)
    return service().members(apmid_id)


@router.get("/users")
def available_users(search: str = Query("", max_length=128), user: SessionUser = Depends(get_session_user)):
    _module_ready()
    if not (service().has_access(user.username) and (
        has_permission(user.username, Permission.APMID_MEMBERS_VIEW)
        or any(ApmidResourcePermission.members_view.value in item["effective"] for item in _member_permissions(user.username))
    )):
        api_error(403, "APMID_PERMISSION_REQUIRED", "Member visibility is required")
    return [
        item for item in linux_accounts.list_users(include_system=False, search=search)
        if item.get("manageable") and not item.get("is_system")
    ][:200]


def _member_permissions(username: str) -> list[dict]:
    listing = service().list_items(username, page_size=200)["items"]
    return [service().effective_permissions(str(item["id"]), username) for item in listing]


@router.post("/items/{apmid_id}/members")
def add_members(apmid_id: str, payload: ApmidMemberCreate, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.members_manage)
    return _controlled(lambda: service().add_members(apmid_id, payload, user.username))


@router.put("/items/{apmid_id}/members/{username}")
def update_member(apmid_id: str, username: str, payload: ApmidMemberUpdate, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.members_manage)
    return _controlled(lambda: service().update_member(apmid_id, username, payload.role, user.username))


@router.delete("/items/{apmid_id}/members/{username}")
def delete_member(apmid_id: str, username: str, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.members_manage)
    _controlled(lambda: service().remove_member(apmid_id, username, user.username))
    return {"ok": True}


@router.get("/items/{apmid_id}/permissions")
def permissions(apmid_id: str, user: SessionUser = Depends(get_session_user)):
    _resource(user, apmid_id, ApmidResourcePermission.permissions_view)
    return service().permissions(apmid_id)


@router.put("/items/{apmid_id}/members/{username}/permissions")
def update_permissions(apmid_id: str, username: str, payload: ApmidPermissionUpdate, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.permissions_manage)
    return _controlled(lambda: service().set_permissions(apmid_id, username, payload, user.username))


@router.delete("/items/{apmid_id}/members/{username}/permissions")
def reset_permissions(apmid_id: str, username: str, request: Request, user: SessionUser = Depends(get_session_user)):
    _mutation(request, user, apmid_id, ApmidResourcePermission.permissions_manage)
    return _controlled(lambda: service().reset_permissions(apmid_id, username, user.username))


@router.get("/items/{apmid_id}/history")
def item_history(apmid_id: str, limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(get_session_user)):
    _resource(user, apmid_id, ApmidResourcePermission.audit_view)
    return service().history(user.username, apmid_id, limit)


@router.get("/items/{apmid_id}/relations")
def item_relations(apmid_id: str, user: SessionUser = Depends(get_session_user)):
    _resource(user, apmid_id, ApmidResourcePermission.view)
    return service().usages(apmid_id, include_managed_groups=True)


@router.get("/history")
def history(limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(Permission.APMID_AUDIT_VIEW))):
    _module_ready()
    return service().history(user.username, limit=limit)


@router.get("/backups")
def backups(user: SessionUser = Depends(require_permission(Permission.APMID_BACKUP))):
    _module_ready()
    return service().list_backups()


@router.post("/backups")
def create_backup(payload: ApmidBackupInput, user: SessionUser = Depends(require_permission(Permission.APMID_BACKUP))):
    _module_ready()
    return service().create_backup(user.username, payload.description)


@router.post("/backups/{backup_id}/restore")
def restore(backup_id: str, payload: ApmidRestoreInput, user: SessionUser = Depends(require_permission(Permission.APMID_RESTORE))):
    _module_ready()
    result = _controlled(lambda: service().restore(backup_id, user.username, payload.confirmation))
    try:
        hosts_registry().sync_apmid_environment_groups(user.username)
    except (ManagedGroupConflictError, ManagedGroupProtectedError) as error:
        service().restore(str(result["safety_backup"]), user.username, "APMID")
        api_error(409, "APMID_RESTORE_INCOMPATIBLE", str(error))
    return result
