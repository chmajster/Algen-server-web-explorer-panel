from __future__ import annotations

import grp
import json
import os
import pwd
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .activity import ActivityCategory, record_activity
from .audit import logger
from .auth import authenticate
from .config import get_config
from .proxmox_guard import safe_mode_active
from .security import SessionUser, get_session_user, require_csrf
from .settings import _is_admin

router = APIRouter(prefix="/api/mounts")

MOUNT_BASE_DIR = Path("/mnt/webnas/mnt")
MOUNT_TYPES = {"smb", "nfs", "sshfs", "webdav"}
SMB_VERSIONS = {"auto", "2.1", "3.0", "3.1.1"}
NFS_VERSIONS = {"auto", "3", "4", "4.1", "4.2"}
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}$")
SHARE_RE = re.compile(r"^[A-Za-z0-9_$][A-Za-z0-9_. $-]{0,127}$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.@-]{0,63}\$?$")
MODE_RE = re.compile(r"^0?[0-7]{3,4}$")
SAFE_OPTION_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:=[A-Za-z0-9_.:/@+-]+)?$")
ALLOWED_OPTION_KEYS = {
    "ac", "actimeo", "async", "atime", "cache", "dirsync", "hard", "intr", "iocharset",
    "lookupcache", "noac", "noatime", "nodiratime", "noserverino", "retrans", "rsize",
    "serverino", "soft", "sync", "timeo", "wsize",
}
BLOCKED_OPTION_KEYS = {
    "allow_other", "allow_root", "credentials", "dev", "exec", "group", "owner", "pass",
    "passwd", "password", "suid", "user", "username", "users",
}
BASE_OPTIONS = ["nosuid", "nodev", "_netdev", "nofail"]
TRANSIENT_STATUSES = {"mounting", "unmounting", "remounting", "testing", "migrating"}
_locks_guard = threading.Lock()
_mount_locks: dict[str, threading.Lock] = {}


def state_dir() -> Path:
    path = Path(get_config().paths.data_dir) / "mounts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return state_dir() / "network_mounts.sqlite3"


def log_dir() -> Path:
    path = Path("/var/log/webnas/mounts")
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except PermissionError:
        fallback = state_dir() / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def credentials_dir() -> Path:
    path = Path("/etc/webnas/mounts/credentials")
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        return path
    except PermissionError:
        fallback = state_dir() / "credentials"
        fallback.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(fallback, 0o700)
        return fallback


