from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from ..path_policy import resolve_user_path
from ..proxmox_guard import safe_mode_active
from . import state
from .models import SambaConfig, SambaShare
from .service import load_manifest, service_status


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
BLOCKED_SHARE_PATHS = ("/", "/etc", "/boot", "/usr", "/var/lib/pve", "/var/lib/pve-cluster", "/etc/pve", "/proc", "/sys", "/dev", "/run")
BLOCKED_SAMBA_OPTIONS = {
    "include", "config file", "private dir", "lock directory", "state directory", "cache directory", "root directory",
    "root preexec", "preexec", "postexec", "wide links", "allow insecure wide links", "follow symlinks", "unix extensions",
}
SAFE_SAMBA_GLOBAL_OPTIONS = {
    "workgroup", "server string", "netbios name", "security", "map to guest", "server min protocol", "server max protocol",
    "interfaces", "bind interfaces only", "log level", "max log size", "deadtime", "load printers", "printing", "disable spoolss",
    "unix extensions", "wide links", "follow symlinks",
}
SAMBA_BOOLEAN_OPTIONS = {"bind interfaces only", "load printers", "disable spoolss", "unix extensions", "wide links", "follow symlinks"}
SAFE_SAMBA_VFS_OBJECTS = {"acl_xattr", "catia", "fruit", "streams_xattr", "recycle"}


def _run(args: list[str], *, input_text: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False, shell=False)
    if result.returncode != 0:
        output = result.stderr.strip() or result.stdout.strip()
        raise HTTPException(400, output or f"{Path(args[0]).name} failed with exit code {result.returncode}")
    return result


def read_samba_config() -> SambaConfig:
    payload = state.read_state("samba")
    return SambaConfig.model_validate(payload.get("config") or {})


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


