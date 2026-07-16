from __future__ import annotations

import json
import os
import pwd
import grp
import re
import threading
from enum import StrEnum
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .activity import ActivityCategory, record_activity
from .audit import logger
from .auth import authenticate
from .config import get_config
from .security import SessionUser, get_session_user, require_csrf


class Role(StrEnum):
    admin = "admin"
    operator = "operator"
    auditor = "auditor"
    user = "user"


PERMISSIONS = {
    "apps.files",
    "apps.settings",
    "apps.monitor",
    "apps.transfers",
    "modules.view",
    "modules.operate",
    "modules.configure",
    "modules.install",
    "updates.view",
    "updates.apply",
    "docker.view",
    "docker.operate",
    "docker.compose",
    "dns.view",
    "dns.configure",
    "databases.view",
    "databases.backup",
    "databases.restore",
    "homeassistant.view",
    "homeassistant.operate",
    "rbac.manage",
    "audit.view",
    "widgets.manage",
}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.admin: set(PERMISSIONS),
    Role.operator: {
        "apps.files", "apps.settings", "apps.monitor", "apps.transfers", "modules.view", "modules.operate", "modules.configure",
        "updates.view", "updates.apply", "docker.view", "docker.operate", "docker.compose", "dns.view", "dns.configure",
        "databases.view", "databases.backup", "databases.restore", "homeassistant.view", "homeassistant.operate", "widgets.manage",
    },
    Role.auditor: {
        "apps.files", "apps.settings", "apps.monitor", "apps.transfers", "modules.view", "updates.view", "docker.view", "dns.view",
        "databases.view", "homeassistant.view", "audit.view", "widgets.manage",
    },
    Role.user: {"apps.files", "apps.settings", "apps.monitor", "apps.transfers", "widgets.manage"},
}

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$", re.IGNORECASE)
_lock = threading.RLock()


class RoleAssignment(BaseModel):
    username: str
    role: Role = Role.user
    allow: list[str] = Field(default_factory=list, max_length=64)
    deny: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("invalid local username")
        return value

    @field_validator("allow", "deny")
    @classmethod
    def valid_permissions(cls, values: list[str]) -> list[str]:
        if any(item not in PERMISSIONS for item in values):
            raise ValueError("unknown permission")
        return list(dict.fromkeys(values))


class RoleAssignmentRequest(RoleAssignment):
    admin_password: str = Field(min_length=1, max_length=1024)


def _path() -> Path:
    return Path(get_config().paths.data_dir) / "rbac.json"


def _read() -> dict[str, RoleAssignment]:
    path = _path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {name: RoleAssignment.model_validate({"username": name, **value}) for name, value in raw.items() if isinstance(value, dict)}
    except (OSError, ValueError):
        logger.exception("rbac_read_failed path=%s", path)
        return {}


