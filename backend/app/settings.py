from __future__ import annotations

import grp
import json
import os
import pwd
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from .activity import ActivityCategory, record_activity
from .audit import logger
from .auth import authenticate
from .config import get_config
from .host_info import collect_host_info
from .path_policy import resolve_user_path
from .proxmox_guard import (
    assert_admin_group_allowed,
    assert_admin_user_allowed,
    assert_chown_allowed,
    assert_service_allowed,
    diagnostic as proxmox_diagnostic,
)
from .resource_dashboard import collect_dashboard
from .security import SessionUser, get_session_user, require_csrf
from .rbac import access_profile, authorize

router = APIRouter()

SUPPORTED_LANGUAGES = {"pl-PL", "en-US"}
SUPPORTED_THEMES = {"light", "dark", "system"}
SUPPORTED_STARTUP_WINDOWS = {"last", "none"}
MAX_WALLPAPER_LENGTH = 2_000_000
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$")
WALLPAPER_RE = re.compile(r"^(https?://[^\s\"'<>]{1,1800}|data:image/(png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=]+)$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+(?:\.service)?$")
CRITICAL_SYSTEMD_SERVICES = {
    "pveproxy",
    "pvedaemon",
    "pve-cluster",
    "corosync",
    "networking",
    "ssh",
    "sshd",
    "systemd-logind",
    "dbus",
    "systemd-journald",
}
PROTECTED_LOCAL_USERS = {
    "root",
    "daemon",
    "bin",
    "sys",
    "sync",
    "games",
    "man",
    "lp",
    "mail",
    "news",
    "uucp",
    "proxy",
    "www-data",
    "backup",
    "list",
    "irc",
    "gnats",
    "nobody",
    "systemd-network",
    "systemd-resolve",
    "messagebus",
    "pve",
    "pvedaemon",
    "pveproxy",
}
PROTECTED_LOCAL_GROUPS = {"root", "daemon", "sudo", "wheel", "shadow", "adm", "www-data", "backup", "pve", "pveadmin", "pveproxy", "pve-cluster"}
UPDATE_SOURCE = "GitHub · chmajster/Algen-server-web-explorer-panel"
UPDATE_SOURCE_URL = "https://github.com/chmajster/Algen-server-web-explorer-panel"


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
auto_update_lock = threading.RLock()
auto_update_scheduler_started = False
user_settings_locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)


class DesktopWidget(BaseModel):
    id: Literal["cpu", "ram", "disks", "transfers", "services", "alerts"]
    visible: bool = True
    x: int = Field(default=0, ge=0, le=11)
    y: int = Field(default=0, ge=0, le=20)
    width: int = Field(default=3, ge=2, le=12)
    height: int = Field(default=2, ge=1, le=6)


DEFAULT_DESKTOP_WIDGETS = [
    DesktopWidget(id="cpu", x=0, y=0, width=3, height=2),
    DesktopWidget(id="ram", x=3, y=0, width=3, height=2),
    DesktopWidget(id="disks", x=6, y=0, width=4, height=2),
    DesktopWidget(id="transfers", x=0, y=2, width=4, height=2),
    DesktopWidget(id="services", x=4, y=2, width=3, height=2),
    DesktopWidget(id="alerts", x=7, y=2, width=3, height=2),
]

PinnedAppId = Literal[
    "files", "transfers", "activity", "identity", "users", "groups", "mounts", "samba",
    "services", "store", "logs", "settings", "monitor", "modules", "access", "containers", "ansible", "module",
]
DEFAULT_PINNED_APPS: list[PinnedAppId] = ["files", "transfers", "monitor", "settings"]


