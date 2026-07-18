"""Compatibility façade for the versioned identity/RBAC subsystem.

New code should import from ``app.identity``. Existing imports and /api/rbac
routes remain available while policies are stored in identity.sqlite3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request

from .config import get_config
from .identity.linux_accounts import is_linux_admin as is_linux_admin
from .identity.models import Role as Role, UserPolicy
from .identity.permissions import ALL_PERMISSIONS, LEGACY_PERMISSION_MAP, ROLE_PERMISSIONS, Permission, authorize, has_permission as has_permission, normalize_permissions, require_permission
from .identity.repository import IdentityRepository
from .identity.service import access_profile, service
from .security import SessionUser, get_session_user, require_csrf


PERMISSIONS = set(ALL_PERMISSIONS) | set(LEGACY_PERMISSION_MAP)


class RoleAssignment(UserPolicy):
    @classmethod
    def model_validate(cls, obj, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(obj, dict):
            obj = {**obj, "allow": normalize_permissions(list(obj.get("allow") or [])), "deny": normalize_permissions(list(obj.get("deny") or []))}
        return super().model_validate(obj, *args, **kwargs)


class RoleAssignmentRequest(RoleAssignment):
    pass


def _path() -> Path:
    return Path(get_config().paths.data_dir) / "rbac.json"


def _read() -> dict[str, RoleAssignment]:
    store = IdentityRepository(_path().parent / "identity.sqlite3", legacy_path=_path())
    return {name: RoleAssignment(username=policy.username, role=policy.role, allow=policy.allow, deny=policy.deny) for name, policy in store.user_policies().items()}


def _write(assignments: dict[str, RoleAssignment]) -> None:
    store = IdentityRepository(_path().parent / "identity.sqlite3", legacy_path=_path())
    for assignment in assignments.values():
        store.save_user_policy(UserPolicy.model_validate(assignment.model_dump(mode="json")), "compatibility")


def module_permission(module_id: str, operation: Literal["view", "operate", "configure", "install", "reinstall", "update", "uninstall", "backup", "restore", "backup_delete", "logs", "diagnostics"]) -> str:
    if module_id == "ansible-controller":
        if operation in {"view", "logs", "diagnostics"}:
            return Permission.ANSIBLE_VIEW.value
        if operation in {"install", "reinstall", "update", "uninstall"}:
            return Permission.ANSIBLE_INSTALL.value
        if operation == "backup":
            return Permission.ANSIBLE_BACKUP.value
        if operation == "restore":
            return Permission.ANSIBLE_RESTORE.value
        return Permission.ANSIBLE_CONFIGURE.value
    if operation in {"install", "reinstall", "update", "uninstall"}:
        return {"install": Permission.MODULES_INSTALL.value, "reinstall": Permission.MODULES_UPDATE.value, "update": Permission.MODULES_UPDATE.value, "uninstall": Permission.MODULES_UNINSTALL.value}[operation]
    if operation == "backup_delete":
        return Permission.MODULES_BACKUP_DELETE.value
    if module_id == "linux-updates":
        return Permission.UPDATES_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.UPDATES_APPLY.value
    if module_id == "docker":
        if operation in {"view", "logs", "diagnostics"}:
            return Permission.DOCKER_VIEW.value
        return Permission.DOCKER_COMPOSE.value if operation == "configure" else Permission.DOCKER_CONTAINERS.value
    if module_id in {"pihole", "adguard-home"}:
        return Permission.DNS_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.DNS_CONFIGURE.value
    if module_id in {"postgresql", "mariadb", "redis"}:
        if operation in {"view", "logs", "diagnostics"}:
            return Permission.DATABASES_VIEW.value
        if operation == "restore":
            return Permission.DATABASES_RESTORE.value
        if operation == "backup":
            return Permission.DATABASES_BACKUP.value
        return Permission.DATABASES_CONFIGURE.value
    if module_id == "home-assistant":
        return Permission.HOMEASSISTANT_VIEW.value if operation in {"view", "logs", "diagnostics"} else Permission.HOMEASSISTANT_OPERATE.value
    return {
        "view": Permission.MODULES_VIEW.value,
        "operate": Permission.MODULES_CONFIGURE.value,
        "configure": Permission.MODULES_CONFIGURE.value,
        "install": Permission.MODULES_INSTALL.value,
        "update": Permission.MODULES_UPDATE.value,
        "uninstall": Permission.MODULES_UNINSTALL.value,
        "backup": Permission.MODULES_BACKUP_CREATE.value,
        "restore": Permission.MODULES_BACKUP_RESTORE.value,
        "backup_delete": Permission.MODULES_BACKUP_DELETE.value,
        "logs": Permission.MODULES_LOGS.value,
        "diagnostics": Permission.MODULES_DIAGNOSTICS.value,
    }[operation]


def current_user(request: Request) -> SessionUser:
    return get_session_user(request)


def mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


router = APIRouter(prefix="/api/rbac", tags=["rbac-compatibility"])


@router.get("/me")
def rbac_me(user: SessionUser = Depends(current_user)):
    return access_profile(user.username)


@router.get("/roles")
def roles(user: SessionUser = Depends(require_permission(Permission.ACCESS_VIEW))):
    return {"roles": {role.value: sorted(values) for role, values in ROLE_PERMISSIONS.items()}, "permissions": sorted(ALL_PERMISSIONS)}


@router.get("/assignments")
def assignments(user: SessionUser = Depends(require_permission(Permission.USERS_VIEW))):
    return service().users(include_system=True)


@router.put("/assignments/{username}")
def save_assignment(username: str, payload: RoleAssignmentRequest, request: Request, user: SessionUser = Depends(require_permission(Permission.ACCESS_MANAGE_USER_PERMISSIONS))):
    authorize(user, Permission.ACCESS_MANAGE_ROLES)
    if username != payload.username:
        from .identity.exceptions import identity_error

        identity_error(400, "INVALID_USERNAME", "Assignment username does not match the route", field="username")
    from .identity.models import UserPolicyRequest

    return service().save_user_policy(username, UserPolicyRequest(role=payload.role, allow=payload.allow, deny=payload.deny), user.username)
