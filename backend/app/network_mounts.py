from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .audit import logger
from .auth import authenticate
from .config import get_config
from .proxmox_guard import assert_path_allowed, safe_mode_active
from .security import SessionUser, get_session_user, require_csrf
from .settings import _is_admin

router = APIRouter(prefix="/api/mounts")

MOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}$")
SHARE_RE = re.compile(r"^[A-Za-z0-9_$][A-Za-z0-9_. $-]{0,127}$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.@-]{0,63}\$?$")
MODE_RE = re.compile(r"^0?[0-7]{3,4}$")
MOUNT_TYPES = {"smb", "nfs", "sshfs", "webdav"}
SMB_VERSIONS = {"auto", "2.1", "3.0", "3.1.1"}
NFS_VERSIONS = {"auto", "3", "4", "4.1", "4.2"}
SSH_AUTH = {"key", "password"}
BLOCKED_OPTIONS = {
    "dev",
    "suid",
    "exec",
    "allow_other",
    "users",
    "user",
    "owner",
    "group",
    "credentials",
    "password",
    "passwd",
    "pass",
}
BASE_OPTIONS = ["nosuid", "nodev", "_netdev", "nofail"]
PERSISTENT_OPTIONS = ["x-systemd.automount"]
BLOCKED_MOUNT_PATHS = (
    "/",
    "/etc",
    "/boot",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var",
    "/var/lib",
    "/var/lib/vz",
    "/etc/pve",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
)


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
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path
    except PermissionError:
        fallback = state_dir() / "credentials"
        fallback.mkdir(parents=True, exist_ok=True)
        os.chmod(fallback, 0o700)
        return fallback