class UserSettings(BaseModel):
    language: Literal["pl-PL", "en-US"] = "pl-PL"
    theme: Literal["light", "dark", "system"] = "system"
    startup_windows: Literal["last", "none"] = "last"
    wallpaper: str = Field(default="", max_length=MAX_WALLPAPER_LENGTH)
    accent_color: Literal["blue", "teal", "green", "violet", "rose", "orange"] = "blue"
    wallpaper_fit: Literal["cover", "contain", "stretch", "center"] = "cover"
    taskbar_alignment: Literal["left", "center"] = "center"
    pinned_apps: list[PinnedAppId] = Field(default_factory=lambda: list(DEFAULT_PINNED_APPS), max_length=16)
    start_pinned_apps: list[PinnedAppId] = Field(default_factory=lambda: list(DEFAULT_PINNED_APPS), max_length=16)
    desktop_shortcut_apps: list[PinnedAppId] = Field(default_factory=lambda: list(DEFAULT_PINNED_APPS), max_length=16)
    show_desktop_shortcuts: bool = True
    desktop_shortcut_size: Literal["small", "medium", "large"] = "medium"
    show_welcome_widget: bool = True
    show_notifications: bool = True
    show_transfer_indicator: bool = True
    window_transparency: bool = True
    animations_enabled: bool = True
    clock_show_seconds: bool = False
    date_format: Literal["locale", "short", "long", "iso"] = "short"
    time_format: Literal["12", "24"] = "24"
    interface_scale: Literal[90, 100, 110, 125] = 100
    larger_text: bool = False
    high_contrast: bool = False
    reduced_motion: bool = False
    strong_active_borders: bool = False
    always_show_focus: bool = False
    file_default_view: Literal["list", "grid", "large"] = "list"
    file_compact_rows: bool = False
    file_show_hidden: bool = False
    file_confirm_delete: bool = True
    file_confirm_overwrite: bool = True
    file_page_size: Literal[25, 50, 100, 200] = 50
    file_default_sort: Literal["name", "size", "type", "modified"] = "name"
    file_sort_direction: Literal["asc", "desc"] = "asc"
    file_remember_last_path: bool = True
    transfer_success_notifications: bool = True
    transfer_error_notifications: bool = True
    transfer_open_failed_details: bool = False
    transfer_remember_filter: bool = True
    notification_transfer: bool = True
    notification_errors: bool = True
    notification_admin: bool = True
    notification_auto_hide: bool = True
    notification_limit: int = Field(default=5, ge=1, le=10)
    first_day_of_week: Literal["monday", "sunday", "locale"] = "locale"
    widgets_enabled: bool = True
    desktop_widgets: list[DesktopWidget] = Field(default_factory=lambda: [item.model_copy() for item in DEFAULT_DESKTOP_WIDGETS], max_length=6)

    @field_validator("desktop_widgets")
    @classmethod
    def unique_widgets(cls, values: list[DesktopWidget]) -> list[DesktopWidget]:
        identifiers = [item.id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("desktop widget identifiers must be unique")
        return values

    @field_validator("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps")
    @classmethod
    def unique_pinned_apps(cls, values: list[PinnedAppId]) -> list[PinnedAppId]:
        if len(values) != len(set(values)):
            raise ValueError("pinned application identifiers must be unique")
        return values

    @field_validator("wallpaper")
    @classmethod
    def validate_wallpaper(cls, value: str) -> str:
        try:
            return _validate_wallpaper(value)
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc


class MePatch(BaseModel):
    language: Literal["pl-PL", "en-US"] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    startup_windows: Literal["last", "none"] | None = None
    wallpaper: str | None = Field(default=None, max_length=MAX_WALLPAPER_LENGTH)
    accent_color: Literal["blue", "teal", "green", "violet", "rose", "orange"] | None = None
    wallpaper_fit: Literal["cover", "contain", "stretch", "center"] | None = None
    taskbar_alignment: Literal["left", "center"] | None = None
    pinned_apps: list[PinnedAppId] | None = Field(default=None, max_length=16)
    start_pinned_apps: list[PinnedAppId] | None = Field(default=None, max_length=16)
    desktop_shortcut_apps: list[PinnedAppId] | None = Field(default=None, max_length=16)
    show_desktop_shortcuts: bool | None = None
    desktop_shortcut_size: Literal["small", "medium", "large"] | None = None
    show_welcome_widget: bool | None = None
    show_notifications: bool | None = None
    show_transfer_indicator: bool | None = None
    window_transparency: bool | None = None
    animations_enabled: bool | None = None
    clock_show_seconds: bool | None = None
    date_format: Literal["locale", "short", "long", "iso"] | None = None
    time_format: Literal["12", "24"] | None = None
    interface_scale: Literal[90, 100, 110, 125] | None = None
    larger_text: bool | None = None
    high_contrast: bool | None = None
    reduced_motion: bool | None = None
    strong_active_borders: bool | None = None
    always_show_focus: bool | None = None
    file_default_view: Literal["list", "grid", "large"] | None = None
    file_compact_rows: bool | None = None
    file_show_hidden: bool | None = None
    file_confirm_delete: bool | None = None
    file_confirm_overwrite: bool | None = None
    file_page_size: Literal[25, 50, 100, 200] | None = None
    file_default_sort: Literal["name", "size", "type", "modified"] | None = None
    file_sort_direction: Literal["asc", "desc"] | None = None
    file_remember_last_path: bool | None = None
    transfer_success_notifications: bool | None = None
    transfer_error_notifications: bool | None = None
    transfer_open_failed_details: bool | None = None
    transfer_remember_filter: bool | None = None
    notification_transfer: bool | None = None
    notification_errors: bool | None = None
    notification_admin: bool | None = None
    notification_auto_hide: bool | None = None
    notification_limit: int | None = Field(default=None, ge=1, le=10)
    first_day_of_week: Literal["monday", "sunday", "locale"] | None = None
    widgets_enabled: bool | None = None
    desktop_widgets: list[DesktopWidget] | None = Field(default=None, max_length=6)

    @field_validator("desktop_widgets")
    @classmethod
    def unique_widgets(cls, values: list[DesktopWidget] | None) -> list[DesktopWidget] | None:
        if values is not None and len({item.id for item in values}) != len(values):
            raise ValueError("desktop widget identifiers must be unique")
        return values

    @field_validator("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps")
    @classmethod
    def unique_pinned_apps(cls, values: list[PinnedAppId] | None) -> list[PinnedAppId] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("pinned application identifiers must be unique")
        return values

    @field_validator("wallpaper")
    @classmethod
    def validate_wallpaper(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return _validate_wallpaper(value)
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminPassword(BaseModel):
    confirm: bool = True


class AdminSessionAction(BaseModel):
    confirm: bool = True


class ServiceAction(BaseModel):
    confirm_restart: bool = False


class UpdateAction(AdminSessionAction):
    update_config: bool = False


class AutoUpdatePatch(AdminSessionAction):
    enabled: bool
    interval_hours: int = Field(default=24, ge=1, le=168)
    update_config: bool = False


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


class UserQuota(AdminPassword):
    soft_mb: int
    hard_mb: int | None = None
    mountpoint: str | None = None


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


def _normalize_user_settings(data: dict, *, default_language: Literal["pl-PL", "en-US"] = "pl-PL") -> dict:
    """Keep valid legacy values while replacing malformed or unknown values safely."""
    defaults = UserSettings(language=default_language).model_dump()
    normalized = defaults.copy()
    for key, value in data.items():
        if key not in defaults:
            continue
        try:
            candidate = UserSettings.model_validate({**defaults, key: value})
        except ValidationError:
            continue
        normalized[key] = getattr(candidate, key)
    # Before destinations were independent, pinned_apps drove the desktop,
    # Start menu, and taskbar together. Preserve that layout for legacy files.
    if "pinned_apps" in data:
        for key in ("start_pinned_apps", "desktop_shortcut_apps"):
            if key not in data:
                normalized[key] = list(normalized["pinned_apps"])
    return normalized


def _validate_wallpaper(value: str | None) -> str:
    if not value:
        return ""
    wallpaper = value.strip()
    if len(wallpaper) > MAX_WALLPAPER_LENGTH:
        raise HTTPException(400, "Wallpaper is too large")
    if not WALLPAPER_RE.fullmatch(wallpaper):
        raise HTTPException(400, "Wallpaper must be an http(s) image URL or a supported image data URL")
    return wallpaper


def _validate_name(value: str, kind: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise HTTPException(400, f"Invalid {kind} name")
    return value


def _validate_password_text(value: str) -> str:
    if not value or any(char in value for char in "\r\n:"):
        raise HTTPException(400, "Invalid password")
    return value


def _is_manageable_uid(uid: int) -> bool:
    return uid >= get_config().security.system_uid_threshold


def _assert_manageable_user(username: str, *, action: str) -> pwd.struct_passwd | None:
    username = _validate_name(username, "user")
    if username in PROTECTED_LOCAL_USERS or username.startswith("pve"):
        raise HTTPException(403, "System account cannot be managed from WebNAS")
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        if action == "create":
            return None
        raise
    if not _is_manageable_uid(pw.pw_uid):
        raise HTTPException(403, "System account cannot be managed from WebNAS")
    assert_admin_user_allowed(username, pw.pw_uid, action)
    return pw


def _assert_manageable_group(groupname: str) -> str:
    groupname = _validate_name(groupname, "group")
    if groupname in PROTECTED_LOCAL_GROUPS or groupname.startswith("pve"):
        raise HTTPException(403, "System group cannot be managed from WebNAS")
    assert_admin_group_allowed(groupname, "manage")
    return groupname


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _revision_path() -> Path:
    return _repo_root() / ".webnas-revision"


def _auto_update_path() -> Path:
    directory = Path(get_config().paths.data_dir) / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "auto_update.json"


def _update_progress_path() -> Path:
    return _auto_update_path().parent / "update_progress.json"


def _default_auto_update_state() -> dict:
    return {
        "enabled": False,
        "interval_hours": 24,
        "update_config": False,
        "last_checked": None,
        "last_run": None,
        "last_error": "",
        "last_pid": None,
        "next_check": None,
    }


def _read_auto_update_state() -> dict:
    path = _auto_update_path()
    if not path.exists():
        return _default_auto_update_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_auto_update_state()
    return {**_default_auto_update_state(), **data}


def _write_auto_update_state(data: dict) -> dict:
    state = {**_default_auto_update_state(), **data}
    path = _auto_update_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return state


def _git_output(args: list[str], *, timeout: int = 20) -> str:
    result = subprocess.run([_tool("git"), *args], cwd=_repo_root(), capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def _remote_release_timestamp(revision: str) -> int | None:
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        return None
    result = subprocess.run(
        [
            _tool("curl"), "-fsSL", "--max-time", "10",
            "-H", "Accept: application/vnd.github+json",
            "-H", "User-Agent: WebNAS-update-checker",
            f"https://api.github.com/repos/chmajster/Algen-server-web-explorer-panel/commits/{revision}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > 2 * 1024 * 1024:
        return None
    try:
        payload = json.loads(result.stdout)
        commit = payload.get("commit") if isinstance(payload, dict) else None
        committer = commit.get("committer") if isinstance(commit, dict) else None
        value = committer.get("date") if isinstance(committer, dict) else None
        if not isinstance(value, str):
            return None
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _publication_version_from_pyproject(content: str) -> str | None:
    project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", content)
    if not project:
        return None
    version = re.search(r'^version\s*=\s*["\']([^"\']+)["\']\s*$', project.group(1), re.MULTILINE)
    return version.group(1).strip() if version else None


def _installed_publication_version() -> str | None:
    path = _repo_root() / "pyproject.toml"
    try:
        return _publication_version_from_pyproject(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def _remote_publication_version(revision: str) -> str | None:
    result = subprocess.run(
        [
            _tool("curl"), "-fsSL", "--max-time", "10",
            f"https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/{revision}/pyproject.toml",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > 128 * 1024:
        return None
    return _publication_version_from_pyproject(result.stdout)


def _update_status() -> dict:
    branch = "main"
    revision_file = _revision_path()
    if (_repo_root() / ".git").exists():
        local = _git_output(["rev-parse", "HEAD"])
        branch = _git_output(["rev-parse", "--abbrev-ref", "HEAD"]) or branch
    elif revision_file.exists():
        revision_text = revision_file.read_text(encoding="utf-8", errors="replace").strip()
        local = revision_text.splitlines()[0] if revision_text else "unknown"
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", local):
            local = "unknown"
    else:
        local = "unknown"
    installed_version = _installed_publication_version()
    try:
        remote = _git_output(["ls-remote", "https://github.com/chmajster/Algen-server-web-explorer-panel.git", f"refs/heads/{branch}"]).split()
        if not remote:
            raise HTTPException(400, f"Could not find remote branch: {branch}")
        remote_sha = remote[0]
    except (HTTPException, OSError, subprocess.SubprocessError) as error:
        message = str(error.detail) if isinstance(error, HTTPException) else str(error)
        return {"branch": branch, "local": local, "remote": "", "installed_version": installed_version, "available_version": None, "update_available": False, "available": False, "error": message, "source": UPDATE_SOURCE, "source_url": UPDATE_SOURCE_URL, "released_at": None}
    released_at = _remote_release_timestamp(remote_sha)
    available_version = _remote_publication_version(remote_sha)
    return {
        "branch": branch,
        "local": local,
        "remote": remote_sha,
        "installed_version": installed_version,
        "available_version": available_version,
        "update_available": local == "unknown" or local != remote_sha,
        "available": True,
        "error": "",
        "source": UPDATE_SOURCE,
        "source_url": UPDATE_SOURCE_URL,
        "released_at": released_at,
    }


def _start_update_process(update_config: bool, *, actor: str) -> dict:
    settings_dir = _auto_update_path().parent
    installer = settings_dir / "update-install.sh"
    download = subprocess.run(
        [_tool("curl"), "-fsSL", "https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh"],
        capture_output=True, timeout=60, check=False,
    )
    if download.returncode != 0:
        raise HTTPException(503, download.stderr.decode("utf-8", errors="replace").strip() or "Could not download the current WebNAS installer")
    if not download.stdout.startswith(b"#!/usr/bin/env bash"):
        raise HTTPException(503, "Downloaded WebNAS installer is invalid")
    with tempfile.NamedTemporaryFile(dir=settings_dir, prefix=".update-install-", suffix=".tmp", delete=False) as handle:
        handle.write(download.stdout)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o700)
        os.replace(temporary, installer)
    finally:
        if temporary.exists():
            temporary.unlink()
    command = [_tool("bash"), str(installer), "--existing-action", "update", "--yes"]
    if update_config:
        command.append("--update-config")
    progress_path = _update_progress_path()
    runner = settings_dir / "update-runner.sh"
    started_at = time.time()
    runner_content = "\n".join([
        "#!/usr/bin/env bash",
        "set +e",
        " ".join(shlex.quote(value) for value in command),
        "rc=$?",
        f"finished=$(date +%s); printf '{{\"running\":false,\"exit_code\":%s,\"started_at\":{int(started_at)},\"finished_at\":%s}}\\n' \"$rc\" \"$finished\" > {shlex.quote(str(progress_path))}.tmp",
        f"mv -f -- {shlex.quote(str(progress_path))}.tmp {shlex.quote(str(progress_path))}",
        "exit \"$rc\"",
        "",
    ])
    runner.write_text(runner_content, encoding="utf-8")
    os.chmod(runner, 0o700)
    _write_json_atomic(progress_path, {"running": True, "exit_code": None, "started_at": started_at, "finished_at": None})
    log_path = Path(get_config().paths.log_dir) / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n=== WebNAS update started ===\n")
        process = subprocess.Popen([_tool("bash"), str(runner)], cwd=_repo_root(), stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    _audit(actor, "download_update", f"pid={process.pid}")
    return {"ok": True, "pid": process.pid, "log": str(log_path)}


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _update_progress() -> dict:
    state = _read_auto_update_state()
    progress_path = _update_progress_path()
    progress: dict = {"running": False, "exit_code": None, "started_at": None, "finished_at": None}
    try:
        if progress_path.exists():
            value = json.loads(progress_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                progress.update({key: value.get(key) for key in progress})
    except (OSError, json.JSONDecodeError):
        pass
    log_path = Path(get_config().paths.log_dir) / "update.log"
    lines: list[str] = []
    try:
        if log_path.exists():
            with log_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 64 * 1024))
                lines = handle.read().decode("utf-8", errors="replace").splitlines()[-120:]
    except OSError:
        pass
    running = bool(progress.get("running"))
    exit_code = progress.get("exit_code")
    return {
        **progress,
        "running": running,
        "state": "running" if running else "completed" if exit_code == 0 else "failed" if exit_code is not None else "idle",
        "pid": state.get("last_pid"),
        "log": str(log_path),
        "lines": lines,
    }


def _run_auto_update_once(*, actor: str = "system", force: bool = False, update_config: bool | None = None) -> dict:
    with auto_update_lock:
        state = _read_auto_update_state()
        now = time.time()
        if not force:
            if not state.get("enabled"):
                return {"ok": True, "skipped": True, "reason": "disabled"}
            next_check = state.get("next_check")
            if next_check and float(next_check) > now:
                return {"ok": True, "skipped": True, "reason": "not_due", "next_check": next_check}
        state["last_checked"] = now
        try:
            status = _update_status()
            interval = max(1, int(state.get("interval_hours") or 24))
            if not status.get("available", True):
                state.update({"last_error": status.get("error") or "Update status unavailable", "next_check": now + 3600})
                _write_auto_update_state(state)
                if force:
                    raise HTTPException(503, state["last_error"])
                return {"ok": False, "updated": False, "status": status, "error": state["last_error"]}
            if not status["update_available"]:
                state.update({"last_error": "", "next_check": now + interval * 3600})
                _write_auto_update_state(state)
                return {"ok": True, "updated": False, "status": status}
            result = _start_update_process(bool(state.get("update_config") if update_config is None else update_config), actor=actor)
            state.update({
                "last_run": now,
                "last_error": "",
                "last_pid": result["pid"],
                "next_check": now + interval * 3600,
            })
            _write_auto_update_state(state)
            return {"ok": True, "updated": True, "status": status, **result}
        except HTTPException as exc:
            state.update({"last_error": str(exc.detail), "next_check": now + 3600})
            _write_auto_update_state(state)
            if force:
                raise
            return {"ok": False, "error": str(exc.detail)}
        except Exception as exc:  # noqa: BLE001
            state.update({"last_error": str(exc), "next_check": now + 3600})
            _write_auto_update_state(state)
            if force:
                raise HTTPException(500, str(exc)) from exc
            return {"ok": False, "error": str(exc)}


def start_auto_update_scheduler() -> None:
    global auto_update_scheduler_started
    if auto_update_scheduler_started:
        return
    auto_update_scheduler_started = True

    def worker() -> None:
        time.sleep(5)
        while True:
            _run_auto_update_once()
            time.sleep(60)

    threading.Thread(target=worker, daemon=True, name="webnas-auto-update").start()


def _user_info(username: str) -> dict:
    pw = pwd.getpwnam(username)
    access = access_profile(username)
    return {
        "username": pw.pw_name,
        "uid": pw.pw_uid,
        "gid": pw.pw_gid,
        "groups": _groups_for(username),
        "home": pw.pw_dir,
        "shell": pw.pw_shell,
        "gecos": pw.pw_gecos,
        "is_system": pw.pw_uid < get_config().security.system_uid_threshold,
        **access,
        "manageable": _is_manageable_uid(pw.pw_uid) and pw.pw_name not in PROTECTED_LOCAL_USERS and not pw.pw_name.startswith("pve"),
    }


def _is_admin(username: str) -> bool:
    return bool(access_profile(username)["is_admin"])


def _admin_count(excluding: str | None = None) -> int:
    return sum(1 for entry in pwd.getpwall() if entry.pw_name != excluding and _is_admin(entry.pw_name))


def _require_admin(user: SessionUser, request: Request, action: str, permission: str = "rbac.manage") -> None:
    key = f"{request.client.host if request.client else 'unknown'}:{user.username}:admin"
    admin_rate_limiter.check(key)
    authorize(user, permission)
    logger.info("admin_authorized actor=%s action=%s", user.username, action)


def _require_admin_session(user: SessionUser, request: Request, action: str, permission: str = "rbac.manage") -> None:
    key = f"{request.client.host if request.client else 'unknown'}:{user.username}:admin-session"
    admin_rate_limiter.check(key)
    authorize(user, permission)
    logger.info("admin_session_authorized actor=%s action=%s", user.username, action)


def _authorize_legacy_admin_or(user: SessionUser, permission: str) -> None:
    if _is_admin(user.username):
        return
    authorize(user, permission)


def _audit(actor: str, action: str, target: str) -> None:
    logger.info("admin_action actor=%s action=%s target=%s", actor, action, target)
    record_activity(ActivityCategory.administration, action, actor, target=target, source="administration")


def _normalize_service(service: str) -> str:
    if not SERVICE_RE.fullmatch(service):
        raise HTTPException(400, "Invalid service name")
    return service if service.endswith(".service") else f"{service}.service"


def _service_base(service: str) -> str:
    return _normalize_service(service).removesuffix(".service")


def _configured_allowed_services() -> set[str]:
    cfg = get_config()
    allowed = {_normalize_service(service) for service in cfg.systemd.allowed_services}
    allowed.update(_normalize_service(service) for service in cfg.systemd_allowed_services)
    allowed.add("webnas.service")
    return allowed


def _is_webnas_managed_service(service: str) -> bool:
    normalized = _normalize_service(service)
    return normalized == "webnas.service" or normalized.startswith("webnas-")


def _assert_systemd_service_allowed(service: str) -> str:
    normalized = _normalize_service(service)
    base = normalized.removesuffix(".service")
    if base in CRITICAL_SYSTEMD_SERVICES or base.startswith("pve"):
        raise HTTPException(403, "Critical system service is protected")
    assert_service_allowed(normalized)
    if normalized not in _configured_allowed_services() and not _is_webnas_managed_service(normalized):
        raise HTTPException(403, "Service is not in systemd_allowed_services")
    return normalized


def _systemctl(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_tool("systemctl"), *args], capture_output=True, text=True, timeout=timeout, check=False)


def _service_show(service: str) -> dict[str, str]:
    result = _systemctl(["show", service, "--property=Id,LoadState,ActiveState,SubState,UnitFileState,ActiveEnterTimestampMonotonic,NRestarts"], timeout=5)
    values: dict[str, str] = {}
    if result.returncode != 0:
        return values
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _service_uptime_seconds(values: dict[str, str]) -> int | None:
    try:
        active_since = int(values.get("ActiveEnterTimestampMonotonic") or "0")
    except ValueError:
        return None
    if active_since <= 0:
        return None
    uptime = Path("/proc/uptime")
    if not uptime.exists():
        return None
    now_us = int(float(uptime.read_text(encoding="utf-8").split()[0]) * 1_000_000)
    return max(0, (now_us - active_since) // 1_000_000)


def _service_last_error(service: str) -> str:
    if not shutil.which("journalctl"):
        return ""
    result = subprocess.run([_tool("journalctl"), "-u", service, "-p", "warning..alert", "-n", "1", "--no-pager"], capture_output=True, text=True, timeout=8, check=False)
    if result.returncode != 0:
        return ""
    return "\n".join(line for line in result.stdout.splitlines() if line.strip())[-1000:]


def _service_payload(service: str) -> dict:
    normalized = _assert_systemd_service_allowed(service)
    values = _service_show(normalized)
    return {
        "name": normalized,
        "status": values.get("ActiveState", "unknown"),
        "sub_state": values.get("SubState", ""),
        "enabled": values.get("UnitFileState", "unknown"),
        "uptime_seconds": _service_uptime_seconds(values),
        "last_error": _service_last_error(normalized),
        "managed_by_webnas": _is_webnas_managed_service(normalized),
    }


def _browser_language(header: str | None) -> Literal["pl-PL", "en-US"]:
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
    authorize(user, "settings.view_own")
    settings = _normalize_user_settings(
        _read_settings(user.username),
        default_language=_browser_language(request.headers.get("accept-language")),
    )
    return {**_user_info(user.username), **access_profile(user.username), **settings}


@router.patch("/api/settings/me")
def settings_patch(payload: MePatch, user: SessionUser = Depends(_current_user)):
    authorize(user, "settings.edit_own")
    changes = payload.model_dump(exclude_none=True)
    with user_settings_locks[user.username]:
        settings = _normalize_user_settings(_read_settings(user.username))
        settings.update(changes)
        settings = UserSettings.model_validate(settings).model_dump()
        _write_settings(user.username, settings)
    logger.info("settings_updated user=%s fields=%s", user.username, list(changes.keys()))
    record_activity(ActivityCategory.configuration, "settings_update", user.username, details={"fields": sorted(changes)}, source="settings")
    return {**_user_info(user.username), **access_profile(user.username), **settings}


@router.post("/api/settings/change-password")
def settings_change_password(payload: ChangePasswordRequest, user: SessionUser = Depends(_current_user)):
    authorize(user, "settings.change_own_password")
    assert_admin_user_allowed(user.username, pwd.getpwnam(user.username).pw_uid, "password")
    authenticate(user.username, payload.current_password)
    _run([_tool("chpasswd")], input_text=f"{user.username}:{_validate_password_text(payload.new_password)}\n")
    logger.info("password_changed user=%s target=%s", user.username, user.username)
    record_activity(ActivityCategory.configuration, "password_change", user.username, target=user.username, source="settings")
    return {"ok": True}


def admin_users(user: SessionUser = Depends(_current_user)):
    _authorize_legacy_admin_or(user, "rbac.manage")
    return [_user_info(entry.pw_name) for entry in pwd.getpwall() if _is_manageable_uid(entry.pw_uid) and entry.pw_name not in PROTECTED_LOCAL_USERS and not entry.pw_name.startswith("pve")]


def admin_user_create(payload: UserCreate, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "create_user")
    username = _validate_name(payload.username, "user")
    _assert_manageable_user(username, action="create")
    if payload.system:
        raise HTTPException(400, "Creating system users is not allowed")
    args = [_tool("useradd")]
    args.append("--user-group")
    if payload.create_home:
        args.append("--create-home")
    if payload.shell:
        args.extend(["--shell", payload.shell])
    if payload.gecos:
        args.extend(["--comment", payload.gecos])
    if payload.groups:
        args.extend(["--groups", ",".join(_assert_manageable_group(group) for group in payload.groups)])
    args.append(username)
    _run(args)
    _run([_tool("chpasswd")], input_text=f"{username}:{_validate_password_text(payload.password)}\n")
    if payload.force_password_change:
        _run([_tool("chage"), "-d", "0", username])
    _audit(user.username, "create_user", username)
    return _user_info(username)


def admin_user_get(username: str, user: SessionUser = Depends(_current_user)):
    authorize(user, "rbac.manage")
    _assert_manageable_user(username, action="read")
    return _user_info(_validate_name(username, "user"))


def admin_user_patch(username: str, payload: UserPatch, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "update_user")
    username = _validate_name(username, "user")
    _assert_manageable_user(username, action="update")
    args = [_tool("usermod")]
    if payload.shell:
        args.extend(["--shell", payload.shell])
    if payload.gecos is not None:
        args.extend(["--comment", payload.gecos])
    if payload.groups_add:
        args.extend(["--append", "--groups", ",".join(_assert_manageable_group(group) for group in payload.groups_add)])
    if len(args) > 1:
        _run([*args, username])
    for group in payload.groups_remove:
        _run([_tool("gpasswd"), "--delete", username, _assert_manageable_group(group)])
    if payload.create_home:
        Path(pwd.getpwnam(username).pw_dir).mkdir(parents=True, exist_ok=True)
    if payload.force_password_change is True:
        _run([_tool("chage"), "-d", "0", username])
    elif payload.force_password_change is False:
        _run([_tool("chage"), "-d", "-1", username])
    _audit(user.username, "update_user", username)
    return _user_info(username)


def admin_user_delete(username: str, payload: AdminPassword, request: Request, advanced: bool = False, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "delete_user")
    username = _validate_name(username, "user")
    _assert_manageable_user(username, action="delete")
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


def admin_user_lock(username: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "lock_user")
    username = _validate_name(username, "user")
    _assert_manageable_user(username, action="lock")
    _run([_tool("usermod"), "--lock", username])
    _audit(user.username, "lock_user", username)
    return {"ok": True}


def admin_user_unlock(username: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "unlock_user")
    username = _validate_name(username, "user")
    _assert_manageable_user(username, action="unlock")
    _run([_tool("usermod"), "--unlock", username])
    _audit(user.username, "unlock_user", username)
    return {"ok": True}


def admin_user_password(username: str, payload: AdminChangePassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "change_user_password")
    username = _validate_name(username, "user")
    _assert_manageable_user(username, action="password")
    _run([_tool("chpasswd")], input_text=f"{username}:{_validate_password_text(payload.new_password)}\n")
    if payload.force_change:
        _run([_tool("chage"), "-d", "0", username])
    _audit(user.username, "change_user_password", username)
    return {"ok": True}


def admin_user_quota(username: str, payload: UserQuota, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "set_user_quota")
    pw = _assert_manageable_user(username, action="quota")
    if pw is None:
        raise HTTPException(404, "User not found")
    if payload.soft_mb < 0 or (payload.hard_mb is not None and payload.hard_mb < payload.soft_mb):
        raise HTTPException(400, "Invalid quota")
    setquota = shutil.which("setquota")
    if not setquota:
        raise HTTPException(503, "Quota tools are not installed on this system")
    mountpoint = payload.mountpoint or str(Path(pw.pw_dir).anchor or "/")
    soft_blocks = payload.soft_mb * 1024
    hard_blocks = (payload.hard_mb if payload.hard_mb is not None else payload.soft_mb) * 1024
    _run([setquota, "-u", username, str(soft_blocks), str(hard_blocks), "0", "0", mountpoint])
    _audit(user.username, "set_user_quota", f"{username}:{payload.soft_mb}:{hard_blocks // 1024}:{mountpoint}")
    return {"ok": True, "quota_supported": True}


def admin_groups(user: SessionUser = Depends(_current_user)):
    authorize(user, "rbac.manage")
    return [{"name": group.gr_name, "gid": group.gr_gid, "members": sorted(group.gr_mem)} for group in grp.getgrall()]


def admin_group_create(payload: GroupCreate, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "create_group")
    groupname = _assert_manageable_group(payload.groupname)
    args = [_tool("groupadd")]
    if payload.system:
        args.append("--system")
    _run([*args, groupname])
    _audit(user.username, "create_group", groupname)
    return {"ok": True, "name": groupname}


def admin_group_patch(groupname: str, payload: GroupPatch, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "update_group")
    groupname = _assert_manageable_group(groupname)
    if payload.new_name:
        _run([_tool("groupmod"), "--new-name", _assert_manageable_group(payload.new_name), groupname])
    _audit(user.username, "update_group", groupname)
    return {"ok": True}


def admin_group_delete(groupname: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "delete_group")
    groupname = _assert_manageable_group(groupname)
    if not payload.confirm:
        raise HTTPException(400, "Confirmation required")
    _run([_tool("groupdel"), groupname])
    _audit(user.username, "delete_group", groupname)
    return {"ok": True}


def admin_group_add_member(groupname: str, payload: GroupMember, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "add_group_member")
    groupname = _assert_manageable_group(groupname)
    username = _validate_name(payload.username, "user")
    _assert_manageable_user(username, action="update")
    _run([_tool("usermod"), "--append", "--groups", groupname, username])
    _audit(user.username, "add_group_member", f"{groupname}:{username}")
    return {"ok": True}


def admin_group_remove_member(groupname: str, username: str, payload: AdminPassword, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin(user, request, "remove_group_member")
    groupname = _assert_manageable_group(groupname)
    username = _validate_name(username, "user")
    _assert_manageable_user(username, action="update")
    _run([_tool("gpasswd"), "--delete", username, groupname])
    _audit(user.username, "remove_group_member", f"{groupname}:{username}")
    return {"ok": True}


@router.post("/api/admin/files/ownership")
def admin_file_ownership(payload: ChownRequest, request: Request, user: SessionUser = Depends(_current_user)):
    authorize(user, "files.chown")
    target = resolve_user_path(user.username, payload.path)
    assert_chown_allowed(target)
    if payload.owner:
        _require_admin(user, request, "change_owner")
    elif payload.group and not _is_admin(user.username):
        user_groups = _groups_for(user.username)
        if payload.group not in user_groups:
            raise HTTPException(403, "Group change is not allowed")
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
    authorize(user, "system.status")
    cfg = get_config()
    return {
        "service": "webnas",
        "version": "0.1.0",
        "port": cfg.server.port,
        "data_dir": cfg.paths.data_dir,
        "log_dir": cfg.paths.log_dir,
        "temp_dir": cfg.paths.temp_dir,
    }


@router.get("/api/system/resources")
def system_resources(user: SessionUser = Depends(_current_user)):
    authorize(user, "system.status")
    return collect_dashboard(user.username, is_admin=_is_admin(user.username))


@router.get("/api/system/host-info")
def system_host_info(user: SessionUser = Depends(_current_user)):
    authorize(user, "system.status")
    return collect_host_info()


@router.post("/api/admin/system/restart")
def admin_system_restart(payload: AdminSessionAction, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin_session(user, request, "restart_system", "system.restart")
    assert_service_allowed("webnas.service")
    _run([_tool("systemctl"), "restart", "webnas.service"])
    _audit(user.username, "restart_system", "webnas.service")
    return {"ok": True}


@router.get("/api/admin/system/updates/check")
def admin_updates_check(user: SessionUser = Depends(_current_user)):
    authorize(user, "updates.view")
    return _update_status()


@router.post("/api/admin/system/updates/download")
def admin_updates_download(payload: UpdateAction, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin_session(user, request, "download_update", "updates.apply")
    return _start_update_process(payload.update_config, actor=user.username)


@router.get("/api/admin/system/updates/progress")
def admin_updates_progress(user: SessionUser = Depends(_current_user)):
    authorize(user, "updates.view")
    return _update_progress()


@router.get("/api/admin/system/updates/auto")
def admin_auto_update_get(user: SessionUser = Depends(_current_user)):
    authorize(user, "updates.configure_auto_update")
    return _read_auto_update_state()


@router.patch("/api/admin/system/updates/auto")
def admin_auto_update_patch(payload: AutoUpdatePatch, request: Request, user: SessionUser = Depends(_current_user)):
    authorize(user, "settings.edit_system")
    _require_admin_session(user, request, "configure_auto_update", "updates.configure_auto_update")
    now = time.time()
    state = _read_auto_update_state()
    state.update({
        "enabled": payload.enabled,
        "interval_hours": payload.interval_hours,
        "update_config": payload.update_config,
        "next_check": now + payload.interval_hours * 3600 if payload.enabled else None,
        "last_error": "",
    })
    _audit(user.username, "configure_auto_update", f"enabled={payload.enabled}")
    return _write_auto_update_state(state)


@router.post("/api/admin/system/updates/auto/run")
def admin_auto_update_run(payload: UpdateAction, request: Request, user: SessionUser = Depends(_current_user)):
    _require_admin_session(user, request, "run_auto_update", "updates.apply")
    result = _run_auto_update_once(actor=user.username, force=True, update_config=payload.update_config)
    return result


@router.get("/api/admin/system/logs")
def admin_system_logs(lines: int = 120, user: SessionUser = Depends(_current_user)):
    authorize(user, "system.logs")
    limit = max(20, min(lines, 500))
    if shutil.which("journalctl"):
        result = subprocess.run(
            [_tool("journalctl"), "-u", "webnas", "-n", str(limit), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return {"source": "journalctl", "lines": result.stdout.splitlines()[-limit:]}
    log_dir = Path(get_config().paths.log_dir)
    candidates = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True) if log_dir.exists() else []
    if not candidates:
        return {"source": "none", "lines": []}
    return {"source": str(candidates[0]), "lines": candidates[0].read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]}


@router.get("/api/admin/system/services")
def admin_systemd_services(user: SessionUser = Depends(_current_user)):
    authorize(user, "services.view")
    services = sorted(_configured_allowed_services())
    return [_service_payload(service) for service in services]


@router.get("/api/admin/system/services/{service}")
def admin_systemd_service(service: str, user: SessionUser = Depends(_current_user)):
    authorize(user, "services.view")
    return _service_payload(service)


@router.post("/api/admin/system/services/{service}/{action}")
def admin_systemd_service_action(service: str, action: str, payload: ServiceAction, request: Request, user: SessionUser = Depends(_current_user)):
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise HTTPException(404, "Unsupported service action")
    normalized = _assert_systemd_service_allowed(service)
    if action == "restart" and not payload.confirm_restart:
        raise HTTPException(400, "Restart requires explicit confirmation")
    _require_admin_session(user, request, f"systemd_{action}", f"services.{action}")
    _run([_tool("systemctl"), action, normalized])
    _audit(user.username, f"systemd_{action}", normalized)
    return _service_payload(normalized)


@router.get("/api/admin/system/services/{service}/logs")
def admin_systemd_service_logs(service: str, lines: int = 160, user: SessionUser = Depends(_current_user)):
    authorize(user, "services.logs")
    normalized = _assert_systemd_service_allowed(service)
    limit = max(20, min(lines, 500))
    if not shutil.which("journalctl"):
        return {"source": "none", "lines": []}
    result = subprocess.run([_tool("journalctl"), "-u", normalized, "-n", str(limit), "--no-pager"], capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        return {"source": "journalctl", "lines": [result.stderr.strip() or "Could not read service logs"]}
    return {"source": "journalctl", "lines": result.stdout.splitlines()[-limit:]}


@router.get("/api/admin/system/proxmox-safety")
def admin_proxmox_safety(user: SessionUser = Depends(_current_user)):
    authorize(user, "settings.view_system")
    return proxmox_diagnostic(user.username)
