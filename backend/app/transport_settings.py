from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from .audit import logger
from .config import get_config
from .privileged_broker.runtime import broker_required, systemd_action
from .rbac import authorize
from .security import SessionUser, get_session_user, require_csrf
from .transport import (
    TransportSettings,
    read_transport_settings,
    render_nginx_transport,
    transport_include_path,
    transport_state_path,
    write_transport_include,
    write_transport_settings,
)


router = APIRouter()


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _active_backend_port() -> int:
    cfg = get_config()
    path = Path(cfg.paths.data_dir) / "settings" / "deployment.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        port = int(payload.get("active_port") or 0) if isinstance(payload, dict) else 0
    except (OSError, ValueError, json.JSONDecodeError):
        port = 0
    if port < 1 or port > 65535:
        raise HTTPException(409, "HTTPS settings require the standard nginx blue/green installation")
    return port


def _nginx_base_config(backend_port: int) -> str:
    cfg = get_config()
    include_path = transport_include_path(cfg)
    return f"""server {{
    include {include_path};
    client_max_body_size 0;
    location / {{
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
}}
"""


def _reload_nginx(actor: str) -> subprocess.CompletedProcess[str]:
    if broker_required():
        return systemd_action("reload", "nginx.service", actor=actor)
    return subprocess.run(
        ["systemctl", "reload", "nginx.service"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _payload(settings: TransportSettings) -> dict[str, object]:
    cfg = get_config()
    return {
        **settings.model_dump(),
        "scheme": "https" if settings.use_https else "http",
        "public_port": cfg.server.port,
    }


@router.get("/api/settings/transport")
def get_transport_settings(user: SessionUser = Depends(_current_user)):
    authorize(user, "system.status")
    return _payload(read_transport_settings())


@router.put("/api/settings/transport")
def save_transport_settings(payload: TransportSettings, request: Request, user: SessionUser = Depends(_current_user)):
    authorize(user, "system.restart")
    cfg = get_config()
    backend_port = _active_backend_port()
    state_path = transport_state_path(cfg)
    include_path = transport_include_path(cfg)
    previous_state = state_path.read_bytes() if state_path.exists() else None
    previous_include = include_path.read_bytes() if include_path.exists() else None

    try:
        # Validate before replacing any durable files.
        render_nginx_transport(payload, cfg.server.port)
        write_transport_settings(payload, cfg)
        write_transport_include(payload, cfg.server.port, cfg)
        result = _reload_nginx(f"transport-{user.username}")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "nginx reload failed")
    except Exception as error:
        if previous_state is None:
            state_path.unlink(missing_ok=True)
        else:
            state_path.write_bytes(previous_state)
        if previous_include is None:
            include_path.unlink(missing_ok=True)
        else:
            include_path.write_bytes(previous_include)
        try:
            _reload_nginx(f"transport-rollback-{user.username}")
        except Exception:
            pass
        raise HTTPException(400, f"Could not apply transport settings: {error}") from error

    logger.info(
        "transport_settings_updated actor=%s https=%s cert=%s",
        user.username,
        payload.use_https,
        payload.tls_cert,
    )
    return _payload(payload)