def systemd_dir() -> Path:
    path = Path("/etc/systemd/system")
    return path if os.access(path, os.W_OK) else state_dir() / "systemd"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            host TEXT NOT NULL,
            remote TEXT NOT NULL,
            mount_point TEXT NOT NULL,
            owner TEXT NOT NULL,
            read_only INTEGER NOT NULL DEFAULT 0,
            persistent INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unmounted',
            config_json TEXT NOT NULL,
            allowed_users_json TEXT NOT NULL,
            allowed_groups_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mount_jobs (
            id TEXT PRIMARY KEY,
            mount_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            exit_code INTEGER,
            error TEXT NOT NULL DEFAULT '',
            log_tail_json TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL,
            finished_at REAL
        )
        """
    )
    conn.commit()
    return conn


class AdminMountAction(BaseModel):
    admin_password: str
    dry_run: bool = False
    force_empty_mountpoint: bool = False


class MountPayload(BaseModel):
    admin_password: str
    name: str
    type: str
    host: str
    share: str | None = None
    export_path: str | None = None
    remote_path: str | None = None
    mount_point: str | None = None
    username: str | None = None
    password: str | None = None
    domain: str | None = None
    smb_version: str = "auto"
    nfs_version: str = "auto"
    ssh_port: int = 22
    ssh_auth: str = "key"
    read_only: bool = False
    persistent: bool = False
    uid: str | None = None
    gid: str | None = None
    file_mode: str = "0644"
    dir_mode: str = "0755"
    noexec: bool = True
    advanced_options: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)
    allowed_groups: list[str] = Field(default_factory=list)
    force_empty_mountpoint: bool = False


def current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def require_admin(user: SessionUser, password: str, action: str) -> None:
    if not _is_admin(user.username):
        logger.info("network_mount_denied actor=%s action=%s reason=not_admin", user.username, action)
        raise HTTPException(403, "Administrator privileges required")
    authenticate(user.username, password)


def audit(actor: str, action: str, target: str) -> None:
    logger.info("network_mount_action actor=%s action=%s target=%s", actor, action, target)


def row_to_mount(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["read_only"] = bool(data["read_only"])
    data["persistent"] = bool(data["persistent"])
    data["config"] = json.loads(data.pop("config_json") or "{}")
    data["allowed_users"] = json.loads(data.pop("allowed_users_json") or "[]")
    data["allowed_groups"] = json.loads(data.pop("allowed_groups_json") or "[]")
    data["jobs"] = recent_jobs(data["id"])
    data["fs"] = filesystem_payload(Path(data["mount_point"]))
    return data


def recent_jobs(mount_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mount_jobs WHERE mount_id=? ORDER BY created_at DESC LIMIT 8", (mount_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["log_tail"] = json.loads(item.pop("log_tail_json") or "[]")
        result.append(item)
    return result


def get_mount_or_404(mount_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM mounts WHERE id=?", (mount_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Mount not found")
    return row_to_mount(row)


def default_mount_point(owner: str, name: str) -> Path:
    return Path("/mnt/webnas") / owner / name


def validate_mount_name(name: str) -> None:
    if not MOUNT_NAME_RE.fullmatch(name):
        raise HTTPException(400, "Invalid mount name")


def validate_host(host: str) -> None:
    if not HOST_RE.fullmatch(host):
        raise HTTPException(400, "Invalid host")


def validate_options(options: list[str]) -> list[str]:
    cleaned = []
    for raw in options:
        option = raw.strip()
        if not option:
            continue
        key = option.split("=", 1)[0].lower()
        if not re.fullmatch(r"[A-Za-z0-9_.=-]+", option) or key in BLOCKED_OPTIONS:
            raise HTTPException(400, f"Blocked mount option: {key}")
        cleaned.append(option)
    return cleaned


def validate_mount_point(path: str | Path, *, allow_existing_data: bool = False) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    for blocked in BLOCKED_MOUNT_PATHS:
        blocked_path = Path(blocked)
        if candidate == blocked_path or (blocked != "/" and candidate.is_relative_to(blocked_path)):
            logger.info("network_mount_denied action=validate_mount_point target=%s reason=blocked_path", candidate)
            raise HTTPException(403, "Mount point is protected")
    if safe_mode_active() and candidate.is_relative_to(Path("/var/lib/vz")):
        logger.info("network_mount_denied action=validate_mount_point target=%s reason=proxmox_storage", candidate)
        raise HTTPException(403, "Proxmox storage paths are blocked by Safe Mode")
    assert_path_allowed(candidate, "network_mount", include_parent=True)
    if candidate.exists() and any(candidate.iterdir()) and not allow_existing_data:
        raise HTTPException(409, "Mount point is not empty; confirm explicitly to continue")
    return candidate


def remote_for(payload: MountPayload) -> str:
    if payload.type == "smb":
        if not payload.share or not SHARE_RE.fullmatch(payload.share):
            raise HTTPException(400, "Invalid SMB share")
        return f"//{payload.host}/{payload.share}"
    if payload.type == "nfs":
        if not payload.export_path or not payload.export_path.startswith("/") or "\n" in payload.export_path:
            raise HTTPException(400, "Invalid NFS export path")
        return f"{payload.host}:{payload.export_path}"
    if payload.type == "sshfs":
        if not payload.username or not USER_RE.fullmatch(payload.username):
            raise HTTPException(400, "Invalid SSHFS username")
        if not payload.remote_path or not payload.remote_path.startswith("/") or "\n" in payload.remote_path:
            raise HTTPException(400, "Invalid SSHFS remote path")
        if payload.ssh_port < 1 or payload.ssh_port > 65535:
            raise HTTPException(400, "Invalid SSHFS port")
        return f"{payload.username}@{payload.host}:{payload.remote_path}"
    if payload.type == "webdav":
        if not payload.remote_path or not payload.remote_path.startswith(("http://", "https://")):
            raise HTTPException(400, "Invalid WebDAV URL")
        return payload.remote_path
    raise HTTPException(400, "Unsupported mount type")


def validate_payload(payload: MountPayload, actor: str, existing_id: str | None = None) -> tuple[Path, str, list[str]]:
    validate_mount_name(payload.name)
    if payload.type not in MOUNT_TYPES:
        raise HTTPException(400, "Unsupported mount type")
    validate_host(payload.host)
    if payload.smb_version not in SMB_VERSIONS:
        raise HTTPException(400, "Invalid SMB version")
    if payload.nfs_version not in NFS_VERSIONS:
        raise HTTPException(400, "Invalid NFS version")
    if payload.ssh_auth not in SSH_AUTH:
        raise HTTPException(400, "Invalid SSHFS authentication method")
    if not MODE_RE.fullmatch(payload.file_mode) or not MODE_RE.fullmatch(payload.dir_mode):
        raise HTTPException(400, "Invalid permission mode")
    if payload.uid and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", payload.uid):
        raise HTTPException(400, "Invalid uid")
    if payload.gid and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", payload.gid):
        raise HTTPException(400, "Invalid gid")
    for username in payload.allowed_users:
        if not USER_RE.fullmatch(username):
            raise HTTPException(400, "Invalid allowed user")
    for group in payload.allowed_groups:
        if not USER_RE.fullmatch(group):
            raise HTTPException(400, "Invalid allowed group")
    options = validate_options(payload.advanced_options)
    mount_point = validate_mount_point(payload.mount_point or default_mount_point(actor, payload.name), allow_existing_data=payload.force_empty_mountpoint)
    remote = remote_for(payload)
    if existing_id:
        with connect() as conn:
            row = conn.execute("SELECT id FROM mounts WHERE name=? AND id<>?", (payload.name, existing_id)).fetchone()
    else:
        with connect() as conn:
            row = conn.execute("SELECT id FROM mounts WHERE name=?", (payload.name,)).fetchone()
    if row:
        raise HTTPException(409, "Mount name already exists")
    return mount_point, remote, options


def safe_config(payload: MountPayload, options: list[str]) -> dict:
    return {
        "domain": payload.domain or "",
        "username": payload.username or "",
        "smb_version": payload.smb_version,
        "nfs_version": payload.nfs_version,
        "ssh_port": payload.ssh_port,
        "ssh_auth": payload.ssh_auth,
        "uid": payload.uid or "",
        "gid": payload.gid or "",
        "file_mode": payload.file_mode,
        "dir_mode": payload.dir_mode,
        "noexec": payload.noexec,
        "advanced_options": options,
        "has_secret": bool(payload.password),
    }


def credentials_path(mount_id: str) -> Path:
    return credentials_dir() / f"{mount_id}.cred"


def write_credentials(mount_id: str, payload: MountPayload) -> None:
    if not payload.password:
        return
    path = credentials_path(mount_id)
    if payload.type == "smb":
        lines = [f"username={payload.username or ''}", f"password={payload.password}"]
        if payload.domain:
            lines.append(f"domain={payload.domain}")
    elif payload.type == "webdav":
        lines = [payload.remote_path or "", payload.username or "", payload.password]
    elif payload.type == "sshfs":
        lines = [payload.password]
    else:
        return
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def mount_options(mount: dict) -> list[str]:
    cfg = mount["config"]
    options = [*BASE_OPTIONS]
    if mount["persistent"]:
        options.extend(PERSISTENT_OPTIONS)
    if mount["read_only"]:
        options.append("ro")
    else:
        options.append("rw")
    if cfg.get("noexec"):
        options.append("noexec")
    options.extend(cfg.get("advanced_options") or [])
    if mount["type"] == "smb":
        cred = credentials_path(mount["id"])
        options.extend([f"credentials={cred}", f"file_mode={cfg.get('file_mode', '0644')}", f"dir_mode={cfg.get('dir_mode', '0755')}"])
        if cfg.get("smb_version") and cfg["smb_version"] != "auto":
            options.append(f"vers={cfg['smb_version']}")
        if cfg.get("uid"):
            options.append(f"uid={cfg['uid']}")
        if cfg.get("gid"):
            options.append(f"gid={cfg['gid']}")
    elif mount["type"] == "nfs":
        if cfg.get("nfs_version") and cfg["nfs_version"] != "auto":
            options.append(f"vers={cfg['nfs_version']}")
    elif mount["type"] == "sshfs":
        options.extend(["ServerAliveInterval=15", "StrictHostKeyChecking=accept-new"])
        if cfg.get("ssh_port"):
            options.append(f"port={cfg['ssh_port']}")
    return options


def command_preview(mount: dict, action: str) -> list[str]:
    if action == "unmount":
        return ["umount", mount["mount_point"]]
    if mount["type"] == "smb":
        fstype = "cifs"
    elif mount["type"] == "nfs":
        fstype = "nfs"
    elif mount["type"] == "sshfs":
        return ["sshfs", mount["remote"], mount["mount_point"], "-o", ",".join(o for o in mount_options(mount) if not o.startswith("credentials="))]
    else:
        fstype = "davfs"
    return ["mount", "-t", fstype, "-o", ",".join(redact_options(mount_options(mount))), mount["remote"], mount["mount_point"]]


def redact_options(options: list[str]) -> list[str]:
    return ["credentials=<webnas-secret-file>" if item.startswith("credentials=") else item for item in options]


def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, shell=False)


def log_line(mount_id: str, action: str, line: str) -> None:
    safe = re.sub(r"(password|passwd|token|secret)=([^,\s]+)", r"\1=<redacted>", line, flags=re.IGNORECASE)
    with (log_dir() / f"{mount_id}.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {action} {safe[-1200:]}\n")


def set_status(mount_id: str, status: str, error: str = "") -> None:
    with connect() as conn:
        conn.execute("UPDATE mounts SET status=?, last_error=?, updated_at=? WHERE id=?", (status, error[:1000], time.time(), mount_id))
        conn.commit()


def dependency_plan(mount_type: str) -> list[str]:
    packages = {
        "smb": ["cifs-utils"],
        "nfs": ["nfs-common"],
        "sshfs": ["sshfs", "fuse3"],
        "webdav": ["davfs2"],
    }[mount_type]
    missing = [pkg for pkg in packages if not package_available(pkg)]
    return [f"Install missing package: {pkg}" for pkg in missing] or ["Dependencies look available"]


def package_available(package: str) -> bool:
    binaries = {
        "cifs-utils": "mount.cifs",
        "nfs-common": "mount.nfs",
        "sshfs": "sshfs",
        "fuse3": "fusermount3",
        "davfs2": "mount.davfs",
    }
    return bool(shutil.which(binaries[package]))


def systemd_unit_name(mount_id: str, suffix: str) -> str:
    return f"webnas-mount-{mount_id}.{suffix}"


def generate_systemd_units(mount: dict) -> dict[str, str]:
    where = mount["mount_point"]
    what = mount["remote"]
    options = ",".join(mount_options(mount))
    if mount["type"] == "smb":
        fstype = "cifs"
    elif mount["type"] == "nfs":
        fstype = "nfs"
    elif mount["type"] == "webdav":
        fstype = "davfs"
    else:
        fstype = "fuse.sshfs"
    mount_unit = "\n".join([
        "[Unit]",
        f"Description=WebNAS network mount {mount['name']}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Mount]",
        f"What={what}",
        f"Where={where}",
        f"Type={fstype}",
        f"Options={options}",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
    automount_unit = "\n".join([
        "[Unit]",
        f"Description=WebNAS automount {mount['name']}",
        "",
        "[Automount]",
        f"Where={where}",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
    return {systemd_unit_name(mount["id"], "mount"): mount_unit, systemd_unit_name(mount["id"], "automount"): automount_unit}


def write_systemd_units(mount: dict) -> None:
    if not mount["persistent"]:
        return
    target = systemd_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name, content in generate_systemd_units(mount).items():
        (target / name).write_text(content, encoding="utf-8")
    if shutil.which("systemctl") and str(target) == "/etc/systemd/system":
        run_command(["systemctl", "daemon-reload"], timeout=30)
        run_command(["systemctl", "enable", systemd_unit_name(mount["id"], "automount")], timeout=30)


def remove_systemd_units(mount: dict) -> None:
    target = systemd_dir()
    if shutil.which("systemctl") and str(target) == "/etc/systemd/system":
        run_command(["systemctl", "disable", "--now", systemd_unit_name(mount["id"], "automount")], timeout=30)
    for suffix in ("mount", "automount"):
        (target / systemd_unit_name(mount["id"], suffix)).unlink(missing_ok=True)
    if shutil.which("systemctl") and str(target) == "/etc/systemd/system":
        run_command(["systemctl", "daemon-reload"], timeout=30)


def mount_command(mount: dict) -> list[str]:
    Path(mount["mount_point"]).mkdir(parents=True, exist_ok=True)
    options = ",".join(mount_options(mount))
    if mount["type"] == "sshfs":
        return ["sshfs", mount["remote"], mount["mount_point"], "-o", options]
    fstype = {"smb": "cifs", "nfs": "nfs", "webdav": "davfs"}[mount["type"]]
    return ["mount", "-t", fstype, "-o", options, mount["remote"], mount["mount_point"]]


def execute_mount(mount: dict, action: str) -> subprocess.CompletedProcess[str]:
    if action == "mount":
        write_systemd_units(mount)
        return run_command(mount_command(mount), timeout=180)
    if action == "unmount":
        return run_command(["umount", mount["mount_point"]], timeout=90)
    if action == "remount":
        run_command(["umount", mount["mount_point"]], timeout=90)
        write_systemd_units(mount)
        return run_command(mount_command(mount), timeout=180)
    raise HTTPException(400, "Unsupported mount action")


def enqueue(mount_id: str, action: str) -> dict:
    job_id = uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO mount_jobs (id, mount_id, action, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, mount_id, action, "queued", time.time()),
        )
        conn.commit()

    def worker() -> None:
        status = {"mount": "mounting", "unmount": "unmounting", "remount": "mounting", "test": "testing"}[action]
        set_status(mount_id, status)
        mount = get_mount_or_404(mount_id)
        tail: list[str] = []
        exit_code: int | None = None
        error = ""
        try:
            if action == "test":
                result = test_mount(mount)
            else:
                result = execute_mount(mount, action)
            exit_code = result.returncode
            tail.extend((result.stdout or "").splitlines()[-20:])
            tail.extend((result.stderr or "").splitlines()[-20:])
            for line in tail:
                log_line(mount_id, action, line)
            if result.returncode != 0:
                error = safe_error(result.stderr or result.stdout or "Mount command failed")
                set_status(mount_id, "error", error)
            elif action == "unmount":
                set_status(mount_id, "unmounted")
            elif action == "test":
                current_status = str(mount.get("status") or "unmounted")
                set_status(mount_id, current_status if current_status != "testing" else "unmounted")
            else:
                set_status(mount_id, "mounted")
        except Exception as exc:  # noqa: BLE001
            error = safe_error(str(exc))
            set_status(mount_id, "error", error)
            log_line(mount_id, action, error)
        with connect() as conn:
            conn.execute(
                "UPDATE mount_jobs SET status=?, exit_code=?, error=?, log_tail_json=?, finished_at=? WHERE id=?",
                ("failed" if error else "completed", exit_code, error, json.dumps(tail[-40:]), time.time(), job_id),
            )
            conn.commit()

    threading.Thread(target=worker, daemon=True).start()
    return {"id": job_id, "mount_id": mount_id, "action": action, "status": "queued", "exit_code": None, "error": "", "log_tail": []}


def safe_error(value: str) -> str:
    cleaned = re.sub(r"(password|passwd|token|secret)=([^,\s]+)", r"\1=<redacted>", value, flags=re.IGNORECASE)
    return cleaned.strip()[:1000] or "Operation failed"


def test_mount(mount: dict) -> subprocess.CompletedProcess[str]:
    host = mount["host"]
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return subprocess.CompletedProcess(["dns", host], 2, "", f"DNS lookup failed: {exc}")
    if mount["type"] == "nfs" and shutil.which("showmount"):
        return run_command(["showmount", "-e", host], timeout=30)
    return subprocess.CompletedProcess(["test", mount["id"]], 0, "Basic host validation passed", "")


def filesystem_payload(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        usage = shutil.disk_usage(path)
        return {"total": usage.total, "used": usage.used, "free": usage.free, "fs_type": fs_type(path)}
    except OSError:
        return None


def fs_type(path: Path) -> str:
    if not shutil.which("findmnt"):
        return "unknown"
    result = run_command(["findmnt", "-n", "-o", "FSTYPE", "--target", str(path)], timeout=5)
    return (result.stdout or "unknown").strip() or "unknown"


def visible_mount_roots(username: str) -> list[Path]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mounts WHERE status IN ('mounted', 'unmounted', 'error')").fetchall()
    roots = []
    for row in rows:
        item = row_to_mount(row)
        if user_can_access(username, item):
            roots.append(Path(item["mount_point"]))
    return roots


def user_can_access(username: str, mount: dict) -> bool:
    if mount["owner"] == username or not mount["allowed_users"] and not mount["allowed_groups"]:
        return True
    if username in mount["allowed_users"]:
        return True
    return False


def mount_for_path(path: str | Path) -> dict | None:
    candidate = Path(path).resolve(strict=False)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mounts").fetchall()
    matches = []
    for row in rows:
        item = row_to_mount(row)
        root = Path(item["mount_point"]).resolve(strict=False)
        if candidate == root or candidate.is_relative_to(root):
            matches.append((len(str(root)), item))
    if not matches:
        return None
    return sorted(matches, reverse=True)[0][1]


def assert_write_allowed(path: str | Path) -> None:
    mount = mount_for_path(path)
    if mount and mount["read_only"]:
        raise HTTPException(403, "Network mount is read-only")


@router.get("")
def list_mounts(user: SessionUser = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mounts ORDER BY name").fetchall()
    mounts = [row_to_mount(row) for row in rows]
    if _is_admin(user.username):
        return mounts
    return [mount for mount in mounts if user_can_access(user.username, mount)]


@router.get("/{mount_id}")
def get_mount(mount_id: str, user: SessionUser = Depends(current_user)):
    mount = get_mount_or_404(mount_id)
    if not _is_admin(user.username) and not user_can_access(user.username, mount):
        raise HTTPException(403, "Mount is not available for this user")
    return mount


@router.post("")
def create_mount(payload: MountPayload, user: SessionUser = Depends(current_user)):
    require_admin(user, payload.admin_password, "create_mount")
    mount_id = uuid4().hex[:16]
    mount_point, remote, options = validate_payload(payload, user.username)
    write_credentials(mount_id, payload)
    now = time.time()
    config = safe_config(payload, options)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mounts (id, name, type, host, remote, mount_point, owner, read_only, persistent, status, config_json, allowed_users_json, allowed_groups_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mount_id,
                payload.name,
                payload.type,
                payload.host,
                remote,
                str(mount_point),
                user.username,
                int(payload.read_only),
                int(payload.persistent),
                "unmounted",
                json.dumps(config),
                json.dumps(payload.allowed_users),
                json.dumps(payload.allowed_groups),
                now,
                now,
            ),
        )
        conn.commit()
    audit(user.username, "create_mount", mount_id)
    return get_mount_or_404(mount_id)


@router.put("/{mount_id}")
def update_mount(mount_id: str, payload: MountPayload, user: SessionUser = Depends(current_user)):
    require_admin(user, payload.admin_password, "update_mount")
    get_mount_or_404(mount_id)
    mount_point, remote, options = validate_payload(payload, user.username, existing_id=mount_id)
    write_credentials(mount_id, payload)
    config = safe_config(payload, options)
    with connect() as conn:
        conn.execute(
            """
            UPDATE mounts SET name=?, type=?, host=?, remote=?, mount_point=?, read_only=?, persistent=?, config_json=?, allowed_users_json=?, allowed_groups_json=?, updated_at=?
            WHERE id=?
            """,
            (
                payload.name,
                payload.type,
                payload.host,
                remote,
                str(mount_point),
                int(payload.read_only),
                int(payload.persistent),
                json.dumps(config),
                json.dumps(payload.allowed_users),
                json.dumps(payload.allowed_groups),
                time.time(),
                mount_id,
            ),
        )
        conn.commit()
    audit(user.username, "update_mount", mount_id)
    return get_mount_or_404(mount_id)


@router.delete("/{mount_id}")
def delete_mount(mount_id: str, payload: AdminMountAction, user: SessionUser = Depends(current_user)):
    require_admin(user, payload.admin_password, "delete_mount")
    mount = get_mount_or_404(mount_id)
    remove_systemd_units(mount)
    credentials_path(mount_id).unlink(missing_ok=True)
    with connect() as conn:
        conn.execute("DELETE FROM mounts WHERE id=?", (mount_id,))
        conn.commit()
    audit(user.username, "delete_mount", mount_id)
    return {"ok": True}


def action_response(mount_id: str, action: str, payload: AdminMountAction, user: SessionUser):
    require_admin(user, payload.admin_password, f"{action}_mount")
    mount = get_mount_or_404(mount_id)
    if payload.dry_run:
        return {"dry_run": True, "dependencies": dependency_plan(mount["type"]), "command": command_preview(mount, "unmount" if action == "unmount" else "mount")}
    if action == "mount":
        validate_mount_point(mount["mount_point"], allow_existing_data=payload.force_empty_mountpoint)
    else:
        validate_mount_point(mount["mount_point"], allow_existing_data=True)
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


@router.get("/{mount_id}/logs")
def mount_logs(mount_id: str, user: SessionUser = Depends(current_user)):
    mount = get_mount_or_404(mount_id)
    if not _is_admin(user.username) and not user_can_access(user.username, mount):
        raise HTTPException(403, "Mount is not available for this user")
    path = log_dir() / f"{mount_id}.log"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:] if path.exists() else []
    return {"lines": lines}
