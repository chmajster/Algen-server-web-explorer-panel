from __future__ import annotations

import grp
import json
import os
import pwd
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import get_config

from . import policy as base
from .protocol import BrokerRequest, BrokerResponse, Operation


MAX_UPDATE_INSTALLER = 2 * 1024 * 1024


def _failure(request: BrokerRequest, error: Exception, *, policy: bool) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=False,
        exit_code=126 if policy else 127,
        error_code="POLICY_DENIED" if policy else "EXECUTION_FAILED",
        stderr=str(error)[:2000],
    )


def _result(request: BrokerRequest, result: base.CommandResult) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        stdout=result.stdout[-base.MAX_OUTPUT:],
        stderr=result.stderr[-base.MAX_OUTPUT:],
        error_code=None if result.exit_code == 0 else "COMMAND_FAILED",
    )


def _update_service(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    extra = set(payload) - {"update_config", "npm_audit_fix"}
    if extra:
        raise base.PolicyError(f"unsupported parameters: {', '.join(sorted(extra))}")
    update_config = payload.get("update_config", False)
    npm_audit_fix = payload.get("npm_audit_fix", False)
    if not isinstance(update_config, bool) or not isinstance(npm_audit_fix, bool):
        raise base.PolicyError("invalid update options")

    config = get_config()
    settings_dir = Path(config.paths.data_dir) / "settings"
    log_dir = Path(config.paths.log_dir)
    settings_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    unit_name = f"webnas-self-update-{int(time.time() * 1000)}.service"
    if not base.UPDATE_UNIT_RE.fullmatch(unit_name):
        raise base.PolicyError("invalid update unit")

    runtime_root = Path("/run/webnas-update") / unit_name.removesuffix(".service")
    runtime_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    installer = runtime_root / "install.sh"
    runner_path = runtime_root / "runner.sh"
    request = urllib.request.Request(
        "https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install/install.sh",
        headers={"User-Agent": "WebNAS-privileged-update/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - fixed HTTPS origin
            content = response.read(MAX_UPDATE_INSTALLER + 1)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError("could not download the trusted WebNAS installer") from error
    if len(content) > MAX_UPDATE_INSTALLER or not content.startswith(b"#!/usr/bin/env bash"):
        raise base.PolicyError("downloaded WebNAS installer is invalid")
    installer.write_bytes(content)
    os.chmod(installer, 0o700)

    progress = settings_dir / "update_progress.json"
    log_path = log_dir / "update.log"
    webnas_user = pwd.getpwnam("webnas")
    try:
        webnas_group = grp.getgrnam("webnas")
    except KeyError as error:
        raise RuntimeError("webnas group is unavailable") from error

    command = [base._resolve_tool("bash"), str(installer), "--existing-action", "update", "--yes"]
    if update_config:
        command.append("--update-config")
    if npm_audit_fix:
        command.append("--npm-audit-fix")
    command_text = " ".join(shlex.quote(item) for item in command)
    runner_text = "\n".join([
        "#!/usr/bin/env bash",
        "set +e",
        f"touch {shlex.quote(str(log_path))}",
        f"chown {webnas_user.pw_uid}:{webnas_group.gr_gid} {shlex.quote(str(log_path))}",
        f"chmod 0640 {shlex.quote(str(log_path))}",
        f"exec >> {shlex.quote(str(log_path))} 2>&1",
        f"printf '\\n=== WebNAS update started (%s) ===\\n' {shlex.quote(unit_name)}",
        f"printf '{{\"running\":true,\"exit_code\":null,\"started_at\":%s,\"finished_at\":null,\"pid\":%s,\"unit\":\"{unit_name}\"}}\\n' \"$(date +%s)\" \"$$\" > {shlex.quote(str(progress))}.tmp",
        f"chown {webnas_user.pw_uid}:{webnas_group.gr_gid} {shlex.quote(str(progress))}.tmp",
        f"chmod 0640 {shlex.quote(str(progress))}.tmp",
        f"mv -f -- {shlex.quote(str(progress))}.tmp {shlex.quote(str(progress))}",
        command_text,
        "rc=$?",
        f"printf '{{\"running\":false,\"exit_code\":%s,\"started_at\":null,\"finished_at\":%s,\"pid\":%s,\"unit\":\"{unit_name}\"}}\\n' \"$rc\" \"$(date +%s)\" \"$$\" > {shlex.quote(str(progress))}.tmp",
        f"chown {webnas_user.pw_uid}:{webnas_group.gr_gid} {shlex.quote(str(progress))}.tmp",
        f"chmod 0640 {shlex.quote(str(progress))}.tmp",
        f"mv -f -- {shlex.quote(str(progress))}.tmp {shlex.quote(str(progress))}",
        "exit \"$rc\"",
        "",
    ])
    runner_path.write_text(runner_text, encoding="utf-8")
    os.chmod(runner_path, 0o700)

    result = runner(
        [
            base._resolve_tool("systemd-run"),
            "--system",
            "--no-ask-password",
            "--unit", unit_name,
            "--collect",
            "--no-block",
            "--property=Type=exec",
            "--property=TimeoutStopSec=infinity",
            "--",
            base._resolve_tool("bash"),
            str(runner_path),
        ],
        None,
        30,
    )
    if result.exit_code:
        return result
    return base.CommandResult(0, json.dumps({"unit": unit_name, "pid": None, "log": str(log_path)}), "")


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    if request.operation != Operation.UPDATE_SERVICE:
        return _failure(request, base.PolicyError("unsupported update policy operation"), policy=True)
    try:
        result = _update_service(request.payload, runner or base._default_runner)
    except base.PolicyError as error:
        return _failure(request, error, policy=True)
    except (OSError, RuntimeError) as error:
        return _failure(request, error, policy=False)
    return _result(request, result)
