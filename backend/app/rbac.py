from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .identity.linux_accounts import is_linux_admin as is_linux_admin
from .identity.models import Role as Role, UserPolicyRequest
from .identity.permission_service import Resource, permission_service
from .identity.permissions import ALL_PERMISSIONS, Permission
from .identity.service import access_profile, service as legacy_identity_service
from .security import SessionUser, get_session_user, require_csrf

PERMISSIONS = set(ALL_PERMISSIONS)


class PermissionGrantInput(BaseModel):
    permission: str
    effect: Literal["allow", "deny"] = "allow"
    resource_type: str = Field(default="global", max_length=128)
    resource_id: str = Field(default="*", max_length=1024)
    scope: str = Field(default="*", max_length=2048)


class RoleInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    active: bool = True
    permissions: list[PermissionGrantInput] = Field(default_factory=list, max_length=1024)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2048)
    active: bool | None = None
    permissions: list[PermissionGrantInput] | None = Field(default=None, max_length=1024)


class GroupInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    active: bool = True
    source: Literal["local", "ldap"] = "local"
    external_id: str = Field(default="", max_length=2048)
    distinguished_name: str = Field(default="", max_length=4096)
    role_ids: list[str] = Field(default_factory=list, max_length=256)


class GroupMembersInput(BaseModel):
    members: list[dict[str, str]] = Field(default_factory=list, max_length=10000)


