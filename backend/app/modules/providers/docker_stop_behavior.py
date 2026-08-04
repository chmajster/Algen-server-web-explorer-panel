from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, TypeVar

from ...package_center.executor import redact
from ...package_center.models import api_error
from .base import CancelCallback, LogCallback, ProgressCallback


ProviderType = TypeVar("ProviderType")


def graceful_stop_command(executable: str, target: str) -> list[str]:
    """Build a Docker stop command that never escalates to SIGKILL on a timer."""

    return [executable, "stop", "--time", "-1", target]


def _safe_environment() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _log_process_output(result: subprocess.CompletedProcess[str], log: LogCallback) -> None:
    for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
        log("stdout" if result.returncode == 0 else "stderr", redact(line))


def _graceful_stop(
    provider: Any,
    payload: dict[str, Any],
    log: LogCallback,
    progress: ProgressCallback,
    cancelled: CancelCallback,
) -> dict[str, Any]:
    progress(10, "Preparing graceful container stop")
    if cancelled():
        raise InterruptedError("Docker operation cancelled before execution")

    target = provider._checked_identifier(payload.get("target"), "container")
    executable = shutil.which("docker")
    if not executable:
        api_error(409, "DOCKER_UNAVAILABLE", "Docker CLI is unavailable")

    command = graceful_stop_command(executable, target)
    log("command", f"docker stop --time -1 {target}")
    progress(35, "Waiting for the container to shut down gracefully")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        env=_safe_environment(),
        start_new_session=True,
    )

    while process.poll() is None:
        if cancelled():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise InterruptedError("Graceful container stop was cancelled")
        time.sleep(0.25)

    stdout, stderr = process.communicate()
    result = subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)
    _log_process_output(result, log)
    if result.returncode != 0:
        raise RuntimeError(redact(result.stderr.strip() or result.stdout.strip() or "Docker stop failed"))

    progress(85, "Verifying graceful container stop")
    inspection = provider._inspect("container", target)
    state = inspection.get("State") if isinstance(inspection, dict) else {}
    if isinstance(state, dict) and bool(state.get("Running")):
        raise RuntimeError("Container is still running after graceful stop")

    if cancelled():
        raise InterruptedError("Docker operation cancelled after execution")

    progress(95, "Refreshing Docker state")
    return {
        "operation": "container_stop",
        "target": target,
        "graceful": True,
        "forced": False,
        "status": provider.get_status().model_dump(mode="json"),
    }


def install_docker_stop_behavior(provider_class: type[ProviderType]) -> None:
    """Patch the bundled Docker provider once."""

    if getattr(provider_class, "_webnas_stop_behavior_installed", False):
        return

    original_manage = provider_class.manage

    def manage(
        self: Any,
        operation: str,
        payload: dict[str, Any],
        actor: str,
        log: LogCallback,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> dict[str, Any]:
        if operation == "container_stop":
            return _graceful_stop(self, payload, log, progress, cancelled)
        if operation == "container_kill":
            payload = {**payload, "signal": "KILL", "timeout": None}
        return original_manage(self, operation, payload, actor, log, progress, cancelled)

    provider_class.manage = manage
    provider_class._webnas_stop_behavior_installed = True
