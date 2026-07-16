from __future__ import annotations

from typing import Callable, TypeVar
from fastapi import APIRouter, Depends, Query, Request

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..security import SessionUser, get_session_user
from .exceptions import identity_error
from .models import AdminCredential, GroupCreateRequest, GroupMemberRequest, GroupPatchRequest, GroupPolicyRequest, PasswordChangeRequest, Role, UserCreateRequest, UserDeleteRequest, UserPatchRequest, UserPolicyRequest, UserQuotaRequest
from .permissions import PERMISSION_REGISTRY, Permission, ROLE_PERMISSIONS, authorize, require_permission
from .repository import repository
from .service import service


router = APIRouter(tags=["identity"])
ResultT = TypeVar("ResultT")


def _execute(action: str, actor: str, target: str, operation: Callable[[], ResultT]) -> ResultT:
    """Audit a controlled failure without serializing request bodies or secrets."""
    try:
        return operation()
    except Exception as error:
        detail = getattr(error, "detail", None)
        code = str(detail.get("code", "IDENTITY_OPERATION_FAILED")) if isinstance(detail, dict) else "IDENTITY_OPERATION_FAILED"
        record_activity(ActivityCategory.administration, action, actor, target=target, status=ActivityStatus.failure, summary=code, source="identity")
        raise


@router.get("/api/identity/me")
def identity_me(user: SessionUser = Depends(get_session_user)):
    return service().access_profile(user.username)


@router.get("/api/identity/permissions")
def identity_permissions(user: SessionUser = Depends(require_permission(Permission.ACCESS_VIEW))):
    return [item.model_dump(mode="json") for item in PERMISSION_REGISTRY.values()]


@router.get("/api/identity/roles")
def identity_roles(user: SessionUser = Depends(require_permission(Permission.ACCESS_VIEW))):
    return {"roles": {role.value: sorted(values) for role, values in ROLE_PERMISSIONS.items()}, "permissions": [item.model_dump(mode="json") for item in PERMISSION_REGISTRY.values()]}


@router.get("/api/identity/history")
def identity_history(limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(Permission.ACCESS_VIEW))):
    return [item.model_dump(mode="json") for item in repository().changes(limit)]


@router.get("/api/identity/users")
def identity_users(
    search: str = Query(default="", max_length=128),
    role: str = Query(default="", pattern=r"^(|admin|operator|auditor|user)$"),
    status: str = Query(default="", pattern=r"^(|active|locked)$"),
    include_system: bool = False,
    user: SessionUser = Depends(require_permission(Permission.USERS_VIEW)),
):
    return service().users(include_system=include_system, search=search, role=role, status=status)


@router.post("/api/identity/users")
@router.post("/api/admin/users")
def identity_user_create(payload: UserCreateRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_CREATE))):
    if payload.allow or payload.deny:
        authorize(user, Permission.ACCESS_MANAGE_USER_PERMISSIONS)
    if payload.role != Role.user:
        authorize(user, Permission.ACCESS_MANAGE_ROLES)
    return _execute("user_create", user.username, payload.username, lambda: service().create_user(payload, user.username))


@router.get("/api/identity/users/{username}")
@router.get("/api/admin/users/{username}")
def identity_user_get(username: str, user: SessionUser = Depends(require_permission(Permission.USERS_VIEW))):
    return service().user(username)


@router.patch("/api/identity/users/{username}")
@router.patch("/api/admin/users/{username}")
def identity_user_patch(username: str, payload: UserPatchRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_UPDATE))):
    if payload.new_username and payload.new_username != username:
        authorize(user, Permission.USERS_RENAME)
    if payload.groups_add or payload.groups_remove:
        authorize(user, Permission.USERS_MANAGE_GROUPS)
    return _execute("user_update", user.username, username, lambda: service().update_user(username, payload, user.username))


@router.delete("/api/identity/users/{username}")
@router.delete("/api/admin/users/{username}")
def identity_user_delete(username: str, payload: UserDeleteRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_DELETE))):
    if not payload.confirm:
        identity_error(400, "CONFIRMATION_REQUIRED", "Explicit confirmation is required")
    _execute("user_delete", user.username, username, lambda: service().delete_user(username, user.username, current_username=user.username, remove_home=payload.remove_home))
    return {"ok": True}


@router.post("/api/identity/users/{username}/lock")
@router.post("/api/admin/users/{username}/lock")
def identity_user_lock(username: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_LOCK))):
    _execute("user_lock", user.username, username, lambda: service().set_user_lock(username, user.username, current_username=user.username, locked=True))
    return {"ok": True}


