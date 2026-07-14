from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from .auth import user_home
from .config import AppConfig, get_config

BLOCKED_MESSAGE = "Operation blocked by Proxmox Safe Mode"

SYSTEM_ROOTS = (
    "/",
    "/etc",
    "/var",
    "/var/lib",
    "/mnt",
    "/mnt/pve",
    "/root",
    "/boot",
    "/dev",
    "/proc",
    "/sys",
    "/run",
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
)

PROTECTED_GROUPS = {
    "root",
    "sudo",
    "wheel",
    "shadow",
    "www-data",
    "backup",
    "storage",
    "pve",
    "pveadmin",
    "pveproxy",
    "pve-cluster",
}

PROXMOX_SERVICES = {
    "pve-cluster",
    "pvedaemon",
    "pveproxy",
    "pvestatd",
    "corosync",
    "qemu-server",
    "lxc",
    "networking",
    "systemd-networkd",
    "ssh",
    "sshd",
    "cron",
    "systemd-journald",
}

UNSAFE_RSYNC_FLAGS = {
    "--delete",
    "--remove-source-files",
    "--rsync-path",
    "--rsh",
    "-e",
}


@dataclass(frozen=True)
class ProxmoxStatus:
    is_proxmox: bool
    reasons: list[str]


def _real(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def detect_proxmox() -> ProxmoxStatus:
    reasons: list[str] = []
    try:
        if Path("/etc/pve").exists():
            reasons.append("/etc/pve exists")
    except OSError:
        pass
    if shutil.which("pveversion"):
        reasons.append("pveversion command exists")
    for service in ("pvedaemon", "pveproxy", "pvestatd", "pve-cluster"):
        result = None
        try:
            result = subprocess.run(["systemctl", "list-unit-files", f"{service}.service"], capture_output=True, text=True, timeout=2, check=False)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0 and service in result.stdout:
            reasons.append(f"{service}.service exists")
    return ProxmoxStatus(is_proxmox=bool(reasons), reasons=reasons)


def safe_mode_active(cfg: AppConfig | None = None) -> bool:
    cfg = cfg or get_config()
    if not cfg.proxmox.safe_mode:
        return False
    if not cfg.proxmox.detect:
        return True
    return detect_proxmox().is_proxmox


def protected_paths(cfg: AppConfig | None = None) -> list[Path]:
    cfg = cfg or get_config()
    return [_real(path) for path in cfg.proxmox.protected_paths]


def _is_same_or_child(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return path == root


def path_is_protected(path: str | Path, cfg: AppConfig | None = None, *, include_parent: bool = False) -> bool:
    cfg = cfg or get_config()
    if not safe_mode_active(cfg):
        return False
    try:
        candidate = _real(path)
    except OSError:
        candidate = Path(path).expanduser().absolute()
    candidates = [candidate]
    if include_parent:
        candidates.append(candidate.parent)
    configured = protected_paths(cfg)
    system_roots = [_real(path) for path in SYSTEM_ROOTS]
    for item in candidates:
        for protected in configured:
            if _is_same_or_child(item, protected):
                return True
        for root in system_roots:
            if root == Path("/"):
                if item == root:
                    return True
            elif _is_same_or_child(item, root):
                return True
    return False


def assert_path_allowed(path: str | Path, operation: str, cfg: AppConfig | None = None, *, include_parent: bool = False) -> None:
    if path_is_protected(path, cfg, include_parent=include_parent):
        raise HTTPException(403, BLOCKED_MESSAGE)


def validate_allowed_roots(username: str, roots: list[Path], cfg: AppConfig | None = None) -> list[Path]:
    cfg = cfg or get_config()
    if not safe_mode_active(cfg) or not cfg.proxmox.allow_only_home_roots_on_proxmox:
        return roots
    home = _real(user_home(username))
    app_share = _real(f"/srv/webnas-shares/{username}")
    blocked_roots = [_real(path) for path in SYSTEM_ROOTS]
    for root in roots:
        real_root = _real(root)
        for blocked in blocked_roots:
            if blocked == Path("/"):
                blocked_match = real_root == blocked
            else:
                blocked_match = _is_same_or_child(real_root, blocked)
            if blocked_match:
                raise HTTPException(403, BLOCKED_MESSAGE)
        if not (_is_same_or_child(real_root, home) or _is_same_or_child(real_root, app_share)):
            raise HTTPException(403, BLOCKED_MESSAGE)
    return roots


def assert_admin_user_allowed(username: str, uid: int | None, action: str) -> None:
    cfg = get_config()
    if not safe_mode_active(cfg):
        return
    if username == "root" or (uid is not None and uid < cfg.security.system_uid_threshold):
        raise HTTPException(403, BLOCKED_MESSAGE)
    if cfg.proxmox.block_system_user_management and action in {"create", "update", "delete", "lock", "unlock"}:
        raise HTTPException(403, BLOCKED_MESSAGE)


def assert_admin_group_allowed(groupname: str, action: str) -> None:
    cfg = get_config()
    if not safe_mode_active(cfg):
        return
    if cfg.proxmox.block_system_group_management or groupname in PROTECTED_GROUPS or groupname.startswith("pve"):
        raise HTTPException(403, BLOCKED_MESSAGE)


def assert_chown_allowed(path: str | Path) -> None:
    cfg = get_config()
    if cfg.proxmox.block_chown:
        assert_path_allowed(path, "chown", cfg, include_parent=True)


def assert_service_allowed(service: str) -> None:
    cfg = get_config()
    normalized = service.removesuffix(".service")
    if safe_mode_active(cfg) and cfg.proxmox.block_service_management and normalized != "webnas":
        raise HTTPException(403, BLOCKED_MESSAGE)
    if normalized in PROXMOX_SERVICES:
        raise HTTPException(403, BLOCKED_MESSAGE)


def validate_rsync_args(extra_args: list[str]) -> list[str]:
    cfg = get_config()
    if not safe_mode_active(cfg):
        return extra_args
    for index, arg in enumerate(extra_args):
        if arg in UNSAFE_RSYNC_FLAGS or arg.startswith("--filter") or arg.startswith("--include-from") or arg.startswith("--exclude-from"):
            raise HTTPException(403, BLOCKED_MESSAGE)
        if index and extra_args[index - 1] in {"--include-from", "--exclude-from"}:
            assert_path_allowed(arg, "rsync-filter-file", cfg, include_parent=True)
    return extra_args


def diagnostic(username: str) -> dict:
    cfg = get_config()
    status = detect_proxmox() if cfg.proxmox.detect else ProxmoxStatus(is_proxmox=False, reasons=["detection disabled"])
    active = safe_mode_active(cfg)
    allowed = []
    try:
        from .path_policy import allowed_roots

        allowed = [str(path) for path in allowed_roots(username)]
    except Exception as exc:
        allowed = [f"unavailable: {exc}"]
    return {
        "is_proxmox": status.is_proxmox,
        "safe_mode_enabled": active,
        "protected_paths": cfg.proxmox.protected_paths,
        "blocked_admin_features": [
            "system user management",
            "system group management",
            "protected path chmod/chown/delete/move/rsync",
            "service management outside webnas.service",
        ] if active else [],
        "allowed_roots_effective": allowed,
        "service_user": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
        "warnings": status.reasons + (["Install WebNAS in a VM or LXC when possible; direct Proxmox host installation is restricted."] if active else []),
    }
