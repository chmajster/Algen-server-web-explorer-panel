from __future__ import annotations

import json
import os
import re
import shutil
import socket
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
from .config import get_config
from .path_policy import resolve_user_path
from .proxmox_guard import safe_mode_active
from .security import SessionUser, get_session_user, require_csrf

router = APIRouter(prefix="/api/apps")

MODULES_DIR = Path(__file__).resolve().parent / "modules"
APP_STATE_DIR = Path(get_config().paths.data_dir) / "apps"
APP_LOG_DIR = Path("/var/log/webnas/apps")
SAMBA_CONF = Path("/etc/samba/smb.conf")
SAMBA_ALGEN_CONF = Path("/etc/samba/algen-shares.conf")
SHARE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")
SAFE_TEXT_RE = re.compile(r"^[^\r\n\[\]]{0,200}$")
USER_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}\$?$")
GROUP_TOKEN_RE = re.compile(r"^@?[A-Za-z_][A-Za-z0-9_.-]{0,31}\$?$")
MASK_RE = re.compile(r"^0?[0-7]{3,4}$")
ADVANCED_OPTION_RE = re.compile(r"^[A-Za-z0-9 _.-]{2,64}$")
ADVANCED_VALUE_RE = re.compile(r"^[^\r\n\[\]]{0,300}$")
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
GITHUB_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?(?:\.git)?$")
BLOCKED_SHARE_PATHS = (
    "/",
    "/etc",
    "/boot",
    "/usr",
    "/var/lib/pve",
    "/var/lib/pve-cluster",
    "/etc/pve",
    "/proc",
    "/sys",
    "/dev",
    "/run",
)
BLOCKED_SAMBA_OPTIONS = {
    "include",
    "config file",
    "private dir",
    "lock directory",
    "state directory",
    "cache directory",
    "root directory",
    "root preexec",
    "preexec",
    "postexec",
    "wide links",
    "allow insecure wide links",
    "follow symlinks",
    "unix extensions",
}


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
    hidden: bool = False
    read_only: bool = True
    guest_ok: bool = False
    valid_users: list[str] = Field(default_factory=list)
    write_list: list[str] = Field(default_factory=list)
    read_list: list[str] = Field(default_factory=list)
    admin_users: list[str] = Field(default_factory=list)
    force_user: str | None = None
    force_group: str | None = None
    veto_files: str = ""
    recycle_bin: bool = False
    create_directory: bool = False
    directory_owner: str = ""
    directory_group: str = ""
    directory_mode: str = ""
    advanced_options: dict[str, str] = Field(default_factory=dict)
    create_mask: str = "0664"
    directory_mask: str = "0775"
    allow_proxmox_storage: bool = False


class SambaConfig(BaseModel):
    shares: list[SambaShare] = Field(default_factory=list)
    global_options: dict[str, str] = Field(default_factory=dict)


class SambaApplyRequest(BaseModel):
    config: SambaConfig | None = None


class SambaServiceAction(BaseModel):
    action: str
    admin_password: str


class SambaUserAction(AdminAction):
    username: str


class StorePlugin(BaseModel):
    id: str = ""
    name: str
    github_url: str
    branch: str = "main"
    enabled: bool = True
    codex_instructions: str
    created_at: float = 0
    updated_at: float = 0


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
        output = result.stderr.strip() or result.stdout.strip()
        raise HTTPException(400, output or f"{Path(args[0]).name} failed with exit code {result.returncode}")
    return result


def _job_error_message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        if isinstance(error.detail, str):
            return error.detail
        if isinstance(error.detail, dict):
            return str(error.detail.get("message") or error.detail.get("detail") or "Administrative operation failed")
    if isinstance(error, subprocess.TimeoutExpired):
        command = error.cmd[0] if isinstance(error.cmd, list) and error.cmd else "Command"
        return f"{Path(str(command)).name} timed out after {error.timeout} seconds"
    return str(error) or "Administrative operation failed"


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


