from __future__ import annotations

import grp
import json
import os
import pwd
import re
import shutil
import subprocess
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .audit import logger
from .auth import authenticate
from .config import get_config
from .path_policy import resolve_user_path
from .security import SessionUser, get_session_user, require_csrf

router = APIRouter()

SUPPORTED_LANGUAGES = {"pl-PL", "en-US"}
SUPPORTED_THEMES = {"light", "dark", "system"}
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$")


class AdminRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        cfg = get_config()
        now = time.time()
        window = self._attempts[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= cfg.security.rate_limit_admin_per_minute:
            raise HTTPException(429, "Too many administrative operations")
        window.append(now)


admin_rate_limiter = AdminRateLimiter()


class MePatch(BaseModel):
    language: Literal["pl-PL", "en-US"] | None = None
    theme: Literal["light", "dark", "system"] | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminPassword(BaseModel):
    admin_password: str
    confirm: bool = True


class UserCreate(AdminPassword):
    username: str
    password: str
    groups: list[str] = Field(default_factory=list)
    shell: str | None = None
    gecos: str | None = None
    create_home: bool = True
    force_password_change: bool = False
    system: bool = False


class UserPatch(AdminPassword):
    groups_add: list[str] = Field(default_factory=list)
    groups_remove: list[str] = Field(default_factory=list)
    shell: str | None = None
    gecos: str | None = None
    create_home: bool = False
    force_password_change: bool | None = None


class AdminChangePassword(AdminPassword):
    new_password: str
    force_change: bool = False


class GroupCreate(AdminPassword):
    groupname: str
    system: bool = False


class GroupPatch(AdminPassword):
    new_name: str | None = None


class GroupMember(AdminPassword):
    username: str


class ChownRequest(AdminPassword):
    path: str
    owner: str | None = None
    group: str | None = None


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _settings_path(username: str) -> Path:
    safe = username.replace("/", "_")
    directory = Path(get_config().paths.data_dir) / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe}.json"


def _read_settings(username: str) -> dict:
    path = _settings_path(username)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_settings(username: str, data: dict) -> None:
    path = _settings_path(username)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _validate_name(value: str, kind: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise HTTPException(400, f"Invalid {kind} name")
    return value


def _validate_password_text(value: str) -> str:
    if not value or any(char in value for char in "\r\n:"):
        raise HTTPException(400, "Invalid password")
    return value


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=60, check=False)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip() or "System command failed")
    return result


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise HTTPException(503, f"Required system tool is missing: {name}")
    return found


def _groups_for(username: str) -> list[str]:
    return sorted(group.gr_name for group in grp.getgrall() if username in group.gr_mem or group.gr_gid == pwd.getpwnam(username).pw_gid)


def _user_info(username: str) -> dict:
    pw = pwd.getpwnam(username)
    return {
        "username": pw.pw_name,
        "uid": pw.pw_uid,
        "gid": pw.pw_gid,
        "groups": _groups_for(username),
        "home": pw.pw_dir,
        "shell": pw.pw_shell,
        "gecos": pw.pw_gecos,
        "is_system": pw.pw_uid < get_config().security.system_uid_threshold,
        "is_admin": _is_admin(username),
    }


def _is_admin(username: str) -> bool:
    try:
        groups = _groups_for(username)
    except KeyError:
        return False
    return "sudo" in groups or "wheel" in groups


def _admin_count(excluding: str | None = None) -> int:
    return sum(1 for entry in pwd.getpwall() if entry.pw_name != excluding and _is_admin(entry.pw_name))


def _require_admin(user: SessionUser, password: str, request: Request, action: str) -> None:
    key = f"{request.client.host if request.client else 'unknown'}:{user.username}:admin"
    admin_rate_limiter.check(key)
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    authenticate(user.username, password)
    logger.info("admin_authorized actor=%s action=%s", user.username, action)


def _audit(actor: str, action: str, target: str) -> None:
    logger.info("admin_action actor=%s action=%s target=%s", actor, action, target)


def _browser_language(header: str | None) -> str:
    if not header:
        return "pl-PL"
    lower = header.lower()
    if "pl" in lower:
        return "pl-PL"
    if "en" in lower:
        return "en-US"
    return "pl-PL"


