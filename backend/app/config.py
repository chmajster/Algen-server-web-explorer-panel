from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5000
    use_https: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None


class AuthConfig(BaseModel):
    provider: Literal["pam"] = "pam"
    session_cookie_name: str = "webnas_session"


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
    log_tail_lines: int = 80
    enable_sse: bool = True
    rsync_path: str | None = None
    rsync_extra_args: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    file_tasks: FileTasksConfig = Field(default_factory=FileTasksConfig)


DEFAULT_CONFIG_PATHS = (
    Path("/etc/webnas/config.yaml"),
    Path(__file__).resolve().parents[2] / "config.example.yaml",
)


def load_config(path: str | None = None) -> AppConfig:
    env_path = os.environ.get("WEBNAS_CONFIG")
    candidates = [Path(path or env_path)] if path or env_path else list(DEFAULT_CONFIG_PATHS)
    for candidate in candidates:
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as handle:
                return AppConfig.model_validate(yaml.safe_load(handle) or {})
    return AppConfig()


@lru_cache
def get_config() -> AppConfig:
    return load_config()
