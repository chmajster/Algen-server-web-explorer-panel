from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .audit import logger
from .config import get_config
from .privileged_broker.runtime import broker_command, broker_required
from .rbac import authorize
from .security import SessionUser, get_session_user, require_csrf

router = APIRouter(tags=["power-control"])


class PowerAction(BaseModel):
    confirm: bool = True


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _require_restart_permission(user: SessionUser, request: Request, action: str) -> None:
    authorize(user, "system.restart")
    logger.info(
        "power_action_authorized actor=%s action=%s client=%s",
        user.username,
        action,
        request.client.host if request.client else "unknown",
    )


def _application_service() -> str:
    """Return the service that currently serves the active WebNAS backend."""
    environment_slot = os.environ.get("WEBNAS_SLOT", "").strip().lower()
    if environment_slot in {"blue", "green"}:
        return f"webnas-backend-{environment_slot}.service"

    deployment_path = Path(get_config().paths.data_dir) / "settings" / "deployment.json"
    try:
        deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        deployment = {}

    active_slot = str(deployment.get("active_slot") or "").strip().lower() if isinstance(deployment, dict) else ""
    if active_slot in {"blue", "green"}:
        return f"webnas-backend-{active_slot}.service"
    return "webnas.service"


def _command_error(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or result.stdout or "System command failed").strip()
    return message[:1000]


def _run_broker_systemctl(action: str, arguments: tuple[str, ...]) -> None:
    """Execute the delayed action after the HTTP response through the root broker.

    The normal WebNAS backend intentionally runs as the unprivileged ``webnas``
    account.  A short in-process delay lets the API return first; once the helper
    sends its typed request, the dedicated broker owns the privileged systemctl
    process and can complete it even when restarting WebNAS kills this backend
    cgroup.
    """
    try:
        result = broker_command(
            ["systemctl", *arguments],
            timeout=120,
            actor=f"power-control-{action}",
        )
        if result is None:
            logger.error("power_action_broker_rejected action=%s arguments=%s", action, arguments)
            return
        if result.returncode != 0:
            logger.error(
                "power_action_broker_failed action=%s returncode=%s error=%s",
                action,
                result.returncode,
                _command_error(result),
            )
    except Exception:  # noqa: BLE001 - background task must never escape the scheduling thread.
        logger.exception("power_action_broker_failed action=%s", action)


def _schedule_systemctl(action: str, *arguments: str) -> dict[str, str | bool]:
    """Schedule a systemd action outside the current HTTP request lifecycle.

    Standard installations run the backend as the unprivileged ``webnas`` user,
    so creating a system transient timer directly would trigger polkit and fail
    with "interactive authentication has not been enabled".  In that deployment
    mode the delayed helper submits the already-allowlisted systemctl operation
    to WebNAS' dedicated root privileged broker instead.

    Root/portable installations keep the existing systemd-run path.
    """
    if broker_required():
        timer = threading.Timer(2.0, _run_broker_systemctl, args=(action, tuple(arguments)))
        timer.daemon = True
        timer.start()
        return {"ok": True, "scheduled": True, "mode": "privileged-broker-delay", "unit": ""}

    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise HTTPException(503, "systemctl is unavailable")

    systemd_run = shutil.which("systemd-run")
    unit = f"webnas-{action}-{time.time_ns()}"
    if systemd_run:
        command = [
            systemd_run,
            "--quiet",
            f"--unit={unit}",
            "--on-active=2s",
            systemctl,
            *arguments,
        ]
        mode = "transient-timer"
    else:
        command = [systemctl, "--no-block", *arguments]
        mode = "no-block"

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env={**os.environ, "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.exception("power_action_schedule_failed action=%s", action)
        raise HTTPException(500, f"Could not schedule {action}: {error}") from error

    if result.returncode != 0:
        message = _command_error(result)
        logger.error(
            "power_action_schedule_failed action=%s returncode=%s error=%s",
            action,
            result.returncode,
            message,
        )
        raise HTTPException(500, message)

    return {"ok": True, "scheduled": True, "mode": mode, "unit": unit if systemd_run else ""}


@router.post("/api/admin/host/restart")
def restart_host(
    payload: PowerAction,
    request: Request,
    user: SessionUser = Depends(_current_user),
):
    _require_restart_permission(user, request, "restart_host")
    if not payload.confirm:
        raise HTTPException(400, "Restart confirmation is required")
    response = _schedule_systemctl("host-restart", "reboot")
    logger.info("power_action_scheduled actor=%s action=restart_host", user.username)
    return {**response, "target": "host"}


@router.post("/api/admin/application/restart")
def restart_application(
    payload: PowerAction,
    request: Request,
    user: SessionUser = Depends(_current_user),
):
    _require_restart_permission(user, request, "restart_application")
    if not payload.confirm:
        raise HTTPException(400, "Restart confirmation is required")
    service = _application_service()
    response = _schedule_systemctl("application-restart", "restart", service)
    logger.info(
        "power_action_scheduled actor=%s action=restart_application service=%s",
        user.username,
        service,
    )
    return {**response, "target": "application", "service": service}