@router.get("/api/settings/me")
def settings_me(request: Request, user: SessionUser = Depends(_current_user)):
    settings = _read_settings(user.username)
    language = settings.get("language") if settings.get("language") in SUPPORTED_LANGUAGES else _browser_language(request.headers.get("accept-language"))
    theme = settings.get("theme") if settings.get("theme") in SUPPORTED_THEMES else "system"
    return {**_user_info(user.username), "language": language, "theme": theme}


@router.patch("/api/settings/me")
def settings_patch(payload: MePatch, user: SessionUser = Depends(_current_user)):
    settings = _read_settings(user.username)
    if payload.language:
        settings["language"] = payload.language
    if payload.theme:
        settings["theme"] = payload.theme
    _write_settings(user.username, settings)
    logger.info("settings_updated user=%s fields=%s", user.username, list(payload.model_dump(exclude_none=True).keys()))
    return {"ok": True, **settings}


@router.post("/api/settings/change-password")
def settings_change_password(payload: ChangePasswordRequest, user: SessionUser = Depends(_current_user)):
    authenticate(user.username, payload.current_password)
    _run([_tool("chpasswd")], input_text=f"{user.username}:{_validate_password_text(payload.new_password)}\n")
    logger.info("password_changed user=%s target=%s", user.username, user.username)
    return {"ok": True}