def _validate_global_options(options: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in options.items():
        option = key.strip().lower()
        text = str(value).strip()
        if option not in SAFE_SAMBA_GLOBAL_OPTIONS:
            raise HTTPException(400, f"Unsupported global Samba option: {option}")
        if not text or len(text) > 300 or any(char in text for char in "\r\n\x00[]"):
            raise HTTPException(400, f"Invalid global Samba value: {option}")
        lowered = text.lower()
        if option in SAMBA_BOOLEAN_OPTIONS and lowered not in {"yes", "no"}:
            raise HTTPException(400, f"Samba option {option} must be yes or no")
        if option == "security" and lowered != "user":
            raise HTTPException(400, "Only Samba security = user is supported")
        if option == "map to guest" and lowered not in {"never", "bad user"}:
            raise HTTPException(400, "Unsupported map to guest mode")
        if option in {"server min protocol", "server max protocol"} and text.upper() not in {"NT1", "SMB2", "SMB3"}:
            raise HTTPException(400, f"Unsupported Samba protocol: {text}")
        if option in {"workgroup", "netbios name"} and not re.fullmatch(r"[A-Za-z0-9_.-]{1,50}", text):
            raise HTTPException(400, f"Invalid Samba name: {option}")
        if option == "log level" and (not text.isdigit() or not 0 <= int(text) <= 10):
            raise HTTPException(400, "Samba log level must be between 0 and 10")
        if option == "max log size" and (not text.isdigit() or not 50 <= int(text) <= 100000):
            raise HTTPException(400, "Samba max log size must be between 50 and 100000 KiB")
        if option == "deadtime" and (not text.isdigit() or not 0 <= int(text) <= 1440):
            raise HTTPException(400, "Samba deadtime must be between 0 and 1440 minutes")
        if option == "printing" and lowered not in {"bsd", "cups"}:
            raise HTTPException(400, "Unsupported Samba printing backend")
        if option == "interfaces" and not re.fullmatch(r"[A-Za-z0-9_.*:/ -]{1,300}", text):
            raise HTTPException(400, "Invalid Samba interface list")
        cleaned[option] = text
    return cleaned


def _ensure_smb_conf_include() -> None:
    include_line = f"include = {SAMBA_ALGEN_CONF}"
    SAMBA_CONF.parent.mkdir(parents=True, exist_ok=True)
    existed = SAMBA_CONF.exists()
    text = SAMBA_CONF.read_text(encoding="utf-8", errors="replace") if existed else "[global]\n   server role = standalone server\n"
    if str(SAMBA_ALGEN_CONF) in text:
        return
    backup_smb_conf()
    if "[global]" not in text.lower():
        text = "[global]\n" + text
    text = text.rstrip() + f"\n\n# Managed by Algen Web Explorer Panel\n{include_line}\n"
    temporary = SAMBA_CONF.with_name(f".{SAMBA_CONF.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, (SAMBA_CONF.stat().st_mode & 0o777) if existed else 0o600)
        os.replace(temporary, SAMBA_CONF)
    finally:
        if temporary.exists():
            temporary.unlink()


def remove_smb_conf_include() -> None:
    if not SAMBA_CONF.exists():
        return
    original = SAMBA_CONF.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in original.splitlines() if str(SAMBA_ALGEN_CONF) not in line and line.strip() != "# Managed by Algen Web Explorer Panel"]
    updated = "\n".join(lines).rstrip() + "\n"
    temporary = SAMBA_CONF.with_name(f".{SAMBA_CONF.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, SAMBA_CONF.stat().st_mode & 0o777)
        os.replace(temporary, SAMBA_CONF)
    finally:
        if temporary.exists():
            temporary.unlink()


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
    if share.force_create_mode and not MASK_RE.fullmatch(share.force_create_mode):
        raise HTTPException(400, "Invalid force create mode")
    if share.force_directory_mode and not MASK_RE.fullmatch(share.force_directory_mode):
        raise HTTPException(400, "Invalid force directory mode")
    if share.force_user and not USER_TOKEN_RE.fullmatch(share.force_user):
        raise HTTPException(400, "Invalid SMB force user")
    if share.force_group and not GROUP_TOKEN_RE.fullmatch(share.force_group):
        raise HTTPException(400, "Invalid SMB force group")
    share.valid_users = _token_list(share.valid_users)
    share.valid_groups = [item.removeprefix("@") for item in _token_list([f"@{value.removeprefix('@')}" for value in share.valid_groups])]
    share.write_list = _token_list(share.write_list)
    share.read_list = _token_list(share.read_list)
    share.admin_users = _token_list(share.admin_users)
    if set(share.read_list) & set(share.write_list):
        raise HTTPException(400, "A user or group cannot be both read-only and write-enabled for the same share")
    if share.guest_ok and (share.valid_users or share.valid_groups):
        raise HTTPException(400, "Guest access conflicts with explicit valid users")
    if share.veto_files and not SAFE_TEXT_RE.fullmatch(share.veto_files):
        raise HTTPException(400, "Invalid veto files pattern")
    if any(value not in SAFE_SAMBA_VFS_OBJECTS for value in share.vfs_objects):
        raise HTTPException(400, "Unsupported Samba VFS object")
    share.vfs_objects = list(dict.fromkeys(share.vfs_objects))
    share.advanced_options = _validate_advanced_options(share.advanced_options)


def validate_samba_config(config: SambaConfig) -> None:
    names: set[str] = set()
    for share in config.shares:
        validate_share_model(share)
        normalized = share.name.lower()
        if normalized in names:
            raise HTTPException(400, f"Duplicate SMB share name: {share.name}")
        names.add(normalized)
    config.global_options = _validate_global_options(config.global_options)


def render_smb_conf(config: SambaConfig) -> str:
    validate_samba_config(config)
    lines = ["# Generated by Algen Web Explorer Panel. Do not edit this file manually.", "# Source of truth: Algen application state.", ""]
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
            f"[{share_name}]", f"   path = {share.path}", f"   comment = {share.comment}",
            f"   browseable = {'yes' if share.browseable else 'no'}", f"   read only = {'yes' if share.read_only else 'no'}",
            f"   guest ok = {'yes' if share.guest_ok else 'no'}", f"   create mask = {share.create_mask}", f"   directory mask = {share.directory_mask}",
        ])
        valid_accounts = [*share.valid_users, *(f"@{group}" for group in share.valid_groups)]
        if valid_accounts:
            lines.append(f"   valid users = {' '.join(valid_accounts)}")
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
        if share.force_create_mode:
            lines.append(f"   force create mode = {share.force_create_mode}")
        if share.force_directory_mode:
            lines.append(f"   force directory mode = {share.force_directory_mode}")
        if share.inherit_permissions:
            lines.append("   inherit permissions = yes")
        if share.veto_files:
            lines.append(f"   veto files = {share.veto_files}")
        vfs_objects = list(dict.fromkeys([*share.vfs_objects, *(["recycle"] if share.recycle_bin else [])]))
        if vfs_objects:
            lines.append(f"   vfs objects = {' '.join(vfs_objects)}")
        if share.recycle_bin:
            lines.extend(["   recycle:repository = .recycle", "   recycle:keeptree = yes", f"   recycle:versions = {'yes' if share.recycle_versions else 'no'}"])
        for key, value in sorted(share.advanced_options.items()):
            lines.append(f"   {key} = {value}")
        lines.append("")
    return "\n".join(lines)