@router.post("/api/identity/users/{username}/unlock")
@router.post("/api/admin/users/{username}/unlock")
def identity_user_unlock(username: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_UNLOCK))):
    _execute("user_unlock", user.username, username, lambda: service().set_user_lock(username, user.username, current_username=user.username, locked=False))
    return {"ok": True}


@router.post("/api/identity/users/{username}/password")
@router.post("/api/admin/users/{username}/change-password")
def identity_user_password(username: str, payload: PasswordChangeRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_CHANGE_PASSWORD))):
    _execute("user_password_change", user.username, username, lambda: service().change_user_password(username, payload.new_password, payload.force_change, user.username))
    return {"ok": True}


@router.post("/api/identity/users/{username}/quota")
@router.post("/api/admin/users/{username}/quota")
def identity_user_quota(username: str, payload: UserQuotaRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_MANAGE_QUOTA))):
    _execute("user_quota_update", user.username, username, lambda: service().set_user_quota(username, payload, user.username))
    return {"ok": True, "quota_supported": True}


@router.put("/api/identity/users/{username}/policy")
def identity_user_policy(username: str, payload: UserPolicyRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.ACCESS_MANAGE_USER_PERMISSIONS))):
    if service().user(username)["role"] != payload.role.value:
        authorize(user, Permission.ACCESS_MANAGE_ROLES)
    return _execute("user_policy_update", user.username, username, lambda: service().save_user_policy(username, payload, user.username))


@router.get("/api/identity/users/{username}/effective-permissions")
def identity_user_effective(username: str, user: SessionUser = Depends(require_permission(Permission.USERS_VIEW))):
    return service().access_profile(username)


@router.get("/api/identity/groups")
def identity_groups(search: str = Query(default="", max_length=128), include_system: bool = False, user: SessionUser = Depends(require_permission(Permission.GROUPS_VIEW))):
    return service().groups(include_system=include_system, search=search)


@router.post("/api/identity/groups")
@router.post("/api/admin/groups")
def identity_group_create(payload: GroupCreateRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_CREATE))):
    if payload.allow or payload.deny:
        authorize(user, Permission.ACCESS_MANAGE_GROUP_PERMISSIONS)
    return _execute("group_create", user.username, payload.groupname, lambda: service().create_group(payload, user.username))


@router.get("/api/identity/groups/{groupname}")
def identity_group_get(groupname: str, user: SessionUser = Depends(require_permission(Permission.GROUPS_VIEW))):
    return service().group(groupname)


@router.patch("/api/identity/groups/{groupname}")
@router.patch("/api/admin/groups/{groupname}")
def identity_group_patch(groupname: str, payload: GroupPatchRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_RENAME))):
    return _execute("group_rename", user.username, groupname, lambda: service().rename_group(groupname, payload.new_name, user.username))


@router.delete("/api/identity/groups/{groupname}")
@router.delete("/api/admin/groups/{groupname}")
def identity_group_delete(groupname: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_DELETE))):
    if not payload.confirm:
        identity_error(400, "CONFIRMATION_REQUIRED", "Explicit confirmation is required")
    _execute("group_delete", user.username, groupname, lambda: service().delete_group(groupname, user.username))
    return {"ok": True}


@router.post("/api/identity/groups/{groupname}/members")
@router.post("/api/admin/groups/{groupname}/members")
def identity_group_member_add(groupname: str, payload: GroupMemberRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_MANAGE_MEMBERS))):
    return _execute("group_member_add", user.username, f"{groupname}:{payload.username}", lambda: service().set_group_member(groupname, payload.username, user.username, True))


@router.delete("/api/identity/groups/{groupname}/members/{username}")
@router.delete("/api/admin/groups/{groupname}/members/{username}")
def identity_group_member_remove(groupname: str, username: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_MANAGE_MEMBERS))):
    return _execute("group_member_remove", user.username, f"{groupname}:{username}", lambda: service().set_group_member(groupname, username, user.username, False))


@router.put("/api/identity/groups/{groupname}/policy")
def identity_group_policy(groupname: str, payload: GroupPolicyRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.ACCESS_MANAGE_GROUP_PERMISSIONS))):
    return _execute("group_policy_update", user.username, groupname, lambda: service().save_group_policy(groupname, payload, user.username))


@router.get("/api/admin/users")
def legacy_admin_users(user: SessionUser = Depends(require_permission(Permission.USERS_VIEW))):
    return service().users()


@router.get("/api/admin/groups")
def legacy_admin_groups(user: SessionUser = Depends(require_permission(Permission.GROUPS_VIEW))):
    return service().groups(include_system=True)