@router.get("/api/admin/users")
def admin_users(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return [_user_info(entry.pw_name) for entry in pwd.getpwall()]


@router.post("/api/admin/users")
def admin_user_create(payload: UserCreate, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "create_user")
    username = _validate_name(payload.username, "user")
    args = [_tool("useradd")]
    args.append("--system" if payload.system else "--user-group")
    if payload.create_home:
        args.append("--create-home")
    if payload.shell:
        args.extend(["--shell", payload.shell])
    if payload.gecos:
        args.extend(["--comment", payload.gecos])
    if payload.groups:
        args.extend(["--groups", ",".join(_validate_name(group, "group") for group in payload.groups)])
    args.append(username)
    _run(args)
    _run([_tool("chpasswd")], input_text=f"{username}:{_validate_password_text(payload.password)}\n")
    if payload.force_password_change:
        _run([_tool("chage"), "-d", "0", username])
    _audit(user.username, "create_user", username)
    return _user_info(username)


@router.get("/api/admin/users/{username}")
def admin_user_get(username: str, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return _user_info(_validate_name(username, "user"))


@router.patch("/api/admin/users/{username}")
def admin_user_patch(username: str, payload: UserPatch, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "update_user")
    username = _validate_name(username, "user")
    args = [_tool("usermod")]
    if payload.shell:
        args.extend(["--shell", payload.shell])
    if payload.gecos is not None:
        args.extend(["--comment", payload.gecos])
    if payload.groups_add:
        args.extend(["--append", "--groups", ",".join(_validate_name(group, "group") for group in payload.groups_add)])
    if len(args) > 1:
        _run([*args, username])
    for group in payload.groups_remove:
        _run([_tool("gpasswd"), "--delete", username, _validate_name(group, "group")])
    if payload.create_home:
        Path(pwd.getpwnam(username).pw_dir).mkdir(parents=True, exist_ok=True)
    if payload.force_password_change is True:
        _run([_tool("chage"), "-d", "0", username])
    elif payload.force_password_change is False:
        _run([_tool("chage"), "-d", "-1", username])
    _audit(user.username, "update_user", username)
    return _user_info(username)


@router.delete("/api/admin/users/{username}")
def admin_user_delete(username: str, payload: AdminPassword, request: Request, advanced: bool = False, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "delete_user")
    username = _validate_name(username, "user")
    if not payload.confirm:
        raise HTTPException(400, "Confirmation required")
    if username == user.username:
        raise HTTPException(400, "Cannot delete currently logged-in user")
    info = _user_info(username)
    if info["is_admin"] and _admin_count(excluding=username) < 1:
        raise HTTPException(400, "Cannot delete the last administrator")
    if info["is_system"] and not advanced:
        raise HTTPException(400, "Refusing to delete a system user without advanced mode")
    _run([_tool("userdel"), "--remove", username])
    _audit(user.username, "delete_user", username)
    return {"ok": True}


@router.post("/api/admin/users/{username}/lock")
def admin_user_lock(username: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "lock_user")
    username = _validate_name(username, "user")
    _run([_tool("usermod"), "--lock", username])
    _audit(user.username, "lock_user", username)
    return {"ok": True}


@router.post("/api/admin/users/{username}/unlock")
def admin_user_unlock(username: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "unlock_user")
    username = _validate_name(username, "user")
    _run([_tool("usermod"), "--unlock", username])
    _audit(user.username, "unlock_user", username)
    return {"ok": True}


@router.post("/api/admin/users/{username}/change-password")
def admin_user_password(username: str, payload: AdminChangePassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "change_user_password")
    username = _validate_name(username, "user")
    _run([_tool("chpasswd")], input_text=f"{username}:{_validate_password_text(payload.new_password)}\n")
    if payload.force_change:
        _run([_tool("chage"), "-d", "0", username])
    _audit(user.username, "change_user_password", username)
    return {"ok": True}


@router.get("/api/admin/groups")
def admin_groups(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return [{"name": group.gr_name, "gid": group.gr_gid, "members": sorted(group.gr_mem)} for group in grp.getgrall()]


@router.post("/api/admin/groups")
def admin_group_create(payload: GroupCreate, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "create_group")
    groupname = _validate_name(payload.groupname, "group")
    args = [_tool("groupadd")]
    if payload.system:
        args.append("--system")
    _run([*args, groupname])
    _audit(user.username, "create_group", groupname)
    return {"ok": True, "name": groupname}


@router.patch("/api/admin/groups/{groupname}")
def admin_group_patch(groupname: str, payload: GroupPatch, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "update_group")
    groupname = _validate_name(groupname, "group")
    if payload.new_name:
        _run([_tool("groupmod"), "--new-name", _validate_name(payload.new_name, "group"), groupname])
    _audit(user.username, "update_group", groupname)
    return {"ok": True}


@router.delete("/api/admin/groups/{groupname}")
def admin_group_delete(groupname: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "delete_group")
    groupname = _validate_name(groupname, "group")
    if not payload.confirm:
        raise HTTPException(400, "Confirmation required")
    _run([_tool("groupdel"), groupname])
    _audit(user.username, "delete_group", groupname)
    return {"ok": True}


@router.post("/api/admin/groups/{groupname}/members")
def admin_group_add_member(groupname: str, payload: GroupMember, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "add_group_member")
    groupname = _validate_name(groupname, "group")
    username = _validate_name(payload.username, "user")
    _run([_tool("usermod"), "--append", "--groups", groupname, username])
    _audit(user.username, "add_group_member", f"{groupname}:{username}")
    return {"ok": True}


@router.delete("/api/admin/groups/{groupname}/members/{username}")
def admin_group_remove_member(groupname: str, username: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "remove_group_member")
    groupname = _validate_name(groupname, "group")
    username = _validate_name(username, "user")
    _run([_tool("gpasswd"), "--delete", username, groupname])
    _audit(user.username, "remove_group_member", f"{groupname}:{username}")
    return {"ok": True}


@router.post("/api/admin/files/ownership")
def admin_file_ownership(payload: ChownRequest, request: Request, user: SessionUser = Depends(_current_user)):
    target = resolve_user_path(user.username, payload.path)
    if payload.owner:
        _require_admin(user, payload.admin_password, request, "change_owner")
    elif payload.group and not _is_admin(user.username):
        user_groups = _groups_for(user.username)
        if payload.group not in user_groups:
            raise HTTPException(403, "Group change is not allowed")
        authenticate(user.username, payload.admin_password)
    owner_group = ""
    if payload.owner:
        owner_group += _validate_name(payload.owner, "user")
    if payload.group:
        owner_group += f":{_validate_name(payload.group, 'group')}"
    _run([_tool("chown"), owner_group, str(target)])
    _audit(user.username, "change_ownership", str(target))
    return {"ok": True}


@router.get("/api/admin/system/status")
def admin_system_status(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    cfg = get_config()
    return {
        "service": "webnas",
        "version": "0.1.0",
        "port": cfg.server.port,
        "data_dir": cfg.paths.data_dir,
        "log_dir": cfg.paths.log_dir,
        "temp_dir": cfg.paths.temp_dir,
    }


@router.post("/api/admin/system/restart")
def admin_system_restart(payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password, request, "restart_system")
    _run([_tool("systemctl"), "restart", "webnas.service"])
    _audit(user.username, "restart_system", "webnas.service")
    return {"ok": True}