PLUGIN_CODEX_TEMPLATE = """Codex task: install or update an Algen Web Explorer Panel plugin from GitHub.

Repository:
{github_url}

Branch/ref:
{branch}

Rules:
- Inspect the repository before changing files.
- Read its README and manifest first.
- Do not run destructive commands.
- Verify the plugin fits the current Algen plugin/module conventions.
- Copy or generate only the files required by the plugin.
- Add or update tests when the plugin changes backend or frontend behavior.
- Run the relevant validation commands and report results.
"""


def _plugin_id(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-.") or "plugin"
    base = base[:50]
    candidate = base
    counter = 2
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _validate_plugin(plugin: StorePlugin) -> StorePlugin:
    plugin.name = plugin.name.strip()
    if not plugin.name or not SAFE_TEXT_RE.fullmatch(plugin.name):
        raise HTTPException(400, "Invalid plugin name")
    if not GITHUB_URL_RE.fullmatch(plugin.github_url.strip()):
        raise HTTPException(400, "Plugin URL must be an https://github.com/owner/repo link")
    if plugin.id and not PLUGIN_ID_RE.fullmatch(plugin.id):
        raise HTTPException(400, "Invalid plugin id")
    if not re.fullmatch(r"^[A-Za-z0-9_.\-/]{1,120}$", plugin.branch):
        raise HTTPException(400, "Invalid plugin branch/ref")
    if len(plugin.codex_instructions) > 8000:
        raise HTTPException(400, "Codex instructions are too long")
    plugin.github_url = plugin.github_url.rstrip("/")
    plugin.branch = plugin.branch.strip() or "main"
    plugin.codex_instructions = plugin.codex_instructions.strip() or PLUGIN_CODEX_TEMPLATE.format(github_url=plugin.github_url, branch=plugin.branch)
    return plugin


def read_store_plugins() -> list[StorePlugin]:
    state = read_state("store_plugins")
    return [StorePlugin.model_validate(item) for item in state.get("plugins", [])]


def write_store_plugins(plugins: list[StorePlugin]) -> None:
    write_state("store_plugins", {"plugins": [plugin.model_dump() for plugin in plugins]})


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
            job.error = _job_error_message(exc)
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
    job.log("Refreshing APT package metadata")
    _run(["apt-get", "update"], timeout=900)
    job.progress = 45
    job.log("Installing samba and smbclient packages")
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


def backup_algen_smb_conf(now: str | None = None) -> Path | None:
    if not SAMBA_ALGEN_CONF.exists():
        return None
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    backup = SAMBA_ALGEN_CONF.with_name(f"algen-shares.conf.backup-{stamp}")
    shutil.copy2(SAMBA_ALGEN_CONF, backup)
    return backup


def _token_list(tokens: list[str], *, allow_group: bool = True) -> list[str]:
    result = []
    for token in tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        pattern = GROUP_TOKEN_RE if allow_group else USER_TOKEN_RE
        if not pattern.fullmatch(cleaned):
            raise HTTPException(400, f"Invalid SMB account token: {cleaned}")
        result.append(cleaned)
    return sorted(dict.fromkeys(result))


def _validate_advanced_options(options: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in options.items():
        option = key.strip().lower()
        text = str(value).strip()
        if not option:
            continue
        if option in BLOCKED_SAMBA_OPTIONS:
            raise HTTPException(400, f"Samba option is blocked for safety: {option}")
        if not ADVANCED_OPTION_RE.fullmatch(option) or not ADVANCED_VALUE_RE.fullmatch(text):
            raise HTTPException(400, f"Invalid Samba option: {option}")
        cleaned[option] = text
    return cleaned


def _ensure_smb_conf_include() -> None:
    include_line = f"include = {SAMBA_ALGEN_CONF}"
    SAMBA_CONF.parent.mkdir(parents=True, exist_ok=True)
    if not SAMBA_CONF.exists():
        SAMBA_CONF.write_text("[global]\n   server role = standalone server\n", encoding="utf-8")
    text = SAMBA_CONF.read_text(encoding="utf-8", errors="replace")
    if str(SAMBA_ALGEN_CONF) in text:
        return
    backup_smb_conf()
    if "[global]" not in text.lower():
        text = "[global]\n" + text
    text = text.rstrip() + f"\n\n# Managed by Algen Web Explorer Panel\n{include_line}\n"
    SAMBA_CONF.write_text(text, encoding="utf-8")


def _prepare_share_directory(share: SambaShare, resolved: Path) -> None:
    if share.create_directory:
        resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.exists():
        raise HTTPException(400, "Share path does not exist")
    if not resolved.is_dir():
        raise HTTPException(400, "Share path must be a directory")
    owner = share.directory_owner.strip()
    group = share.directory_group.strip()
    if owner or group:
        uid = -1
        gid = -1
        if owner:
            import pwd

            uid = pwd.getpwnam(owner).pw_uid
        if group:
            import grp

            gid = grp.getgrnam(group).gr_gid
        os.chown(resolved, uid, gid)
    if share.directory_mode:
        if not MASK_RE.fullmatch(share.directory_mode):
            raise HTTPException(400, "Invalid directory permission mode")
        os.chmod(resolved, int(share.directory_mode, 8))


def validate_share_path(username: str, share: SambaShare) -> Path:
    candidate = Path(share.path).resolve(strict=False)
    for blocked in BLOCKED_SHARE_PATHS:
        blocked_path = Path(blocked).resolve(strict=False)
        if candidate == blocked_path or (blocked != "/" and candidate.is_relative_to(blocked_path)):
            raise HTTPException(403, "Share path is protected")
    if safe_mode_active() and (share.path.startswith("/var/lib/vz") or share.path.startswith("/etc/pve")) and not share.allow_proxmox_storage:
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
    if share.force_group and not GROUP_TOKEN_RE.fullmatch(share.force_group):
        raise HTTPException(400, "Invalid SMB force group")
    share.valid_users = _token_list(share.valid_users)
    share.write_list = _token_list(share.write_list)
    share.read_list = _token_list(share.read_list)
    share.admin_users = _token_list(share.admin_users)
    if set(share.read_list) & set(share.write_list):
        raise HTTPException(400, "A user or group cannot be both read-only and write-enabled for the same share")
    if share.guest_ok and share.valid_users:
        raise HTTPException(400, "Guest access conflicts with explicit valid users")
    if share.veto_files and not SAFE_TEXT_RE.fullmatch(share.veto_files):
        raise HTTPException(400, "Invalid veto files pattern")
    share.advanced_options = _validate_advanced_options(share.advanced_options)


def validate_samba_config(config: SambaConfig) -> None:
    names: set[str] = set()
    for share in config.shares:
        validate_share_model(share)
        normalized = share.name.lower()
        if normalized in names:
            raise HTTPException(400, f"Duplicate SMB share name: {share.name}")
        names.add(normalized)
    config.global_options = _validate_advanced_options(config.global_options)


def render_smb_conf(config: SambaConfig) -> str:
    validate_samba_config(config)
    lines = [
        "# Generated by Algen Web Explorer Panel. Do not edit this file manually.",
        "# Source of truth: Algen application state.",
        "",
    ]
    if config.global_options:
        lines.append("[global]")
        for key, value in sorted(config.global_options.items()):
            lines.append(f"   {key} = {value}")
        lines.append("")
    for share in config.shares:
        if not share.enabled:
            continue
        share_name = f"{share.name}$" if share.hidden and not share.name.endswith("$") else share.name
        lines.extend([
            f"[{share_name}]",
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
        if share.read_list:
            lines.append(f"   read list = {' '.join(share.read_list)}")
        if share.write_list:
            lines.append(f"   write list = {' '.join(share.write_list)}")
        if share.admin_users:
            lines.append(f"   admin users = {' '.join(share.admin_users)}")
        if share.force_user:
            lines.append(f"   force user = {share.force_user}")
        if share.force_group:
            lines.append(f"   force group = {share.force_group}")
        if share.veto_files:
            lines.append(f"   veto files = {share.veto_files}")
        if share.recycle_bin:
            lines.extend([
                "   vfs objects = recycle",
                "   recycle:repository = .recycle",
                "   recycle:keeptree = yes",
                "   recycle:versions = yes",
            ])
        for key, value in sorted(share.advanced_options.items()):
            lines.append(f"   {key} = {value}")
        lines.append("")
    return "\n".join(lines)


def testparm_config(config_text: str) -> dict:
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = APP_STATE_DIR / "algen-shares.conf.candidate"
    candidate.write_text(config_text, encoding="utf-8")
    if not shutil.which("testparm"):
        return {"ok": True, "stdout": "testparm is not installed; syntax validation skipped", "stderr": ""}
    result = subprocess.run(["testparm", "-s", str(candidate)], capture_output=True, text=True, timeout=15, check=False, shell=False)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}


def preview_samba_config(username: str, config: SambaConfig) -> dict:
    for share in config.shares:
        validate_share_model(share)
        resolved = validate_share_path(username, share)
        share.path = str(resolved)
    rendered = render_smb_conf(config)
    validation = testparm_config(rendered)
    return {"config": rendered, "validation": validation}


def write_samba_config(username: str, config: SambaConfig) -> None:
    preview = preview_samba_config(username, config)
    validation = preview["validation"]
    if not validation["ok"]:
        raise HTTPException(400, validation["stderr"].strip() or validation["stdout"].strip() or "testparm rejected Samba config")
    for share in config.shares:
        _prepare_share_directory(share, Path(share.path))
    backup = backup_algen_smb_conf()
    _ensure_smb_conf_include()
    SAMBA_ALGEN_CONF.write_text(preview["config"], encoding="utf-8")
    state = read_state("samba")
    state["installed"] = state.get("installed", False)
    state["configured"] = True
    state["config"] = config.model_dump()
    state["last_validation"] = validation
    state["last_backup"] = str(backup) if backup else state.get("last_backup")
    state.setdefault("changes", []).append({"ts": time.time(), "actor": username, "action": "apply_config"})
    state["changes"] = state["changes"][-100:]
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
    app_jobs = [job for job in jobs.values() if job.app_id == app_id]
    if app_jobs and app_jobs[-1].status == "failed":
        status = "error"
    return {"id": app_id, "manifest": manifest, "state": state, "services": services, "status": status, "jobs": [job.to_dict() for job in app_jobs]}


def samba_service_names() -> list[str]:
    return load_manifest("samba").get("systemd_services", ["smbd", "nmbd"])


def samba_port_status() -> dict[str, bool]:
    result: dict[str, bool] = {}
    for port in (445, 139):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            result[str(port)] = sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()
    return result


def samba_users_payload() -> list[dict]:
    import pwd

    smb_users: set[str] = set()
    if shutil.which("pdbedit"):
        result = subprocess.run(["pdbedit", "-L"], capture_output=True, text=True, timeout=10, check=False, shell=False)
        if result.returncode == 0:
            smb_users = {line.split(":", 1)[0] for line in result.stdout.splitlines() if ":" in line}
    users = []
    for item in pwd.getpwall():
        system = item.pw_uid < 1000 and item.pw_name not in {"root"}
        users.append({
            "username": item.pw_name,
            "uid": item.pw_uid,
            "home": item.pw_dir,
            "shell": item.pw_shell,
            "system": system,
            "samba_enabled": item.pw_name in smb_users,
        })
    return users


def samba_status_payload() -> dict:
    state = read_state("samba")
    config = read_samba_config()
    rendered = render_smb_conf(config)
    validation = testparm_config(rendered)
    return {
        "installed": shutil.which("smbd") is not None or bool(state.get("installed")),
        "managed_config": SAMBA_ALGEN_CONF.exists(),
        "include_configured": SAMBA_CONF.exists() and str(SAMBA_ALGEN_CONF) in SAMBA_CONF.read_text(encoding="utf-8", errors="replace"),
        "external_config": SAMBA_CONF.exists(),
        "services": {service: service_status(service) for service in samba_service_names()},
        "ports": samba_port_status(),
        "validation": validation,
        "shares": config.model_dump()["shares"],
        "history": state.get("changes", [])[-20:],
        "last_backup": state.get("last_backup"),
        "proxmox_safe_mode": safe_mode_active(),
    }


def rollback_samba_config(username: str) -> dict:
    state = read_state("samba")
    backup = Path(state.get("last_backup") or "")
    if not backup.exists():
        raise HTTPException(404, "No Samba backup is available for rollback")
    validation = testparm_config(backup.read_text(encoding="utf-8", errors="replace"))
    if not validation["ok"]:
        raise HTTPException(400, "Backup config failed Samba validation")
    current_backup = backup_algen_smb_conf()
    shutil.copy2(backup, SAMBA_ALGEN_CONF)
    state["last_validation"] = validation
    state["last_backup"] = str(current_backup) if current_backup else state.get("last_backup")
    state.setdefault("changes", []).append({"ts": time.time(), "actor": username, "action": "rollback_config"})
    write_state("samba", state)
    logger.info("app_store_config actor=%s app=samba action=rollback", username)
    return {"ok": True, "validation": validation}


def list_apps(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    from .package_center.service import list_modules

    return list_modules()


@router.get("/plugins")
def list_store_plugins(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return {
        "plugins": [plugin.model_dump() for plugin in read_store_plugins()],
        "codex_template": PLUGIN_CODEX_TEMPLATE,
    }


@router.post("/plugins")
def create_store_plugin(payload: StorePlugin, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    plugins = read_store_plugins()
    existing = {plugin.id for plugin in plugins}
    payload.id = payload.id or _plugin_id(payload.name, existing)
    payload.created_at = payload.created_at or time.time()
    payload.updated_at = time.time()
    payload = _validate_plugin(payload)
    if payload.id in existing:
        raise HTTPException(409, "Plugin id already exists")
    plugins.append(payload)
    write_store_plugins(plugins)
    logger.info("app_store_plugin actor=%s action=create id=%s repo=%s", user.username, payload.id, payload.github_url)
    return payload.model_dump()


@router.put("/plugins/{plugin_id}")
def update_store_plugin(plugin_id: str, payload: StorePlugin, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    plugins = read_store_plugins()
    for index, plugin in enumerate(plugins):
        if plugin.id != plugin_id:
            continue
        payload.id = plugin_id
        payload.created_at = plugin.created_at
        payload.updated_at = time.time()
        payload = _validate_plugin(payload)
        plugins[index] = payload
        write_store_plugins(plugins)
        logger.info("app_store_plugin actor=%s action=update id=%s repo=%s", user.username, payload.id, payload.github_url)
        return payload.model_dump()
    raise HTTPException(404, "Plugin entry not found")


@router.delete("/plugins/{plugin_id}")
def delete_store_plugin(plugin_id: str, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    plugins = read_store_plugins()
    next_plugins = [plugin for plugin in plugins if plugin.id != plugin_id]
    if len(next_plugins) == len(plugins):
        raise HTTPException(404, "Plugin entry not found")
    write_store_plugins(next_plugins)
    logger.info("app_store_plugin actor=%s action=delete id=%s", user.username, plugin_id)
    return {"ok": True}


def get_app(app_id: str, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    from .package_center.service import get_module

    return get_module(app_id)


def install_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    from .package_center.jobs import manager as package_manager
    from .package_center.models import PackageAction
    from .package_center.service import plan_operation, repository

    plan = plan_operation(app_id, PackageAction.install)
    if payload.dry_run:
        return {"dry_run": True, "plan": plan.model_dump()}
    logger.info("app_store_action actor=%s app=%s action=install", user.username, app_id)
    return {"job": package_manager(repository()).enqueue(plan, user.username)}


def uninstall_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    from .package_center.jobs import manager as package_manager
    from .package_center.models import PackageAction
    from .package_center.service import plan_operation, repository

    plan = plan_operation(app_id, PackageAction.uninstall)
    if payload.dry_run:
        return {"dry_run": True, "plan": plan.model_dump()}
    logger.info("app_store_action actor=%s app=%s action=uninstall", user.username, app_id)
    return {"job": package_manager(repository()).enqueue(plan, user.username)}


def update_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    from .package_center.jobs import manager as package_manager
    from .package_center.models import PackageAction
    from .package_center.service import plan_operation, repository

    plan = plan_operation(app_id, PackageAction.update)
    if payload.dry_run:
        return {"dry_run": True, "plan": plan.model_dump()}
    logger.info("app_store_action actor=%s app=%s action=update", user.username, app_id)
    return {"job": package_manager(repository()).enqueue(plan, user.username)}


def service_action(app_id: str, action: str, payload: AdminAction, user: SessionUser) -> dict:
    _require_admin(user, payload.admin_password)
    if payload.dry_run:
        return {"dry_run": True, "steps": [f"systemctl {action} service(s) from manifest"]}
    logger.info("app_store_action actor=%s app=%s action=%s", user.username, app_id, action)
    run_service(app_id, action)
    return {"ok": True}


def start_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    return service_action(app_id, "start", payload, user)


def stop_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    return service_action(app_id, "stop", payload, user)


def restart_app(app_id: str, payload: AdminAction, user: SessionUser = Depends(_current_user)):
    return service_action(app_id, "restart", payload, user)


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


@router.get("/samba/status")
def samba_status(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return samba_status_payload()


@router.get("/samba/users")
def samba_users(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return samba_users_payload()


@router.post("/samba/preview")
def samba_preview(payload: SambaApplyRequest, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    config = payload.config or read_samba_config()
    return preview_samba_config(user.username, config)


@router.post("/samba/apply")
def samba_apply(payload: SambaApplyRequest, user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    config = payload.config or read_samba_config()
    write_samba_config(user.username, config)
    logger.info("app_store_config actor=%s app=samba action=apply_config", user.username)
    return {"ok": True, **samba_status_payload()}


@router.post("/samba/rollback")
def samba_rollback(user: SessionUser = Depends(_current_user)):
    if not _is_admin(user.username):
        raise HTTPException(403, "Administrator privileges required")
    return rollback_samba_config(user.username)


@router.post("/samba/service")
def samba_service(payload: SambaServiceAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    if payload.action not in {"start", "stop", "restart", "reload"}:
        raise HTTPException(400, "Unsupported Samba service action")
    logger.info("app_store_action actor=%s app=samba action=%s", user.username, payload.action)
    for service in samba_service_names():
        _run(["systemctl", payload.action, service])
    return {"ok": True, "status": samba_status_payload()}


@router.post("/samba/users/enable")
def samba_user_enable(payload: SambaPassword, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    if not shutil.which("smbpasswd"):
        raise HTTPException(503, "smbpasswd is not installed")
    _run(["smbpasswd", "-s", "-a", payload.username], input_text=f"{payload.password}\n{payload.password}\n")
    _run(["smbpasswd", "-e", payload.username])
    logger.info("app_store_config actor=%s app=samba action=enable_samba_user target=%s", user.username, payload.username)
    return {"ok": True}


@router.post("/samba/users/disable")
def samba_user_disable(payload: SambaUserAction, user: SessionUser = Depends(_current_user)):
    _require_admin(user, payload.admin_password)
    if not shutil.which("smbpasswd"):
        raise HTTPException(503, "smbpasswd is not installed")
    _run(["smbpasswd", "-d", payload.username])
    logger.info("app_store_config actor=%s app=samba action=disable_samba_user target=%s", user.username, payload.username)
    return {"ok": True}


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