def systemd_dir() -> Path:
    path = Path("/etc/systemd/system")
    fallback = state_dir() / "systemd"
    return path if os.access(path, os.W_OK) else fallback


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mounts (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, host TEXT NOT NULL,
            remote TEXT NOT NULL, mount_point TEXT NOT NULL, owner TEXT NOT NULL,
            read_only INTEGER NOT NULL DEFAULT 0, persistent INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unmounted', config_json TEXT NOT NULL,
            allowed_users_json TEXT NOT NULL, allowed_groups_json TEXT NOT NULL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    additions = {
        "normalized_name": "TEXT NOT NULL DEFAULT ''",
        "last_operation": "TEXT NOT NULL DEFAULT ''",
        "last_operation_at": "REAL",
        "missing_packages_json": "TEXT NOT NULL DEFAULT '[]'",
        "migration_status": "TEXT NOT NULL DEFAULT 'ready'",
        "manual_intervention": "INTEGER NOT NULL DEFAULT 0",
    }
    existing = _columns(conn, "mounts")
    for name, definition in additions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE mounts ADD COLUMN {name} {definition}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mount_jobs (
            id TEXT PRIMARY KEY, mount_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
            exit_code INTEGER, error TEXT NOT NULL DEFAULT '', log_tail_json TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL, finished_at REAL
        )
        """
    )
    rows = conn.execute("SELECT id, name, mount_point, normalized_name FROM mounts").fetchall()
    for row in rows:
        normalized = normalize_mount_name(str(row["name"]), validate=False)
        migration = "ready" if is_managed_mount_point(row["mount_point"], str(row["name"]), resolve=False) else "required"
        conn.execute(
            "UPDATE mounts SET normalized_name=?, migration_status=CASE WHEN migration_status='ready' THEN ? ELSE migration_status END WHERE id=?",
            (normalized, migration, row["id"]),
        )
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS mounts_normalized_name_uq ON mounts(normalized_name)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS mounts_mount_point_uq ON mounts(mount_point)")
    except sqlite3.IntegrityError:
        logger.warning("network_mount_migration_conflict reason=duplicate_name_or_path")
    conn.commit()
    return conn


class AdminMountAction(BaseModel):
    admin_password: str
    dry_run: bool = False
    force_empty_mountpoint: bool = False
    confirm_destructive: bool = False


class MountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_password: str
    name: str
    type: str
    host: str
    share: str | None = None
    export_path: str | None = None
    remote_path: str | None = None
    username: str | None = None
    password: str | None = None
    domain: str | None = None
    smb_version: str = "auto"
    nfs_version: str = "auto"
    ssh_port: int = 22
    ssh_auth: str = "key"
    read_only: bool = False
    persistent: bool = False
    automount: bool = False
    uid: str | None = None
    gid: str | None = None
    file_mode: str = "0644"
    dir_mode: str = "0755"
    noexec: bool = True
    advanced_options: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)
    allowed_groups: list[str] = Field(default_factory=list)
    force_empty_mountpoint: bool = False
    remove_secret: bool = False


def current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def require_admin_session(user: SessionUser, action: str) -> None:
    if not _is_admin(user.username):
        logger.info("network_mount_denied actor=%s action=%s reason=not_admin", user.username, action)
        raise HTTPException(403, "Administrator privileges required")


def require_admin(user: SessionUser, password: str, action: str) -> None:
    require_admin_session(user, action)
    authenticate(user.username, password)


def audit(actor: str, action: str, target: str) -> None:
    logger.info("network_mount_action actor=%s action=%s target=%s", actor, action, target)
    record_activity(ActivityCategory.administration, action, actor, target=target, source="network-mounts")


def normalize_mount_name(name: str, *, validate: bool = True) -> str:
    value = unicodedata.normalize("NFKC", name)
    if validate:
        if value != name or not value or value != value.strip() or value.endswith((".", " ")):
            raise HTTPException(422, {"code": "invalid_name", "field": "name", "message": "Invalid resource name"})
        if len(value) > 63 or value in {".", ".."} or ".." in value:
            raise HTTPException(422, {"code": "invalid_name", "field": "name", "message": "Invalid resource name"})
        if any(ch in "/\\\x00" or unicodedata.category(ch) == "Cc" for ch in value):
            raise HTTPException(422, {"code": "invalid_name", "field": "name", "message": "Resource name must be one directory component"})
        if not value[0].isalnum() or any(not (ch.isalnum() or ch in "_.-") for ch in value):
            raise HTTPException(422, {"code": "invalid_name", "field": "name", "message": "Use letters, numbers, dots, dashes or underscores"})
    return value.casefold()


def validate_mount_name(name: str) -> str:
    normalize_mount_name(name)
    return name


def default_mount_point(name_or_owner: str, name: str | None = None) -> Path:
    # The optional second argument keeps compatibility with older internal callers;
    # the owner is deliberately ignored.
    resource_name = name if name is not None else name_or_owner
    validate_mount_name(resource_name)
    mount_point = MOUNT_BASE_DIR / resource_name
    if mount_point.parent != MOUNT_BASE_DIR:
        raise HTTPException(422, {"code": "invalid_mount_point", "field": "name", "message": "Invalid mount point"})
    return mount_point


def is_managed_mount_point(path: str | Path, name: str | None = None, *, resolve: bool = True) -> bool:
    candidate = Path(path)
    expected = default_mount_point(name) if name else candidate
    if candidate != expected or candidate.parent != MOUNT_BASE_DIR:
        return False
    try:
        managed_components = (Path("/mnt"), Path("/mnt/webnas"), MOUNT_BASE_DIR, candidate)
        if any(component.exists() and component.is_symlink() for component in managed_components):
            return False
        if resolve:
            base_real = MOUNT_BASE_DIR.resolve(strict=False)
            candidate_real = candidate.resolve(strict=False)
            return base_real == MOUNT_BASE_DIR and candidate_real.parent == base_real
    except OSError:
        return False
    return True


def _proxmox_storage_conflicts(path: Path) -> bool:
    if not safe_mode_active():
        return False
    storage_config = Path("/etc/pve/storage.cfg")
    try:
        content = storage_config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    text_path = str(path)
    return any(text_path == token or text_path.startswith(f"{token}/") or token.startswith(f"{text_path}/") for token in re.findall(r"(?:path|mountpoint)\s+([^\s]+)", content))


def validate_mount_point(path: str | Path, *, allow_existing_data: bool = False, name: str | None = None) -> Path:
    candidate = Path(path)
    resource_name = name or candidate.name
    if not is_managed_mount_point(candidate, resource_name):
        raise HTTPException(403, {"code": "unsafe_mount_point", "message": "Mount point must be a direct child of /mnt/webnas/mnt"})
    if _proxmox_storage_conflicts(candidate):
        raise HTTPException(403, {"code": "proxmox_conflict", "message": "Mount point conflicts with Proxmox storage"})
    if candidate.exists() and not candidate.is_dir():
        raise HTTPException(409, {"code": "mount_point_conflict", "message": "Mount point is not a directory"})
    if candidate.exists() and any(candidate.iterdir()) and not allow_existing_data:
        raise HTTPException(409, {"code": "mount_point_not_empty", "message": "Mount point is not empty; confirm explicitly to continue"})
    return candidate


def validate_host(host: str) -> None:
    if not HOST_RE.fullmatch(host):
        raise HTTPException(422, {"code": "invalid_host", "field": "host", "message": "Invalid host"})


def validate_options(options: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in options:
        option = raw.strip()
        if not option:
            continue
        key = option.split("=", 1)[0].lower()
        if key in BLOCKED_OPTION_KEYS or key not in ALLOWED_OPTION_KEYS or not SAFE_OPTION_RE.fullmatch(option):
            raise HTTPException(422, {"code": "blocked_option", "field": "advanced_options", "message": f"Blocked mount option: {key}"})
        cleaned.append(option)
    return list(dict.fromkeys(cleaned))


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, {"code": "invalid_url", "field": "remote_path", "message": "Invalid WebDAV URL"})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def remote_for(payload: MountPayload) -> str:
    if payload.type == "smb":
        if not payload.share or not SHARE_RE.fullmatch(payload.share):
            raise HTTPException(422, {"code": "invalid_share", "field": "share", "message": "Invalid SMB share"})
        return f"//{payload.host}/{payload.share}"
    if payload.type == "nfs":
        if not payload.export_path or not payload.export_path.startswith("/") or any(ch in payload.export_path for ch in "\r\n\x00"):
            raise HTTPException(422, {"code": "invalid_export", "field": "export_path", "message": "Invalid NFS export path"})
        return f"{payload.host}:{payload.export_path}"
    if payload.type == "sshfs":
        if payload.ssh_auth != "key":
            raise HTTPException(422, {"code": "unsafe_auth", "field": "ssh_auth", "message": "SSHFS password authentication is disabled; use key authentication"})
        if not payload.username or not USER_RE.fullmatch(payload.username):
            raise HTTPException(422, {"code": "invalid_username", "field": "username", "message": "Invalid SSH username"})
        if not payload.remote_path or not payload.remote_path.startswith("/") or any(ch in payload.remote_path for ch in "\r\n\x00"):
            raise HTTPException(422, {"code": "invalid_remote_path", "field": "remote_path", "message": "Invalid SSHFS path"})
        if not 1 <= payload.ssh_port <= 65535:
            raise HTTPException(422, {"code": "invalid_port", "field": "ssh_port", "message": "Invalid SSH port"})
        return f"{payload.username}@{payload.host}:{payload.remote_path}"
    if payload.type == "webdav" and payload.remote_path:
        return _safe_url(payload.remote_path)
    raise HTTPException(422, {"code": "unsupported_protocol", "field": "type", "message": "Unsupported mount protocol"})


def validate_payload(payload: MountPayload, _actor: str, existing_id: str | None = None) -> tuple[Path, str, list[str]]:
    validate_mount_name(payload.name)
    if payload.type not in MOUNT_TYPES:
        raise HTTPException(422, {"code": "unsupported_protocol", "field": "type", "message": "Unsupported mount protocol"})
    validate_host(payload.host)
    if payload.smb_version not in SMB_VERSIONS or payload.nfs_version not in NFS_VERSIONS:
        raise HTTPException(422, {"code": "invalid_version", "message": "Invalid protocol version"})
    if not MODE_RE.fullmatch(payload.file_mode) or not MODE_RE.fullmatch(payload.dir_mode):
        raise HTTPException(422, {"code": "invalid_mode", "message": "Invalid permission mode"})
    for field_name, values in (("allowed_users", payload.allowed_users), ("allowed_groups", payload.allowed_groups)):
        if any(not USER_RE.fullmatch(value) for value in values):
            raise HTTPException(422, {"code": "invalid_access_entry", "field": field_name, "message": "Invalid user or group name"})
    if payload.uid and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", payload.uid):
        raise HTTPException(422, {"code": "invalid_uid", "field": "uid", "message": "Invalid uid"})
    if payload.gid and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", payload.gid):
        raise HTTPException(422, {"code": "invalid_gid", "field": "gid", "message": "Invalid gid"})
    calculated_mount_point = default_mount_point(payload.name)
    same_existing_point = False
    if existing_id:
        with connect() as conn:
            current = conn.execute("SELECT mount_point FROM mounts WHERE id=?", (existing_id,)).fetchone()
        same_existing_point = bool(current and current["mount_point"] == str(calculated_mount_point))
    mount_point = validate_mount_point(
        calculated_mount_point,
        allow_existing_data=payload.force_empty_mountpoint or same_existing_point,
        name=payload.name,
    )
    options = validate_options(payload.advanced_options)
    remote = remote_for(payload)
    normalized = normalize_mount_name(payload.name)
    with connect() as conn:
        if existing_id:
            duplicate = conn.execute("SELECT id FROM mounts WHERE (normalized_name=? OR mount_point=?) AND id<>?", (normalized, str(mount_point), existing_id)).fetchone()
        else:
            duplicate = conn.execute("SELECT id FROM mounts WHERE normalized_name=? OR mount_point=?", (normalized, str(mount_point))).fetchone()
    if duplicate:
        raise HTTPException(409, {"code": "duplicate_mount", "field": "name", "message": "Resource name or mount point already exists"})
    return mount_point, remote, options


def credentials_path(mount_id: str) -> Path:
    return credentials_dir() / f"{mount_id}.cred"


def davfs_config_path(mount_id: str) -> Path:
    return credentials_dir() / f"{mount_id}.davfs.conf"


def _atomic_secret_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_credentials(mount_id: str, payload: MountPayload) -> None:
    if payload.remove_secret:
        credentials_path(mount_id).unlink(missing_ok=True)
        davfs_config_path(mount_id).unlink(missing_ok=True)
        return
    if not payload.password:
        return
    if payload.type == "smb":
        lines = [f"username={payload.username or ''}", f"password={payload.password}"]
        if payload.domain:
            lines.append(f"domain={payload.domain}")
    elif payload.type == "webdav":
        lines = [remote_for(payload), payload.username or "", payload.password]
    else:
        return
    path = credentials_path(mount_id)
    _atomic_secret_write(path, "\n".join(lines) + "\n")
    if payload.type == "webdav":
        _atomic_secret_write(davfs_config_path(mount_id), f"secrets {path}\nask_auth 0\n")


def safe_config(payload: MountPayload, options: list[str], mount_id: str, existing: dict | None = None) -> dict:
    has_secret = credentials_path(mount_id).exists()
    if existing and not payload.password and not payload.remove_secret:
        has_secret = bool(existing.get("config", {}).get("has_secret")) or has_secret
    return {
        "domain": payload.domain or "", "username": payload.username or "", "smb_version": payload.smb_version,
        "nfs_version": payload.nfs_version, "ssh_port": payload.ssh_port, "ssh_auth": payload.ssh_auth,
        "uid": payload.uid or "", "gid": payload.gid or "", "file_mode": payload.file_mode,
        "dir_mode": payload.dir_mode, "noexec": payload.noexec, "automount": payload.automount,
        "advanced_options": options, "has_secret": has_secret,
    }


def recent_jobs(mount_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mount_jobs WHERE mount_id=? ORDER BY created_at DESC LIMIT 8", (mount_id,)).fetchall()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        item["log_tail"] = json.loads(item.pop("log_tail_json") or "[]")
        result.append(item)
    return result


def _decode_mountinfo(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def actual_mount(path: str | Path) -> dict | None:
    target = str(Path(path))
    try:
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            fields = line.split()
            separator = fields.index("-")
            mount_point = _decode_mountinfo(fields[4])
            if mount_point == target:
                return {"mount_point": mount_point, "fs_type": fields[separator + 1], "source": _decode_mountinfo(fields[separator + 2])}
    except (OSError, ValueError, IndexError):
        pass
    if shutil.which("mountpoint"):
        result = run_command(["mountpoint", "-q", target], timeout=5)
        if result.returncode == 0:
            return {"mount_point": target, "fs_type": fs_type(Path(target)), "source": "unknown"}
    return None


def missing_packages(mount_type: str) -> list[str]:
    packages = {"smb": ["cifs-utils"], "nfs": ["nfs-common"], "sshfs": ["sshfs", "fuse3"], "webdav": ["davfs2"]}[mount_type]
    return [package for package in packages if not package_available(package)]


def _active_job(jobs: list[dict]) -> bool:
    return any(job["status"] in {"queued", "running"} for job in jobs)


def row_to_mount(row: sqlite3.Row, *, reconcile: bool = True) -> dict:
    data = dict(row)
    data["read_only"] = bool(data["read_only"])
    data["persistent"] = bool(data["persistent"])
    data["manual_intervention"] = bool(data.get("manual_intervention", 0))
    data["config"] = json.loads(data.pop("config_json") or "{}")
    data["config"]["has_secret"] = credentials_path(data["id"]).exists()
    data["allowed_users"] = json.loads(data.pop("allowed_users_json") or "[]")
    data["allowed_groups"] = json.loads(data.pop("allowed_groups_json") or "[]")
    data["missing_packages"] = missing_packages(data["type"])
    data.pop("missing_packages_json", None)
    jobs = recent_jobs(data["id"])
    data["jobs"] = jobs
    mounted = actual_mount(data["mount_point"])
    data["actual_mounted"] = mounted is not None
    if reconcile and not _active_job(jobs):
        desired = "mounted" if mounted else "unmounted"
        if data["migration_status"] != "ready":
            desired = "manual_intervention_required" if data["manual_intervention"] else "migration_required"
        elif not mounted and data["missing_packages"]:
            desired = "missing_packages"
        if data["status"] != desired:
            diagnostic = "Stored state said mounted, but the operating system does not report this mount" if data["status"] == "mounted" and not mounted else data["last_error"]
            with connect() as conn:
                conn.execute("UPDATE mounts SET status=?, last_error=?, updated_at=? WHERE id=?", (desired, diagnostic, time.time(), data["id"]))
                conn.commit()
            data["status"] = desired
            data["last_error"] = diagnostic
    data["fs"] = filesystem_payload(Path(data["mount_point"]), mounted)
    return data


def get_mount_or_404(mount_id: str, *, reconcile: bool = True) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM mounts WHERE id=?", (mount_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Mount not found")
    return row_to_mount(row, reconcile=reconcile)


def mount_options(mount: dict) -> list[str]:
    cfg = mount["config"]
    options = [*BASE_OPTIONS, "ro" if mount["read_only"] else "rw"]
    if cfg.get("noexec", True):
        options.append("noexec")
    options.extend(cfg.get("advanced_options") or [])
    if mount["type"] == "smb":
        options.extend([f"credentials={credentials_path(mount['id'])}", f"file_mode={cfg.get('file_mode', '0644')}", f"dir_mode={cfg.get('dir_mode', '0755')}"])
        if cfg.get("smb_version") not in {None, "auto"}:
            options.append(f"vers={cfg['smb_version']}")
        for key in ("uid", "gid"):
            if cfg.get(key):
                options.append(f"{key}={cfg[key]}")
    elif mount["type"] == "nfs" and cfg.get("nfs_version") not in {None, "auto"}:
        options.append(f"vers={cfg['nfs_version']}")
    elif mount["type"] == "sshfs":
        options.extend(["ServerAliveInterval=15", "StrictHostKeyChecking=accept-new", f"port={cfg.get('ssh_port', 22)}"])
    elif mount["type"] == "webdav":
        options.append(f"conf={davfs_config_path(mount['id'])}")
    return list(dict.fromkeys(options))


def redact(value: str, known_secrets: list[str] | None = None) -> str:
    safe = value
    for secret in known_secrets or []:
        if secret:
            safe = safe.replace(secret, "<redacted>")
    safe = re.sub(r"(?i)(password|passwd|token|secret|credentials)(\s*[:=]\s*)([^,\s]+)", r"\1\2<redacted>", safe)
    safe = re.sub(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@", r"\1<redacted>@", safe)
    return safe


def redact_options(options: list[str]) -> list[str]:
    return ["credentials=<webnas-secret-file>" if item.startswith("credentials=") else "conf=<webnas-managed-config>" if item.startswith("conf=") else item for item in options]


def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, shell=False)


def safe_error(value: str) -> str:
    return redact(value).strip()[:1000] or "Operation failed"


def log_line(mount_id: str, action: str, line: str) -> None:
    safe = redact(line)[-1200:]
    with (log_dir() / f"{mount_id}.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {action} {safe}\n")


def set_status(mount_id: str, status: str, error: str = "", action: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE mounts SET status=?, last_error=?, last_operation=CASE WHEN ?='' THEN last_operation ELSE ? END, last_operation_at=?, updated_at=? WHERE id=?",
            (status, safe_error(error) if error else "", action, action, time.time(), time.time(), mount_id),
        )
        conn.commit()


def package_available(package: str) -> bool:
    binary = {"cifs-utils": "mount.cifs", "nfs-common": "mount.nfs", "sshfs": "sshfs", "fuse3": "fusermount3", "davfs2": "mount.davfs"}[package]
    return bool(shutil.which(binary))


def dependency_plan(mount_type: str) -> list[str]:
    missing = missing_packages(mount_type)
    return [f"Install missing package: {package}" for package in missing] or ["Dependencies look available"]


def _fallback_systemd_escape(path: str) -> str:
    escaped_components: list[str] = []
    for component in path.strip("/").split("/"):
        result: list[str] = []
        for char in component:
            if char == "-":
                result.append(r"\x2d")
            elif char.isascii() and (char.isalnum() or char in "_."):
                result.append(char)
            else:
                result.extend(f"\\x{byte:02x}" for byte in char.encode())
        escaped_components.append("".join(result))
    return "-".join(escaped_components) or "-"


def systemd_unit_name(path_or_mount_id: str, suffix: str) -> str:
    path = path_or_mount_id if path_or_mount_id.startswith("/") else str(MOUNT_BASE_DIR / path_or_mount_id)
    if shutil.which("systemd-escape"):
        result = run_command(["systemd-escape", "--path", f"--suffix={suffix}", path], timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return f"{_fallback_systemd_escape(path)}.{suffix}"


def _unit_names(mount: dict) -> tuple[str, str]:
    return systemd_unit_name(mount["mount_point"], "mount"), systemd_unit_name(mount["mount_point"], "automount")


def generate_systemd_units(mount: dict) -> dict[str, str]:
    where = mount["mount_point"]
    fstype = {"smb": "cifs", "nfs": "nfs", "webdav": "davfs", "sshfs": "fuse.sshfs"}[mount["type"]]
    mount_name, automount_name = _unit_names(mount)
    mount_unit = "\n".join([
        "[Unit]", f"Description=WebNAS network mount {mount['name']}", "After=network-online.target", "Wants=network-online.target", "",
        "[Mount]", f"What={mount['remote']}", f"Where={where}", f"Type={fstype}", f"Options={','.join(mount_options(mount))}", "TimeoutSec=120", "",
        "[Install]", "WantedBy=multi-user.target", "",
    ])
    units = {mount_name: mount_unit}
    if mount["config"].get("automount"):
        units[automount_name] = "\n".join([
            "[Unit]", f"Description=WebNAS automount {mount['name']}", "After=network-online.target", "", "[Automount]",
            f"Where={where}", "TimeoutIdleSec=300", "", "[Install]", "WantedBy=multi-user.target", "",
        ])
    return units


def _systemctl(*args: str) -> subprocess.CompletedProcess[str] | None:
    if not shutil.which("systemctl") or str(systemd_dir()) != "/etc/systemd/system":
        return None
    return run_command(["systemctl", *args], timeout=30)


def write_systemd_units(mount: dict) -> None:
    if not mount["persistent"]:
        return
    target = systemd_dir()
    target.mkdir(parents=True, exist_ok=True)
    units = generate_systemd_units(mount)
    for name, content in units.items():
        (target / name).write_text(content, encoding="utf-8")
    _systemctl("daemon-reload")
    mount_name, automount_name = _unit_names(mount)
    _systemctl("enable", automount_name if automount_name in units else mount_name)


def remove_systemd_units(mount: dict) -> None:
    target = systemd_dir()
    names = [*_unit_names(mount), f"webnas-mount-{mount['id']}.mount", f"webnas-mount-{mount['id']}.automount"]
    for name in names:
        _systemctl("disable", "--now", name)
        (target / name).unlink(missing_ok=True)
    _systemctl("daemon-reload")


def command_preview(mount: dict, action: str) -> list[str]:
    if action == "unmount":
        return ["umount", mount["mount_point"]]
    return [*mount_command(mount)[:-3], ",".join(redact_options(mount_options(mount))), *mount_command(mount)[-2:]] if mount["type"] != "sshfs" else ["sshfs", mount["remote"], mount["mount_point"], "-o", ",".join(redact_options(mount_options(mount)))]


def mount_command(mount: dict) -> list[str]:
    options = ",".join(mount_options(mount))
    if mount["type"] == "sshfs":
        return ["sshfs", mount["remote"], mount["mount_point"], "-o", options]
    fstype = {"smb": "cifs", "nfs": "nfs", "webdav": "davfs"}[mount["type"]]
    return ["mount", "-t", fstype, "-o", options, mount["remote"], mount["mount_point"]]


def _prepare_mount_directory(mount: dict, allow_existing_data: bool = False) -> None:
    point = validate_mount_point(mount["mount_point"], allow_existing_data=allow_existing_data, name=mount["name"])
    MOUNT_BASE_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
    if MOUNT_BASE_DIR.is_symlink():
        raise HTTPException(403, "Mount base directory cannot be a symlink")
    point.mkdir(mode=0o750, exist_ok=True)


def execute_mount(mount: dict, action: str) -> subprocess.CompletedProcess[str]:
    if action == "mount":
        if actual_mount(mount["mount_point"]):
            return subprocess.CompletedProcess(["mountpoint", mount["mount_point"]], 0, "Already mounted", "")
        _prepare_mount_directory(mount)
        write_systemd_units(mount)
        return run_command(mount_command(mount), timeout=180)
    if action == "unmount":
        if not actual_mount(mount["mount_point"]):
            return subprocess.CompletedProcess(["umount", mount["mount_point"]], 0, "Already unmounted", "")
        return run_command(["umount", mount["mount_point"]], timeout=90)
    if action == "remount":
        if actual_mount(mount["mount_point"]):
            result = run_command(["umount", mount["mount_point"]], timeout=90)
            if result.returncode:
                return result
        _prepare_mount_directory(mount)
        write_systemd_units(mount)
        return run_command(mount_command(mount), timeout=180)
    raise HTTPException(400, "Unsupported mount action")


def test_mount(mount: dict) -> subprocess.CompletedProcess[str]:
    missing = missing_packages(mount["type"])
    if missing:
        return subprocess.CompletedProcess(["dependency-check"], 3, "", f"Missing packages: {', '.join(missing)}")
    port = {"smb": 445, "nfs": 2049, "sshfs": int(mount["config"].get("ssh_port", 22)), "webdav": 443 if mount["remote"].startswith("https://") else 80}[mount["type"]]
    try:
        with socket.create_connection((mount["host"], port), timeout=5):
            pass
    except OSError as exc:
        return subprocess.CompletedProcess(["connect", mount["host"], str(port)], 2, "", f"Host is unavailable on port {port}: {exc}")
    return subprocess.CompletedProcess(["connect", mount["host"], str(port)], 0, "Connection test passed", "")


def _mount_lock(mount_id: str) -> threading.Lock:
    with _locks_guard:
        return _mount_locks.setdefault(mount_id, threading.Lock())


def _perform_migration(mount: dict) -> subprocess.CompletedProcess[str]:
    old_point = mount["mount_point"]
    new_point = default_mount_point(mount["name"])
    if old_point == str(new_point):
        with connect() as conn:
            conn.execute("UPDATE mounts SET migration_status='ready', manual_intervention=0 WHERE id=?", (mount["id"],))
            conn.commit()
        return subprocess.CompletedProcess(["migrate"], 0, "Already migrated", "")
    validate_mount_point(new_point, name=mount["name"])
    was_mounted = actual_mount(old_point) is not None
    if was_mounted:
        result = run_command(["umount", old_point], timeout=90)
        if result.returncode:
            return result
    old_mount = dict(mount)
    try:
        remove_systemd_units(old_mount)
        with connect() as conn:
            conn.execute("UPDATE mounts SET mount_point=?, migration_status='ready', manual_intervention=0, updated_at=? WHERE id=?", (str(new_point), time.time(), mount["id"]))
            conn.commit()
        updated = get_mount_or_404(mount["id"], reconcile=False)
        write_systemd_units(updated)
        if was_mounted:
            result = execute_mount(updated, "mount")
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
        return subprocess.CompletedProcess(["migrate"], 0, "Migration completed", "")
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE mounts SET mount_point=?, migration_status='required', manual_intervention=1, last_error=? WHERE id=?", (old_point, safe_error(str(exc)), mount["id"]))
            conn.commit()
        write_systemd_units(old_mount)
        if was_mounted and not actual_mount(old_point):
            try:
                execute_mount(old_mount, "mount")
            except Exception as rollback_exc:  # noqa: BLE001
                log_line(mount["id"], "migration-rollback", safe_error(str(rollback_exc)))
        return subprocess.CompletedProcess(["migrate"], 1, "", safe_error(str(exc)))


def enqueue(mount_id: str, action: str) -> dict:
    with connect() as conn:
        conflict = conn.execute("SELECT id FROM mount_jobs WHERE mount_id=? AND status IN ('queued','running')", (mount_id,)).fetchone()
        if conflict:
            raise HTTPException(409, {"code": "operation_in_progress", "message": "Another operation is already running"})
        job_id = uuid4().hex
        conn.execute("INSERT INTO mount_jobs (id, mount_id, action, status, created_at) VALUES (?, ?, ?, 'queued', ?)", (job_id, mount_id, action, time.time()))
        conn.commit()

    def worker() -> None:
        with _mount_lock(mount_id):
            with connect() as conn:
                conn.execute("UPDATE mount_jobs SET status='running' WHERE id=?", (job_id,))
                conn.commit()
            transient = {"mount": "mounting", "unmount": "unmounting", "remount": "remounting", "test": "testing", "migrate": "migrating"}[action]
            set_status(mount_id, transient, action=action)
            mount = get_mount_or_404(mount_id, reconcile=False)
            previous_status = "mounted" if actual_mount(mount["mount_point"]) else "unmounted"
            tail: list[str] = []
            error = ""
            exit_code: int | None = None
            try:
                result = test_mount(mount) if action == "test" else _perform_migration(mount) if action == "migrate" else execute_mount(mount, action)
                exit_code = result.returncode
                tail = (result.stdout or "").splitlines()[-20:] + (result.stderr or "").splitlines()[-20:]
                for line in tail:
                    log_line(mount_id, action, line)
                if result.returncode:
                    error = safe_error(result.stderr or result.stdout)
                    final = "host_unavailable" if result.returncode == 2 else "missing_packages" if result.returncode == 3 else "error"
                elif action == "test":
                    final = previous_status
                elif action == "unmount":
                    final = "unmounted" if not actual_mount(mount["mount_point"]) else "error"
                    if final == "error":
                        error = "Operating system still reports the mount as active"
                elif action == "migrate":
                    final = "mounted" if actual_mount(default_mount_point(mount["name"])) else "unmounted"
                else:
                    final = "mounted" if actual_mount(mount["mount_point"]) else "error"
                    if final == "error":
                        error = "Mount command succeeded, but the operating system does not report the mount"
                set_status(mount_id, final, error, action)
            except Exception as exc:  # noqa: BLE001
                error = safe_error(str(exc))
                set_status(mount_id, "error", error, action)
                log_line(mount_id, action, error)
            with connect() as conn:
                conn.execute("UPDATE mount_jobs SET status=?, exit_code=?, error=?, log_tail_json=?, finished_at=? WHERE id=?", ("failed" if error else "completed", exit_code, error, json.dumps([redact(line) for line in tail[-40:]]), time.time(), job_id))
                conn.commit()

    threading.Thread(target=worker, daemon=True).start()
    return {"id": job_id, "mount_id": mount_id, "action": action, "status": "queued", "exit_code": None, "error": "", "log_tail": []}


def filesystem_payload(path: Path, mounted: dict | None = None) -> dict | None:
    mounted = mounted or actual_mount(path)
    if not mounted:
        return None
    try:
        usage = shutil.disk_usage(path)
        return {"total": usage.total, "used": usage.used, "free": usage.free, "fs_type": mounted.get("fs_type") or fs_type(path)}
    except OSError:
        return None


def fs_type(path: Path) -> str:
    if not shutil.which("findmnt"):
        return "unknown"
    result = run_command(["findmnt", "-n", "-o", "FSTYPE", "--target", str(path)], timeout=5)
    return (result.stdout or "unknown").strip() or "unknown"


def _system_groups(username: str) -> set[str]:
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        return set()
    gids = set(os.getgrouplist(username, account.pw_gid))
    names: set[str] = set()
    for gid in gids:
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            continue
    return names


def user_can_access(username: str, mount: dict) -> bool:
    if _is_admin(username) or mount["owner"] == username or username in mount["allowed_users"]:
        return True
    allowed_groups = set(mount["allowed_groups"])
    if allowed_groups and _system_groups(username).intersection(allowed_groups):
        return True
    # Existing project policy: empty ACLs publish the resource to every authenticated local user.
    return not mount["allowed_users"] and not mount["allowed_groups"]


def _safe_visible_mount(mount: dict) -> bool:
    return (
        mount["status"] == "mounted" and mount["actual_mounted"] and mount["migration_status"] == "ready"
        and not mount["manual_intervention"] and is_managed_mount_point(mount["mount_point"], mount["name"])
        and not _proxmox_storage_conflicts(Path(mount["mount_point"]))
    )


def visible_mount_roots(username: str) -> list[Path]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mounts ORDER BY name").fetchall()
    roots: list[Path] = []
    for row in rows:
        mount = row_to_mount(row)
        if _safe_visible_mount(mount) and user_can_access(username, mount):
            roots.append(Path(mount["mount_point"]))
    return roots


def mount_for_path(path: str | Path) -> dict | None:
    candidate = Path(path).resolve(strict=False)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mounts").fetchall()
    matches: list[tuple[int, dict]] = []
    for row in rows:
        mount = row_to_mount(row)
        if not is_managed_mount_point(mount["mount_point"], mount["name"]):
            continue
        root = Path(mount["mount_point"]).resolve(strict=False)
        if candidate == root or candidate.is_relative_to(root):
            matches.append((len(str(root)), mount))
    return sorted(matches, key=lambda item: item[0], reverse=True)[0][1] if matches else None


def assert_write_allowed(path: str | Path) -> None:
    mount = mount_for_path(path)
    if mount and mount["read_only"]:
        raise HTTPException(403, "Network mount is read-only")


def _admin_mounts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mounts ORDER BY name").fetchall()
    return [row_to_mount(row) for row in rows]


@router.get("/roots")
def mount_roots(user: SessionUser = Depends(current_user)):
    roots = []
    for mount in _admin_mounts():
        if _safe_visible_mount(mount) and user_can_access(user.username, mount):
            roots.append({
                "id": mount["id"], "name": mount["name"], "mount_point": mount["mount_point"],
                "read_only": mount["read_only"], "status": "mounted", "filesystem": mount["fs"],
            })
    return roots


@router.get("")
def list_mounts(user: SessionUser = Depends(current_user)):
    require_admin_session(user, "list_mounts")
    return _admin_mounts()


@router.post("")
def create_mount(payload: MountPayload, user: SessionUser = Depends(current_user)):
    require_admin(user, payload.admin_password, "create_mount")
    mount_id = uuid4().hex[:16]
    mount_point, remote, options = validate_payload(payload, user.username)
    write_credentials(mount_id, payload)
    config = safe_config(payload, options, mount_id)
    now = time.time()
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO mounts
                (id,name,normalized_name,type,host,remote,mount_point,owner,read_only,persistent,status,config_json,allowed_users_json,allowed_groups_json,created_at,updated_at,migration_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'ready')""",
                (mount_id, payload.name, normalize_mount_name(payload.name), payload.type, payload.host, remote, str(mount_point), user.username,
                 int(payload.read_only), int(payload.persistent), "unmounted", json.dumps(config), json.dumps(payload.allowed_users), json.dumps(payload.allowed_groups), now, now),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        credentials_path(mount_id).unlink(missing_ok=True)
        raise HTTPException(409, {"code": "duplicate_mount", "field": "name", "message": "Resource already exists"}) from exc
    audit(user.username, "create_mount", mount_id)
    return get_mount_or_404(mount_id)


@router.get("/{mount_id}")
def get_mount(mount_id: str, user: SessionUser = Depends(current_user)):
    require_admin_session(user, "get_mount")
    return get_mount_or_404(mount_id)


@router.put("/{mount_id}")
def update_mount(mount_id: str, payload: MountPayload, user: SessionUser = Depends(current_user)):
    require_admin(user, payload.admin_password, "update_mount")
    with _mount_lock(mount_id):
        old = get_mount_or_404(mount_id)
        mount_point, remote, options = validate_payload(payload, user.username, mount_id)
        was_mounted = old["actual_mounted"]
        old_config = old["config"]
        definition_changed = any(
            (
                str(mount_point) != old["mount_point"], remote != old["remote"], payload.type != old["type"],
                payload.read_only != old["read_only"], payload.persistent != old["persistent"],
                payload.automount != bool(old_config.get("automount")), payload.smb_version != old_config.get("smb_version", "auto"),
                payload.nfs_version != old_config.get("nfs_version", "auto"), payload.ssh_port != int(old_config.get("ssh_port", 22)),
                payload.noexec != bool(old_config.get("noexec", True)), options != old_config.get("advanced_options", []),
                (payload.uid or "") != old_config.get("uid", ""), (payload.gid or "") != old_config.get("gid", ""),
                payload.file_mode != old_config.get("file_mode", "0644"), payload.dir_mode != old_config.get("dir_mode", "0755"),
            )
        )
        if was_mounted and definition_changed:
            result = execute_mount(old, "unmount")
            if result.returncode:
                raise HTTPException(409, {"code": "unmount_failed", "message": safe_error(result.stderr or result.stdout)})
        old_credential = credentials_path(mount_id).read_bytes() if credentials_path(mount_id).exists() else None
        old_davfs_config = davfs_config_path(mount_id).read_bytes() if davfs_config_path(mount_id).exists() else None
        try:
            remove_systemd_units(old)
            write_credentials(mount_id, payload)
            config = safe_config(payload, options, mount_id, old)
            with connect() as conn:
                conn.execute(
                    """UPDATE mounts SET name=?, normalized_name=?, type=?, host=?, remote=?, mount_point=?, read_only=?, persistent=?,
                    config_json=?, allowed_users_json=?, allowed_groups_json=?, migration_status='ready', manual_intervention=0, updated_at=? WHERE id=?""",
                    (payload.name, normalize_mount_name(payload.name), payload.type, payload.host, remote, str(mount_point), int(payload.read_only), int(payload.persistent),
                     json.dumps(config), json.dumps(payload.allowed_users), json.dumps(payload.allowed_groups), time.time(), mount_id),
                )
                conn.commit()
            updated = get_mount_or_404(mount_id, reconcile=False)
            write_systemd_units(updated)
            if was_mounted:
                result = execute_mount(updated, "mount")
                if result.returncode or not actual_mount(updated["mount_point"]):
                    raise RuntimeError(result.stderr or result.stdout or "Updated resource could not be mounted")
            old_point = Path(old["mount_point"])
            if old_point != mount_point and is_managed_mount_point(old_point, old["name"]) and old_point.exists() and not any(old_point.iterdir()):
                old_point.rmdir()
        except Exception as exc:
            with connect() as conn:
                conn.execute(
                    """UPDATE mounts SET name=?, normalized_name=?, type=?, host=?, remote=?, mount_point=?, read_only=?, persistent=?,
                    config_json=?, allowed_users_json=?, allowed_groups_json=?, migration_status=?, manual_intervention=?, status=?, last_error=?, updated_at=? WHERE id=?""",
                    (old["name"], old["normalized_name"], old["type"], old["host"], old["remote"], old["mount_point"], int(old["read_only"]), int(old["persistent"]),
                     json.dumps(old["config"]), json.dumps(old["allowed_users"]), json.dumps(old["allowed_groups"]), old["migration_status"], int(old["manual_intervention"]), old["status"], safe_error(str(exc)), time.time(), mount_id),
                )
                conn.commit()
            if old_credential is not None:
                _atomic_secret_write(credentials_path(mount_id), old_credential.decode("utf-8"))
            elif not old["config"].get("has_secret"):
                credentials_path(mount_id).unlink(missing_ok=True)
            if old_davfs_config is not None:
                _atomic_secret_write(davfs_config_path(mount_id), old_davfs_config.decode("utf-8"))
            else:
                davfs_config_path(mount_id).unlink(missing_ok=True)
            write_systemd_units(old)
            if was_mounted and not actual_mount(old["mount_point"]):
                try:
                    execute_mount(old, "mount")
                except Exception as rollback_exc:  # noqa: BLE001
                    log_line(mount_id, "update-rollback", safe_error(str(rollback_exc)))
            raise HTTPException(500, {"code": "update_rollback", "message": "Update failed and the previous definition was restored"}) from exc
    audit(user.username, "update_mount", mount_id)
    return get_mount_or_404(mount_id)


@router.delete("/{mount_id}")
def delete_mount(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    require_admin(user, payload.admin_password, "delete_mount")
    with _mount_lock(mount_id):
        mount = get_mount_or_404(mount_id)
        if mount["actual_mounted"]:
            if not payload.confirm_destructive:
                raise HTTPException(409, {"code": "confirmation_required", "message": "Confirm controlled unmount before deletion"})
            result = execute_mount(mount, "unmount")
            if result.returncode or actual_mount(mount["mount_point"]):
                raise HTTPException(409, {"code": "unmount_failed", "message": safe_error(result.stderr or result.stdout)})
        remove_systemd_units(mount)
        credentials_path(mount_id).unlink(missing_ok=True)
        davfs_config_path(mount_id).unlink(missing_ok=True)
        point = Path(mount["mount_point"])
        if is_managed_mount_point(point, mount["name"]) and point.exists() and not any(point.iterdir()):
            point.rmdir()
        with connect() as conn:
            conn.execute("DELETE FROM mount_jobs WHERE mount_id=?", (mount_id,))
            conn.execute("DELETE FROM mounts WHERE id=?", (mount_id,))
            conn.commit()
    audit(user.username, "delete_mount", mount_id)
    return {"ok": True}


def action_response(mount_id: str, action: str, payload: AdminMountAction, user: SessionUser):
    require_admin(user, payload.admin_password, f"{action}_mount")
    mount = get_mount_or_404(mount_id)
    if payload.dry_run:
        return {"dry_run": True, "dependencies": dependency_plan(mount["type"]), "command": command_preview(mount, "unmount" if action == "unmount" else "mount")}
    missing = missing_packages(mount["type"])
    if action in {"mount", "remount", "test"} and missing:
        set_status(mount_id, "missing_packages", f"Missing packages: {', '.join(missing)}", action)
        raise HTTPException(409, {"code": "missing_packages", "message": "Required packages are missing", "missing_packages": missing})
    if action == "mount":
        validate_mount_point(mount["mount_point"], allow_existing_data=payload.force_empty_mountpoint, name=mount["name"])
    elif action != "migrate":
        validate_mount_point(mount["mount_point"], allow_existing_data=True, name=mount["name"])
    audit(user.username, f"{action}_mount", mount_id)
    return {"job": enqueue(mount_id, action)}


@router.post("/{mount_id}/mount")
def mount_now(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    return action_response(mount_id, "mount", payload, user)


@router.post("/{mount_id}/unmount")
def unmount_now(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    return action_response(mount_id, "unmount", payload, user)


@router.post("/{mount_id}/remount")
def remount_now(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    return action_response(mount_id, "remount", payload, user)


@router.post("/{mount_id}/test")
def test_now(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    return action_response(mount_id, "test", payload, user)


@router.post("/{mount_id}/migrate")
def migrate_now(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    return action_response(mount_id, "migrate", payload, user)


@router.get("/{mount_id}/logs")
def mount_logs(mount_id: str, user: SessionUser = Depends(current_user)):
    require_admin_session(user, "mount_logs")
    get_mount_or_404(mount_id)
    path = log_dir() / f"{mount_id}.log"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:] if path.exists() else []
    return {"lines": [redact(line) for line in lines]}
