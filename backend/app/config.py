from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    # The NAS panel intentionally listens on the configured LAN interfaces;
    # production exposure is controlled by firewall/TLS configuration.
    host: str = "0.0.0.0"  # nosec B104
    port: int = 5000
    use_https: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None


class AuthConfig(BaseModel):
    provider: Literal["pam"] = "pam"
    pam_service: str = "webnas"
    session_cookie_name: str = Field(default="webnas_session", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    session_lifetime_hours: int = Field(default=12, ge=1, le=168)
    remember_me_lifetime_days: int = Field(default=30, ge=1, le=365)


class PathsConfig(BaseModel):
    default_root: Literal["home", "allowed"] = "home"
    allowed_roots: list[str] = Field(default_factory=list)
    data_dir: str = "/var/lib/webnas"
    log_dir: str = "/var/log/webnas"
    temp_dir: str = "/var/lib/webnas/tmp"


class SecurityConfig(BaseModel):
    max_upload_size_mb: int = 2048
    rate_limit_login_per_minute: int = 5
    rate_limit_admin_per_minute: int = 20
    allow_chmod: bool = True
    allow_chown: bool = False
    system_uid_threshold: int = 1000
    session_secret: str = "change-this-secret"
    cookie_secure: bool = False


class FileTasksConfig(BaseModel):
    max_parallel: int = 2
    max_parallel_per_user: int = 1
    log_tail_lines: int = 80
    enable_sse: bool = True
    rsync_path: str | None = None
    rsync_extra_args: list[str] = Field(default_factory=list)


class ProxmoxConfig(BaseModel):
    detect: bool = True
    safe_mode: bool = True
    block_system_user_management: bool = True
    block_system_group_management: bool = True
    block_chown: bool = True
    block_chmod_on_protected_paths: bool = True
    block_delete_on_protected_paths: bool = True
    block_move_on_protected_paths: bool = True
    block_rsync_on_protected_paths: bool = True
    block_service_management: bool = True
    allow_only_home_roots_on_proxmox: bool = True
    require_explicit_install_confirmation: bool = True
    install_abort_on_proxmox_without_flag: bool = True
    protected_paths: list[str] = Field(default_factory=lambda: [
        "/etc/pve",
        "/var/lib/pve-cluster",
        "/var/lib/vz",
        "/var/lib/lxc",
        "/etc/network",
        "/etc/network/interfaces",
        "/etc/hosts",
        "/etc/hostname",
        "/etc/resolv.conf",
        "/etc/apt",
        "/etc/systemd",
        "/etc/default",
        "/etc/modprobe.d",
        "/etc/modules-load.d",
        "/boot",
        "/root",
        "/usr/share/perl5/PVE",
        "/var/log/pve",
        "/run/pve",
        "/run/lock",
        "/dev",
        "/proc",
        "/sys",
        "/run",
        "/mnt/pve",
        "/rpool",
    ])


class SystemdConfig(BaseModel):
    allowed_services: list[str] = Field(default_factory=lambda: [
        "webnas.service",
        "webnas-backend-blue.service",
        "webnas-backend-green.service",
        "smbd.service",
        "nmbd.service",
        "nginx.service",
        "caddy.service",
        "docker.service",
    ])


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    file_tasks: FileTasksConfig = Field(default_factory=FileTasksConfig)
    proxmox: ProxmoxConfig = Field(default_factory=ProxmoxConfig)
    systemd: SystemdConfig = Field(default_factory=SystemdConfig)
    systemd_allowed_services: list[str] = Field(default_factory=list)


DEFAULT_CONFIG_PATHS = (
    Path("/etc/webnas/config.yaml"),
    Path(__file__).resolve().parents[2] / "config.example.yaml",
)


def load_config(path: str | None = None) -> AppConfig:
    env_path = os.environ.get("WEBNAS_CONFIG")
    selected_path = path or env_path
    candidates = [Path(selected_path)] if selected_path is not None else list(DEFAULT_CONFIG_PATHS)
    for candidate in candidates:
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as handle:
                return AppConfig.model_validate(yaml.safe_load(handle) or {})
    return AppConfig()


@lru_cache
def get_config() -> AppConfig:
    return load_config()
