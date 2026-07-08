from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .audit import logger
from .auth import authenticate
from .path_policy import resolve_user_path
from .proxmox_guard import safe_mode_active
from .security import SessionUser, get_session_user, require_csrf

router = APIRouter(prefix="/api/apps")

MODULES_DIR = Path(__file__).resolve().parent / "modules"
APP_STATE_DIR = Path("/etc/webnas/apps")
APP_LOG_DIR = Path("/var/log/webnas/apps")
SAMBA_CONF = Path("/etc/samba/smb.conf")
SHARE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")
SAFE_TEXT_RE = re.compile(r"^[^\r\n\[\]]{0,200}$")
USER_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}\$?$")
MASK_RE = re.compile(r"^0?[0-7]{3,4}$")
BLOCKED_SHARE_PATHS = (
    "/",
    "/etc",
    "/boot",
    "/usr",
    "/var/lib/pve-cluster",
    "/etc/pve",
    "/proc",
    "/sys",
    "/dev",
    "/run",
)


class AdminAction(BaseModel):
    admin_password: str
    dry_run: bool = False


class SambaPassword(AdminAction):
    username: str
    password: str


class SambaShare(BaseModel):
    name: str
    path: str
    comment: str = ""
    enabled: bool = True
    browseable: bool = True
    read_only: bool = True
    guest_ok: bool = False
    valid_users: list[str] = Field(default_factory=list)
    force_user: str | None = None
    create_mask: str = "0664"
    directory_mask: str = "0775"
    allow_proxmox_storage: bool = False


class SambaConfig(BaseModel):
    shares: list[SambaShare] = Field(default_factory=list)


@dataclass
class AppJob:
    id: str
    app_id: str
    action: str
    status: str = "queued"
    progress: int = 0
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    log_tail: list[str] = field(default_factory=list)
    error: str = ""

    def log(self, line: str) -> None:
        self.log_tail.append(line[-1000:])
        self.log_tail = self.log_tail[-80:]
        APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (APP_LOG_DIR / f"{self.app_id}.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.action} {line}\n")

    def to_dict(self) -> dict:
        return self.__dict__


jobs: dict[str, AppJob] = {}
jobs_lock = threading.RLock()


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _groups_for(username: str) -> list[str]:
    import grp
    import pwd

    pw = pwd.getpwnam(username)
    return sorted(group.gr_name for group in grp.getgrall() if username in group.gr_mem or group.gr_gid == pw.pw_gid)


def _is_admin(username: str) -> bool:
    try:
        groups = _groups_for(username)
    except KeyError:
        return False
    return "sudo" in groups or "wheel" in groups


def _require_admin(user: SessionUser, password: str) -> None:
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    authenticate(user.username, password)


def _run(args: list[str], *, input_text: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False, shell=False)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip() or result.stdout.strip() or "Command failed")
    return result


