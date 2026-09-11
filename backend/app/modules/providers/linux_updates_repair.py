from __future__ import annotations

import shutil
from typing import Any

from ...package_center.executor import redact
from .base import CancelCallback, LogCallback, ProgressCallback
from .linux_updates import LinuxUpdatesProvider


class LinuxUpdatesRepairProvider(LinuxUpdatesProvider):
    """Extend Linux system updates with recovery for interrupted dpkg runs."""

    allowed_tools = {*LinuxUpdatesProvider.allowed_tools, "dpkg"}

    def manage(
        self,
        operation: str,
        payload: dict[str, Any],
        actor: str,
        log: LogCallback,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> dict[str, Any]:
        if operation != "repair_dpkg":
            return super().manage(operation, payload, actor, log, progress, cancelled)

        if self._manager() != "apt-get":
            raise RuntimeError("DPKG repair is available only on APT-based systems")
        if not shutil.which("dpkg"):
            raise RuntimeError("dpkg executable is unavailable")

        progress(10, "Preparing dpkg repair")
        if cancelled():
            raise InterruptedError("DPKG repair cancelled before execution")

        command = ["dpkg", "--configure", "-a"]
        log("stdout", "Running dpkg --configure -a")
        result = self._run(command, timeout=3600, env={"DEBIAN_FRONTEND": "noninteractive"})

        for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
            if line.strip():
                log("stdout" if result.returncode == 0 else "stderr", redact(line))

        self._result(result, "DPKG repair failed")
        progress(95, "DPKG configuration completed")
        return {
            "operation": operation,
            "command": "dpkg --configure -a",
            "repaired": True,
            "reboot_required": self._reboot_required(),
        }