def _write(assignments: dict[str, RoleAssignment]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {name: item.model_dump(mode="json", exclude={"username"}) for name, item in sorted(assignments.items())}
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def is_linux_admin(username: str) -> bool:
    try:
        user = pwd.getpwnam(username)
        if user.pw_uid == 0:
            return True
        groups = {item.gr_name for item in grp.getgrall() if username in item.gr_mem or item.gr_gid == user.pw_gid}
    except KeyError:
        return False
    return bool(groups & {"sudo", "wheel"})


def access_profile(username: str) -> dict[str, object]:
    if is_linux_admin(username):
        role = Role.admin
        permissions = set(ROLE_PERMISSIONS[role])
        source = "linux-admin"
    else:
        with _lock:
            assignment = _read().get(username, RoleAssignment(username=username))
        role = assignment.role
        permissions = (set(ROLE_PERMISSIONS[role]) | set(assignment.allow)) - set(assignment.deny)
        source = "assignment" if assignment.role != Role.user or assignment.allow or assignment.deny else "default"
    return {"role": role.value, "permissions": sorted(permissions), "role_source": source, "is_admin": role == Role.admin}


def has_permission(username: str, permission: str) -> bool:
    if permission not in PERMISSIONS:
        return False
    permissions = access_profile(username)["permissions"]
    return isinstance(permissions, list) and permission in permissions


def authorize(user: SessionUser, permission: str) -> None:
    if not has_permission(user.username, permission):
        raise HTTPException(403, {"code": "PERMISSION_REQUIRED", "message": "The operation is not allowed for this role", "permission": permission})


def current_user(request: Request) -> SessionUser:
    return get_session_user(request)


def mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


MODULE_PERMISSION_PREFIX: dict[str, str] = {
    "linux-updates": "updates",
    "docker": "docker",
    "pihole": "dns",
    "adguard-home": "dns",
    "postgresql": "databases",
    "mariadb": "databases",
    "redis": "databases",
    "home-assistant": "homeassistant",
}


def module_permission(module_id: str, operation: Literal["view", "operate", "configure", "install", "backup", "restore"]) -> str:
    prefix = MODULE_PERMISSION_PREFIX.get(module_id, "modules")
    if operation == "view":
        return f"{prefix}.view" if f"{prefix}.view" in PERMISSIONS else "modules.view"
    if operation == "install":
        return "modules.install"
    if prefix == "updates":
        return "updates.apply"
    if prefix == "docker":
        return "docker.compose" if operation == "configure" else "docker.operate"
    if prefix == "dns":
        return "dns.configure"
    if prefix == "databases":
        return "databases.restore" if operation == "restore" else "databases.backup" if operation == "backup" else "modules.operate"
    if prefix == "homeassistant":
        return "homeassistant.operate"
    return "modules.configure" if operation == "configure" else "modules.operate"


router = APIRouter(prefix="/api/rbac", tags=["rbac"])


@router.get("/me")
def rbac_me(user: SessionUser = Depends(current_user)):
    return access_profile(user.username)


@router.get("/roles")
def roles(user: SessionUser = Depends(current_user)):
    authorize(user, "rbac.manage")
    return {"roles": {role.value: sorted(permissions) for role, permissions in ROLE_PERMISSIONS.items()}, "permissions": sorted(PERMISSIONS)}


@router.get("/assignments")
def assignments(user: SessionUser = Depends(current_user)):
    authorize(user, "rbac.manage")
    with _lock:
        configured = _read()
    result = []
    for entry in pwd.getpwall():
        assignment = configured.get(entry.pw_name, RoleAssignment(username=entry.pw_name))
        profile = access_profile(entry.pw_name)
        result.append({**assignment.model_dump(mode="json"), **profile, "uid": entry.pw_uid})
    return result


@router.put("/assignments/{username}")
def save_assignment(username: str, payload: RoleAssignmentRequest, user: SessionUser = Depends(mutating_user)):
    authorize(user, "rbac.manage")
    if username != payload.username or not USERNAME_RE.fullmatch(username):
        raise HTTPException(400, {"code": "INVALID_USERNAME", "message": "Assignment username does not match the route"})
    try:
        pwd.getpwnam(username)
    except KeyError as error:
        raise HTTPException(404, {"code": "LOCAL_USER_NOT_FOUND", "message": "Local Linux user does not exist"}) from error
    authenticate(user.username, payload.admin_password)
    if is_linux_admin(username) and payload.role != Role.admin:
        raise HTTPException(409, {"code": "LINUX_ADMIN_COMPATIBILITY", "message": "Linux administrators always retain the administrator role"})
    assignment = RoleAssignment.model_validate(payload.model_dump(exclude={"admin_password"}))
    with _lock:
        configured = _read()
        configured[username] = assignment
        _write(configured)
    logger.info("rbac_assignment actor=%s target=%s role=%s allow=%s deny=%s", user.username, username, assignment.role.value, assignment.allow, assignment.deny)
    record_activity(
        ActivityCategory.administration,
        "rbac_assignment",
        user.username,
        target=username,
        details={"role": assignment.role.value, "allow": assignment.allow, "deny": assignment.deny},
        source="rbac",
    )
    return {**assignment.model_dump(mode="json"), **access_profile(username)}