def load_manifest(app_id: str) -> dict:
    path = MODULES_DIR / app_id / "manifest.yaml"
    if not path.exists():
        raise HTTPException(404, "App module not found")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def all_manifests() -> list[dict]:
    result = []
    for path in sorted(MODULES_DIR.glob("*/manifest.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifest["id"] = path.parent.name
        result.append(manifest)
    return result


def app_state_path(app_id: str) -> Path:
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return APP_STATE_DIR / f"{app_id}.json"


def read_state(app_id: str) -> dict:
    path = app_state_path(app_id)
    if not path.exists():
        return {"installed": False, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(app_id: str, state: dict) -> None:
    path = app_state_path(app_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def service_status(service: str) -> str:
    if not shutil.which("systemctl"):
        return "unsupported"
    result = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=3, check=False, shell=False)
    return result.stdout.strip() or "unknown"


def plan_install(app_id: str) -> list[str]:
    manifest = load_manifest(app_id)
    if app_id == "samba" and not shutil.which("apt-get"):
        return ["Samba module requires apt-get on Debian/Ubuntu-like systems."]
    steps = [f"Install packages: {', '.join(manifest.get('apt_packages', []))}"]
    steps += [f"Enable/start service: {service}" for service in manifest.get("systemd_services", [])]
    return steps


def assert_app_allowed_on_host(app_id: str) -> None:
    manifest = load_manifest(app_id)
    if safe_mode_active() and not manifest.get("proxmox_safe", False):
        raise HTTPException(403, "Module is blocked by Proxmox Safe Mode")


def enqueue(app_id: str, action: str, worker) -> AppJob:
    job = AppJob(id=uuid4().hex, app_id=app_id, action=action)
    with jobs_lock:
        jobs[job.id] = job

    def run() -> None:
        job.status = "running"
        try:
            worker(job)
            job.progress = 100
            job.status = "completed"
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.log(job.error)
        finally:
            job.finished_at = time.time()
            state = read_state(app_id)
            state.setdefault("history", []).append(job.to_dict())
            state["history"] = state["history"][-100:]
            write_state(app_id, state)

    threading.Thread(target=run, daemon=True).start()
    return job


def install_samba(job: AppJob) -> None:
    assert_app_allowed_on_host("samba")
    if not shutil.which("apt-get"):
        raise HTTPException(400, "Samba module is supported only on apt-based Debian/Ubuntu systems")
    job.log("Installing samba packages without full system upgrade")
    job.progress = 15
    _run(["apt-get", "update"], timeout=900)
    job.progress = 45
    _run(["apt-get", "install", "-y", "samba", "smbclient"], timeout=1800)
    job.progress = 85
    state = read_state("samba")
    state["installed"] = True
    state["configured"] = bool(read_samba_config().shares)
    write_state("samba", state)
    job.log("Samba packages installed")


def run_service(app_id: str, action: str) -> None:
    manifest = load_manifest(app_id)
    for service in manifest.get("systemd_services", []):
        _run(["systemctl", action, service])


def read_samba_config() -> SambaConfig:
    state = read_state("samba")
    return SambaConfig.model_validate(state.get("config") or {})


def backup_smb_conf(now: str | None = None) -> Path | None:
    if not SAMBA_CONF.exists():
        return None
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    backup = SAMBA_CONF.with_name(f"smb.conf.webnas-backup-{stamp}")
    shutil.copy2(SAMBA_CONF, backup)
    return backup


def validate_share_path(username: str, share: SambaShare) -> Path:
    candidate = Path(share.path).resolve(strict=False)
    for blocked in BLOCKED_SHARE_PATHS:
        blocked_path = Path(blocked)
        if candidate == blocked_path or (blocked != "/" and candidate.is_relative_to(blocked_path)):
            raise HTTPException(403, "Share path is protected")
    if safe_mode_active() and share.path.startswith("/var/lib/vz") and not share.allow_proxmox_storage:
        raise HTTPException(403, "Sharing Proxmox storage requires explicit advanced confirmation")
    return resolve_user_path(username, share.path)


def validate_share_model(share: SambaShare) -> None:
    if not SHARE_RE.fullmatch(share.name):
        raise HTTPException(400, "Invalid SMB share name")
    if not SAFE_TEXT_RE.fullmatch(share.comment):
        raise HTTPException(400, "Invalid SMB share comment")
    if not MASK_RE.fullmatch(share.create_mask) or not MASK_RE.fullmatch(share.directory_mask):
        raise HTTPException(400, "Invalid SMB permission mask")
    if share.force_user and not USER_TOKEN_RE.fullmatch(share.force_user):
        raise HTTPException(400, "Invalid SMB force user")
    for username in share.valid_users:
        if not USER_TOKEN_RE.fullmatch(username):
            raise HTTPException(400, "Invalid SMB user name")


def render_smb_conf(config: SambaConfig) -> str:
    lines = [
        "[global]",
        "   server role = standalone server",
        "   map to guest = Bad User",
        "   usershare allow guests = no",
        "",
    ]
    for share in config.shares:
        if not share.enabled:
            continue
        validate_share_model(share)
        lines.extend([
            f"[{share.name}]",
            f"   path = {share.path}",
            f"   comment = {share.comment}",
            f"   browseable = {'yes' if share.browseable else 'no'}",
            f"   read only = {'yes' if share.read_only else 'no'}",
            f"   guest ok = {'yes' if share.guest_ok else 'no'}",
            f"   create mask = {share.create_mask}",
            f"   directory mask = {share.directory_mask}",
        ])
        if share.valid_users:
            lines.append(f"   valid users = {' '.join(share.valid_users)}")
        if share.force_user:
            lines.append(f"   force user = {share.force_user}")
        lines.append("")
    return "\n".join(lines)


def write_samba_config(username: str, config: SambaConfig) -> None:
    for share in config.shares:
        validate_share_model(share)
        resolved = validate_share_path(username, share)
        share.path = str(resolved)
    rendered = render_smb_conf(config)
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = APP_STATE_DIR / "smb.conf.candidate"
    candidate.write_text(rendered, encoding="utf-8")
    if shutil.which("testparm"):
        result = subprocess.run(["testparm", "-s", str(candidate)], capture_output=True, text=True, timeout=15, check=False, shell=False)
        if result.returncode != 0:
            raise HTTPException(400, result.stderr.strip() or result.stdout.strip() or "testparm rejected Samba config")
    backup_smb_conf()
    SAMBA_CONF.write_text(rendered, encoding="utf-8")
    state = read_state("samba")
    state["installed"] = state.get("installed", False)
    state["configured"] = True
    state["config"] = config.model_dump()
    write_state("samba", state)


def app_payload(app_id: str) -> dict:
    manifest = load_manifest(app_id)
    state = read_state(app_id)
    services = {service: service_status(service) for service in manifest.get("systemd_services", [])}
    status = "installed" if state.get("installed") else "not_installed"
    if state.get("installed") and not state.get("configured", True):
        status = "needs_config"
    if services and any(value == "active" for value in services.values()):
        status = "running"
    elif services and state.get("installed"):
        status = "stopped"
    if any(job.app_id == app_id and job.status == "failed" for job in jobs.values()):
        status = "error"
    return {"id": app_id, "manifest": manifest, "state": state, "services": services, "status": status, "jobs": [job.to_dict() for job in jobs.values() if job.app_id == app_id]}


@router.get("")
def list_apps(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return [app_payload(manifest["id"]) for manifest in all_manifests()]


@router.get("/{app_id}")
def get_app(app_id: str, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return app_payload(app_id)


@router.post("/{app_id}/install")
def install_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    assert_app_allowed_on_host(app_id)
    if payload.dry_run:
        return {"dry_run": True, "steps": plan_install(app_id)}
    logger.info("app_store_action actor=%s app=%s action=install", user.username, app_id)
    if app_id != "samba":
        raise HTTPException(404, "Unsupported app module")
    return {"job": enqueue(app_id, "install", install_samba).to_dict()}


@router.post("/{app_id}/uninstall")
def uninstall_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    if payload.dry_run:
        return {"dry_run": True, "steps": ["Stop app services", "Mark module as uninstalled; keep configuration backups"]}
    logger.info("app_store_action actor=%s app=%s action=uninstall", user.username, app_id)

    def worker(job: AppJob) -> None:
        job.progress = 40
        run_service(app_id, "stop")
        state = read_state(app_id)
        state["installed"] = False
        write_state(app_id, state)
        job.progress = 90
        job.log("Module marked as uninstalled; packages/configuration kept")

    return {"job": enqueue(app_id, "uninstall", worker).to_dict()}


@router.post("/{app_id}/update")
def update_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    if payload.dry_run:
        return {"dry_run": True, "steps": plan_install(app_id)}
    logger.info("app_store_action actor=%s app=%s action=update", user.username, app_id)
    if app_id != "samba":
        raise HTTPException(404, "Unsupported app module")
    return {"job": enqueue(app_id, "update", install_samba).to_dict()}


def service_action(app_id: str, action: str, payload: AdminAction, user: SessionUser) -> dict:
    _require_admin(user, payload.admin_password)
    if payload.dry_run:
        return {"dry_run": True, "steps": [f"systemctl {action} service(s) from manifest"]}
    logger.info("app_store_action actor=%s app=%s action=%s", user.username, app_id, action)
    run_service(app_id, action)
    return {"ok": True}


@router.post("/{app_id}/start")
def start_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    return service_action(app_id, "start", payload, user)


@router.post("/{app_id}/stop")
def stop_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    return service_action(app_id, "stop", payload, user)


@router.post("/{app_id}/restart")
def restart_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    return service_action(app_id, "restart", payload, user)


@router.get("/{app_id}/logs")
def app_logs(app_id: str, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    log_file = APP_LOG_DIR / f"{app_id}.log"
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-200:] if log_file.exists() else []
    if app_id == "samba" and shutil.which("journalctl"):
        result = subprocess.run(["journalctl", "-u", "smbd", "-u", "nmbd", "-n", "120", "--no-pager"], capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            lines += result.stdout.splitlines()
    return {"lines": lines[-300:]}


@router.get("/{app_id}/config")
def get_config_app(app_id: str, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    if app_id != "samba":
        return read_state(app_id).get("config") or {}
    return read_samba_config().model_dump()


@router.put("/{app_id}/config")
def put_config_app(app_id: str, payload: SambaConfig, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    if app_id != "samba":
        raise HTTPException(404, "Unsupported app module")
    write_samba_config(user.username, payload)
    logger.info("app_store_config actor=%s app=%s action=update_samba_shares", user.username, app_id)
    return {"ok": True}


@router.post("/samba/smbpasswd")
def set_samba_password(payload: SambaPassword, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    if not shutil.which("smbpasswd"):
        raise HTTPException(503, "smbpasswd is not installed")
    _run(["smbpasswd", "-s", "-a", payload.username], input_text=f"{payload.password}\n{payload.password}\n")
    logger.info("app_store_config actor=%s app=samba action=set_samba_password target=%s", user.username, payload.username)
    return {"ok": True}
