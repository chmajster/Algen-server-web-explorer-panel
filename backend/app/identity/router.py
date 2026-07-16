from __future__ import annotations

import time
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, Query, Request

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..auth import authenticate
from ..config import get_config
from ..security import SessionUser, get_session_user
from .exceptions import identity_error
from .models import AdminCredential, GroupCreateRequest, GroupMemberRequest, GroupPatchRequest, GroupPolicyRequest, PasswordChangeRequest, Role, UserCreateRequest, UserDeleteRequest, UserPatchRequest, UserPolicyRequest, UserQuotaRequest
from .permissions import PERMISSION_REGISTRY, Permission, ROLE_PERMISSIONS, authorize, require_permission
from .repository import repository
from .service import service


router = APIRouter(tags=["identity"])


class IdentityRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.time()
        window = self._attempts[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= get_config().security.rate_limit_admin_per_minute:
            identity_error(429, "ADMIN_RATE_LIMIT", "Too many administrative operations")
        window.append(now)


identity_rate_limiter = IdentityRateLimiter()


def _reauth(request: Request, user: SessionUser, password: str, action: str, target: str = "") -> None:
    client = request.client.host if request.client else "unknown"
    identity_rate_limiter.check(f"{client}:{user.username}:{action}")
    try:
        authenticate(user.username, password)
    except Exception as error:
        record_activity(ActivityCategory.administration, action, user.username, target=target, status=ActivityStatus.failure, summary="PAM_REAUTHENTICATION_FAILED", source="identity")
        raise error


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
    _reauth(request, user, payload.admin_password, "user_create", payload.username)
    return service().create_user(payload, user.username)


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
    _reauth(request, user, payload.admin_password, "user_update", username)
    return service().update_user(username, payload, user.username)


@router.delete("/api/identity/users/{username}")
@router.delete("/api/admin/users/{username}")
def identity_user_delete(username: str, payload: UserDeleteRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_DELETE))):
    if not payload.confirm:
        identity_error(400, "CONFIRMATION_REQUIRED", "Explicit confirmation is required")
    _reauth(request, user, payload.admin_password, "user_delete", username)
    service().delete_user(username, user.username, current_username=user.username, remove_home=payload.remove_home)
    return {"ok": True}


@router.post("/api/identity/users/{username}/lock")
@router.post("/api/admin/users/{username}/lock")
def identity_user_lock(username: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_LOCK))):
    _reauth(request, user, payload.admin_password, "user_lock", username)
    service().set_user_lock(username, user.username, current_username=user.username, locked=True)
    return {"ok": True}


@router.post("/api/identity/users/{username}/unlock")
@router.post("/api/admin/users/{username}/unlock")
def identity_user_unlock(username: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_UNLOCK))):
    _reauth(request, user, payload.admin_password, "user_unlock", username)
    service().set_user_lock(username, user.username, current_username=user.username, locked=False)
    return {"ok": True}


@router.post("/api/identity/users/{username}/password")
@router.post("/api/admin/users/{username}/change-password")
def identity_user_password(username: str, payload: PasswordChangeRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_CHANGE_PASSWORD))):
    _reauth(request, user, payload.admin_password, "user_password_change", username)
    service().change_user_password(username, payload.new_password, payload.force_change, user.username)
    return {"ok": True}


@router.post("/api/identity/users/{username}/quota")
@router.post("/api/admin/users/{username}/quota")
def identity_user_quota(username: str, payload: UserQuotaRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.USERS_MANAGE_QUOTA))):
    _reauth(request, user, payload.admin_password, "user_quota_update", username)
    service().set_user_quota(username, payload, user.username)
    return {"ok": True, "quota_supported": True}


@router.put("/api/identity/users/{username}/policy")
def identity_user_policy(username: str, payload: UserPolicyRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.ACCESS_MANAGE_USER_PERMISSIONS))):
    if service().user(username)["role"] != payload.role.value:
        authorize(user, Permission.ACCESS_MANAGE_ROLES)
    _reauth(request, user, payload.admin_password, "user_policy_update", username)
    return service().save_user_policy(username, payload, user.username)


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
    _reauth(request, user, payload.admin_password, "group_create", payload.groupname)
    return service().create_group(payload, user.username)


@router.get("/api/identity/groups/{groupname}")
def identity_group_get(groupname: str, user: SessionUser = Depends(require_permission(Permission.GROUPS_VIEW))):
    return service().group(groupname)


@router.patch("/api/identity/groups/{groupname}")
@router.patch("/api/admin/groups/{groupname}")
def identity_group_patch(groupname: str, payload: GroupPatchRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_RENAME))):
    _reauth(request, user, payload.admin_password, "group_rename", groupname)
    return service().rename_group(groupname, payload.new_name, user.username)


@router.delete("/api/identity/groups/{groupname}")
@router.delete("/api/admin/groups/{groupname}")
def identity_group_delete(groupname: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_DELETE))):
    if not payload.confirm:
        identity_error(400, "CONFIRMATION_REQUIRED", "Explicit confirmation is required")
    _reauth(request, user, payload.admin_password, "group_delete", groupname)
    service().delete_group(groupname, user.username)
    return {"ok": True}


@router.post("/api/identity/groups/{groupname}/members")
@router.post("/api/admin/groups/{groupname}/members")
def identity_group_member_add(groupname: str, payload: GroupMemberRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_MANAGE_MEMBERS))):
    _reauth(request, user, payload.admin_password, "group_member_add", f"{groupname}:{payload.username}")
    return service().set_group_member(groupname, payload.username, user.username, True)


@router.delete("/api/identity/groups/{groupname}/members/{username}")
@router.delete("/api/admin/groups/{groupname}/members/{username}")
def identity_group_member_remove(groupname: str, username: str, payload: AdminCredential, request: Request, user: SessionUser = Depends(require_permission(Permission.GROUPS_MANAGE_MEMBERS))):
    _reauth(request, user, payload.admin_password, "group_member_remove", f"{groupname}:{username}")
    return service().set_group_member(groupname, username, user.username, False)


@router.put("/api/identity/groups/{groupname}/policy")
def identity_group_policy(groupname: str, payload: GroupPolicyRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.ACCESS_MANAGE_GROUP_PERMISSIONS))):
    _reauth(request, user, payload.admin_password, "group_policy_update", groupname)
    return service().save_group_policy(groupname, payload, user.username)


@router.get("/api/admin/users")
def legacy_admin_users(user: SessionUser = Depends(require_permission(Permission.USERS_VIEW))):
    return service().users()


@router.get("/api/admin/groups")
def legacy_admin_groups(user: SessionUser = Depends(require_permission(Permission.GROUPS_VIEW))):
    return service().groups(include_system=True)