def testparm_config(config_text: str) -> dict:
    state.APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = state.APP_STATE_DIR / "algen-shares.conf.candidate"
    candidate.write_text(config_text, encoding="utf-8")
    executable = shutil.which("testparm")
    if not executable:
        return {"ok": True, "stdout": "testparm is not installed; syntax validation skipped", "stderr": ""}
    result = subprocess.run([executable, "-s", str(candidate)], capture_output=True, text=True, timeout=15, check=False, shell=False)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}


def preview_samba_config(username: str, config: SambaConfig) -> dict:
    for share in config.shares:
        validate_share_model(share)
        share.path = str(validate_share_path(username, share))
    rendered = render_smb_conf(config)
    return {"config": rendered, "validation": testparm_config(rendered)}


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
    payload = state.read_state("samba")
    payload["installed"] = payload.get("installed", False)
    payload["configured"] = True
    payload["config"] = config.model_dump()
    payload["last_validation"] = validation
    payload["last_backup"] = str(backup) if backup else payload.get("last_backup")
    payload.setdefault("changes", []).append({"ts": time.time(), "actor": username, "action": "apply_config"})
    payload["changes"] = payload["changes"][-100:]
    state.write_state("samba", payload)


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
    executable = shutil.which("pdbedit")
    if executable:
        result = subprocess.run([executable, "-L"], capture_output=True, text=True, timeout=10, check=False, shell=False)
        if result.returncode == 0:
            smb_users = {line.split(":", 1)[0] for line in result.stdout.splitlines() if ":" in line}
    return [{"username": item.pw_name, "uid": item.pw_uid, "home": item.pw_dir, "shell": item.pw_shell, "system": item.pw_uid < 1000 and item.pw_name != "root", "samba_enabled": item.pw_name in smb_users} for item in pwd.getpwall()]


def samba_status_payload() -> dict:
    payload = state.read_state("samba")
    config = read_samba_config()
    validation = testparm_config(render_smb_conf(config))
    return {
        "installed": shutil.which("smbd") is not None or bool(payload.get("installed")),
        "managed_config": SAMBA_ALGEN_CONF.exists(),
        "include_configured": SAMBA_CONF.exists() and str(SAMBA_ALGEN_CONF) in SAMBA_CONF.read_text(encoding="utf-8", errors="replace"),
        "external_config": SAMBA_CONF.exists(),
        "services": {service: service_status(service) for service in samba_service_names()},
        "ports": samba_port_status(), "validation": validation, "shares": config.model_dump()["shares"],
        "history": payload.get("changes", [])[-20:], "last_backup": payload.get("last_backup"), "proxmox_safe_mode": safe_mode_active(),
    }


def rollback_samba_config(username: str) -> dict:
    payload = state.read_state("samba")
    backup = Path(payload.get("last_backup") or "")
    if not backup.exists():
        raise HTTPException(404, "No Samba backup is available for rollback")
    validation = testparm_config(backup.read_text(encoding="utf-8", errors="replace"))
    if not validation["ok"]:
        raise HTTPException(400, "Backup config failed Samba validation")
    current_backup = backup_algen_smb_conf()
    shutil.copy2(backup, SAMBA_ALGEN_CONF)
    payload["last_validation"] = validation
    payload["last_backup"] = str(current_backup) if current_backup else payload.get("last_backup")
    payload.setdefault("changes", []).append({"ts": time.time(), "actor": username, "action": "rollback_config"})
    state.write_state("samba", payload)
    return {"ok": True, "validation": validation}