class UserRoleInput(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    auth_provider: Literal["local", "pam", "ldap"] = "pam"
    identity_id: str = Field(default="", max_length=2048)
    role_id: str


class LegacyAssignmentInput(BaseModel):
    username: str
    role: Role = Role.user
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class PolicySubjectInput(BaseModel):
    subject_type: Literal["user", "group", "external_group", "provider"]
    subject_id: str = Field(min_length=1, max_length=4096)


class PolicyInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    active: bool = True
    effect: Literal["allow", "deny"] = "allow"
    permission: str
    resource_type: str = Field(default="global", max_length=128)
    resource_id: str = Field(default="*", max_length=1024)
    scope: str = Field(default="*", max_length=2048)
    conditions: dict[str, Any] = Field(default_factory=dict)
    subjects: list[PolicySubjectInput] = Field(default_factory=list, max_length=512)


class ExplainInput(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    auth_provider: Literal["local", "pam", "ldap"] = "pam"
    identity_id: str = Field(default="", max_length=2048)
    permission: str
    resource_type: str = "global"
    resource_id: str = "*"
    scope: str = "*"


class ExternalMappingInput(BaseModel):
    external_group_id: str
    role_id: str


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _migrate_legacy_assignment(user: SessionUser) -> bool:
    """One-way migration of the old admin/operator/auditor/user role into RBAC v2."""
    profile = access_profile(user.username)
    role = str(profile.get("role") or "user")
    role_name = {"admin": "Administrator", "operator": "Operator", "auditor": "Auditor", "user": "User"}.get(role, "User")
    role_id = f"system:{role_name.casefold().replace(' ', '-')}"
    central = permission_service()
    if any(source.source_type == "direct-role" and source.source_id == role_id for source in central.sources(user)):
        return False
    central.repository.assign_user_role(user, role_id, "legacy-migration")
    central.invalidate()
    return True


def _authorize_user(request: Request, permission: str, *, mutate: bool) -> SessionUser:
    user = get_session_user(request)
    if mutate:
        require_csrf(request, user)
    central = permission_service()
    if not central.can(user, permission) and _migrate_legacy_assignment(user):
        central.invalidate()
    central.authorize(user, permission)
    return user


def rbac_read(request: Request) -> SessionUser:
    return _authorize_user(request, "rbac.read", mutate=False)


def rbac_write(request: Request) -> SessionUser:
    return _authorize_user(request, "rbac.manage", mutate=True)


def current_user(request: Request) -> SessionUser:
    return get_session_user(request)


def mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def has_permission(username: str, permission: str | Permission) -> bool:
    user = SessionUser(username=username, csrf_token="", auth_provider="pam", identity_id=username)
    expected = str(getattr(permission, "value", permission))
    central = permission_service()
    if central.can(user, expected):
        return True
    return _migrate_legacy_assignment(user) and central.can(user, expected)


def authorize(user: SessionUser, permission: str | Permission, resource: Resource | None = None) -> None:
    expected = str(getattr(permission, "value", permission))
    central = permission_service()
    if not central.can(user, expected) and _migrate_legacy_assignment(user):
        central.invalidate()
    central.authorize(user, expected, resource)


def require_permission(permission: str | Permission, *, mutating: bool | None = None):
    expected = str(getattr(permission, "value", permission))
    def dependency(request: Request) -> SessionUser:
        user = get_session_user(request)
        if mutating is not False and request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_csrf(request, user)
        authorize(user, expected)
        return user
    return dependency


def module_permission(module_id: str, operation: Literal["view", "operate", "configure", "install", "reinstall", "update", "uninstall", "backup", "restore", "backup_delete", "logs", "diagnostics"]) -> str:
    if module_id == "ansible-controller":
        if operation in {"view", "logs", "diagnostics"}: return Permission.ANSIBLE_VIEW.value
        if operation in {"install", "reinstall", "update", "uninstall"}: return Permission.ANSIBLE_INSTALL.value
        if operation == "backup": return Permission.ANSIBLE_BACKUP.value
        if operation == "restore": return Permission.ANSIBLE_RESTORE.value
        return Permission.ANSIBLE_CONFIGURE.value
    if operation in {"install", "reinstall", "update", "uninstall"}:
        return {"install": Permission.MODULES_INSTALL.value, "reinstall": Permission.MODULES_UPDATE.value, "update": Permission.MODULES_UPDATE.value, "uninstall": Permission.MODULES_UNINSTALL.value}[operation]
    if operation == "backup_delete": return Permission.MODULES_BACKUP_DELETE.value
    if module_id == "linux-updates": return Permission.UPDATES_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.UPDATES_APPLY.value
    if module_id == "docker": return Permission.DOCKER_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.DOCKER_COMPOSE.value if operation == "configure" else Permission.DOCKER_CONTAINERS.value
    if module_id in {"pihole", "adguard-home"}: return Permission.DNS_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.DNS_CONFIGURE.value
    if module_id in {"postgresql", "mariadb", "redis"}:
        if operation in {"view", "logs", "diagnostics"}: return Permission.DATABASES_VIEW.value
        if operation == "restore": return Permission.DATABASES_RESTORE.value
        if operation == "backup": return Permission.DATABASES_BACKUP.value
        return Permission.DATABASES_CONFIGURE.value
    if module_id == "home-assistant": return Permission.HOMEASSISTANT_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.HOMEASSISTANT_OPERATE.value
    return {"view": Permission.MODULES_VIEW.value,"operate": Permission.MODULES_CONFIGURE.value,"configure": Permission.MODULES_CONFIGURE.value,"install": Permission.MODULES_INSTALL.value,"update": Permission.MODULES_UPDATE.value,"uninstall": Permission.MODULES_UNINSTALL.value,"backup": Permission.MODULES_BACKUP_CREATE.value,"restore": Permission.MODULES_BACKUP_RESTORE.value,"backup_delete": Permission.MODULES_BACKUP_DELETE.value,"logs": Permission.MODULES_LOGS.value,"diagnostics": Permission.MODULES_DIAGNOSTICS.value}[operation]


router = APIRouter(prefix="/api/rbac", tags=["rbac"])


@router.get("/me")
def rbac_me(user: SessionUser = Depends(current_user)):
    if not permission_service().sources(user):
        _migrate_legacy_assignment(user)
    return permission_service().effective(user)


@router.get("/permissions")
def permissions(_user: SessionUser = Depends(rbac_read)):
    return {"items": permission_service().repository.permissions()}


@router.get("/roles")
def roles(_user: SessionUser = Depends(rbac_read)):
    return {"items": permission_service().repository.roles()}


@router.get("/roles/{role_id}")
def role(role_id: str, _user: SessionUser = Depends(rbac_read)):
    return permission_service().repository.role(role_id)


@router.post("/roles")
def create_role(payload: RoleInput, request: Request, user: SessionUser = Depends(rbac_write)):
    result = permission_service().repository.create_role(payload.model_dump(), user.username, _ip(request)); permission_service().invalidate(); return result


@router.put("/roles/{role_id}")
def update_role(role_id: str, payload: RolePatch, request: Request, user: SessionUser = Depends(rbac_write)):
    result = permission_service().repository.update_role(role_id, payload.model_dump(exclude_none=True), user.username, _ip(request)); permission_service().invalidate(); return result


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, request: Request, user: SessionUser = Depends(rbac_write)):
    permission_service().repository.delete_role(role_id, user.username, _ip(request)); permission_service().invalidate(); return {"ok": True}


@router.post("/roles/{role_id}/duplicate")
def duplicate_role(role_id: str, request: Request, user: SessionUser = Depends(rbac_write)):
    source = permission_service().repository.role(role_id)
    payload = {"name": f"{source['name']} Copy", "description": source["description"], "active": True, "permissions": source["permissions"]}
    result = permission_service().repository.create_role(payload, user.username, _ip(request)); permission_service().invalidate(); return result


@router.get("/groups")
def groups(_user: SessionUser = Depends(rbac_read)):
    return {"items": permission_service().repository.groups()}


@router.post("/groups")
def create_group(payload: GroupInput, request: Request, user: SessionUser = Depends(rbac_write)):
    result = permission_service().repository.create_group(payload.model_dump(), user.username, _ip(request)); permission_service().invalidate(); return result


@router.put("/groups/{group_id}/members")
def set_group_members(group_id: str, payload: GroupMembersInput, request: Request, user: SessionUser = Depends(rbac_write)):
    permission_service().repository.set_group_members(group_id, payload.members, user.username, _ip(request)); permission_service().invalidate(); return {"ok": True}


@router.post("/users/{username}/roles")
def assign_user_role(username: str, payload: UserRoleInput, request: Request, user: SessionUser = Depends(rbac_write)):
    if username != payload.username: raise HTTPException(400, "Username does not match route")
    subject = SessionUser(username=payload.username, csrf_token="", auth_provider=payload.auth_provider, identity_id=payload.identity_id or payload.username)
    permission_service().repository.assign_user_role(subject, payload.role_id, user.username, _ip(request)); permission_service().invalidate(); return {"ok": True}


@router.delete("/users/{username}/roles/{role_id}")
def revoke_user_role(request: Request, username: str, role_id: str, auth_provider: Literal["local","pam","ldap"] = "pam", identity_id: str = "", user: SessionUser = Depends(rbac_write)):
    subject = SessionUser(username=username, csrf_token="", auth_provider=auth_provider, identity_id=identity_id or username)
    permission_service().repository.revoke_user_role(subject, role_id, user.username, _ip(request)); permission_service().invalidate(); return {"ok": True}


@router.get("/users/{username}/effective-permissions")
def effective_permissions(username: str, auth_provider: Literal["local","pam","ldap"] = "pam", identity_id: str = "", _user: SessionUser = Depends(rbac_read)):
    return permission_service().effective(SessionUser(username=username,csrf_token="",auth_provider=auth_provider,identity_id=identity_id or username))


@router.get("/policies")
def policies(_user: SessionUser = Depends(rbac_read)):
    return {"items": permission_service().repository.policies()}


@router.post("/policies")
def create_policy(payload: PolicyInput, request: Request, user: SessionUser = Depends(rbac_write)):
    result = permission_service().repository.create_policy(payload.model_dump(),user.username,_ip(request)); permission_service().invalidate(); return result


@router.post("/simulate")
def simulate(payload: ExplainInput, _user: SessionUser = Depends(rbac_read)):
    subject=SessionUser(username=payload.username,csrf_token="",auth_provider=payload.auth_provider,identity_id=payload.identity_id or payload.username)
    return permission_service().explain(subject,payload.permission,Resource(payload.resource_type,payload.resource_id,payload.scope)).as_dict()


@router.get("/external-groups")
def external_groups(_user: SessionUser = Depends(rbac_read)):
    return {"items": permission_service().repository.external_groups()}


@router.post("/external-group-mappings")
def map_external_group(payload: ExternalMappingInput, request: Request, user: SessionUser = Depends(rbac_write)):
    permission_service().repository.map_external_group_role(payload.external_group_id,payload.role_id,user.username,_ip(request)); permission_service().invalidate(); return {"ok": True}


@router.get("/audit")
def audit(limit: int = 200, _user: SessionUser = Depends(rbac_read)):
    return {"items": permission_service().repository.audit(limit)}


# Legacy API kept only as a migration façade. It writes the old policy once and
# immediately projects the selected role into the central RBAC graph.
@router.get("/assignments")
def legacy_assignments(_user: SessionUser = Depends(rbac_read)):
    return legacy_identity_service().users(include_system=True)


@router.put("/assignments/{username}")
def legacy_save_assignment(username: str, payload: LegacyAssignmentInput, request: Request, user: SessionUser = Depends(rbac_write)):
    if username != payload.username:
        raise HTTPException(400, "Assignment username does not match route")
    legacy_identity_service().save_user_policy(username, UserPolicyRequest(role=payload.role, allow=payload.allow, deny=payload.deny), user.username)
    subject = SessionUser(username=username, csrf_token="", auth_provider="pam", identity_id=username)
    _migrate_legacy_assignment(subject)
    permission_service().invalidate()
    return legacy_identity_service().user(username)
