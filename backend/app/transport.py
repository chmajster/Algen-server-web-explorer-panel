from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, field_validator

from .config import AppConfig, get_config


TLS_PATH_RE = re.compile(r"^/[A-Za-z0-9._@:+/-]{1,4095}$")


class TransportSettings(BaseModel):
    use_https: bool = False
    tls_cert: str = ""
    tls_key: str = ""

    @field_validator("tls_cert", "tls_key")
    @classmethod
    def valid_tls_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not TLS_PATH_RE.fullmatch(value) or ".." in Path(value).parts:
            raise ValueError("TLS path must be an absolute path without whitespace or traversal")
        return value


def transport_state_path(cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    return Path(selected.paths.data_dir) / "settings" / "transport.json"


def transport_include_path(cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    return Path(selected.paths.data_dir) / "settings" / "nginx-transport.conf"


def default_transport(cfg: AppConfig | None = None) -> TransportSettings:
    selected = cfg or get_config()
    return TransportSettings(
        use_https=bool(selected.server.use_https),
        tls_cert=str(selected.server.tls_cert or ""),
        tls_key=str(selected.server.tls_key or ""),
    )


def read_transport_settings(cfg: AppConfig | None = None) -> TransportSettings:
    selected = cfg or get_config()
    defaults = default_transport(selected)
    path = transport_state_path(selected)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    try:
        return TransportSettings.model_validate({**defaults.model_dump(), **payload})
    except ValueError:
        return defaults


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def write_transport_settings(settings: TransportSettings, cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    path = transport_state_path(selected)
    _atomic_write(path, settings.model_dump_json(indent=2) + "\n", 0o600)
    return path


def render_nginx_transport(settings: TransportSettings, public_port: int) -> str:
    if public_port < 1 or public_port > 65535:
        raise ValueError("invalid public port")
    lines = [f"listen {public_port}{' ssl' if settings.use_https else ''};"]
    if settings.use_https:
        if not settings.tls_cert or not settings.tls_key:
            raise ValueError("TLS certificate and key paths are required when HTTPS is enabled")
        lines.extend(
            [
                f"ssl_certificate {settings.tls_cert};",
                f"ssl_certificate_key {settings.tls_key};",
            ]
        )
    return "\n".join(lines) + "\n"


def write_transport_include(settings: TransportSettings, public_port: int, cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    path = transport_include_path(selected)
    _atomic_write(path, render_nginx_transport(settings, public_port), 0o640)
    return path


def cookie_secure(cfg: AppConfig | None = None) -> bool:
    selected = cfg or get_config()
    state_path = transport_state_path(selected)
    if state_path.exists():
        return read_transport_settings(selected).use_https
    return bool(selected.security.cookie_secure or selected.server.use_https)
