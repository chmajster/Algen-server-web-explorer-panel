from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ...package_center.distro import detect_distribution
from ...package_center.executor import redact
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus
from .base import CancelCallback, LogCallback, ProgressCallback
from .infrastructure import CommandProvider


APT_INST_RE = re.compile(r"^Inst\s+(?P<name>[A-Za-z0-9][A-Za-z0-9+._:-]*)\s+(?:\[(?P<current>[^]]+)\]\s+)?\((?P<version>\S+)(?:\s+(?P<origin>[^)]+))?\)")


class LinuxUpdatesProvider(CommandProvider):
    allowed_tools = {"apt-get", "dnf", "yum"}

    def _manager(self) -> str | None:
        detected = detect_distribution().package_manager
        return detected if detected in self.allowed_tools and shutil.which(detected) else None

    def _packages(self) -> list[dict[str, Any]]:
        manager = self._manager()
        if manager == "apt-get":
            result = self._run(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], timeout=90)
            packages: list[dict[str, Any]] = []
            for line in result.stdout.splitlines():
                match = APT_INST_RE.match(line)
                if not match:
                    continue
                origin = match.group("origin") or ""
                packages.append({"name": match.group("name"), "current_version": match.group("current") or "", "available_version": match.group("version"), "security": "security" in origin.lower(), "origin": origin})
            return packages
        if manager in {"dnf", "yum"}:
            result = self._run([manager, "-q", "check-update"], timeout=90)
            packages = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and "." in parts[0] and not parts[0].startswith(("Last", "Obsoleting")):
                    name, architecture = parts[0].rsplit(".", 1)
                    packages.append({"name": name, "architecture": architecture, "current_version": "", "available_version": parts[1], "security": False, "origin": parts[2]})
            security = self._run([manager, "-q", "updateinfo", "list", "security", "updates"], timeout=90)
            security_names = {part.rsplit(".", 1)[0] for line in security.stdout.splitlines() for part in line.split() if "." in part and not part.startswith("FEDORA-")}
            for package in packages:
                package["security"] = package["name"] in security_names
            return packages
        return []

    @staticmethod
    def _reboot_required() -> bool:
        if Path("/var/run/reboot-required").exists():
            return True
        executable = shutil.which("needs-restarting")
        if not executable:
            return False
        import subprocess

        return subprocess.run([executable, "-r"], capture_output=True, text=True, timeout=20, check=False, shell=False).returncode == 1

    def get_status(self) -> ModuleStatus:
        manager = self._manager()
        packages = self._packages() if manager else []
        security = sum(1 for item in packages if item["security"])
        reboot = self._reboot_required()
        return ModuleStatus(
            installed=bool(manager), package_version=None, update_available=bool(packages), service_state="available" if manager else "not_installed",
            configuration_valid=True if manager else None, health=ModuleHealth.degraded if security or reboot else ModuleHealth.healthy if manager else ModuleHealth.not_installed,
            health_message=f"{len(packages)} updates, {security} security updates" if manager else "A supported package manager is unavailable",
            metrics={"updates": len(packages), "security_updates": security, "reboot_required": reboot, "package_manager": manager},
        )

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        if resource in {"packages", "security"}:
            items = self._packages()
            if resource == "security":
                items = [item for item in items if item["security"]]
            needle = search.lower().strip()
            if needle:
                items = [item for item in items if needle in str(item.get("name", "")).lower()]
            return {"resource": resource, "items": items[:limit], "total": len(items), "reboot_required": self._reboot_required()}
        if resource == "history":
            manager = self._manager()
            lines: list[str] = []
            if manager == "apt-get":
                path = Path("/var/log/apt/history.log")
                if path.is_file():
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
            elif manager in {"dnf", "yum"}:
                lines = self._run([manager, "history", "list", "--reverse"], timeout=30).stdout.splitlines()[-limit:]
            return {"resource": resource, "items": [{"entry": redact(line)} for line in lines], "total": len(lines), "reboot_required": self._reboot_required()}
        if resource == "reboot":
            return {"resource": resource, "items": [{"required": self._reboot_required()}], "total": 1}
        return super().list_resources(resource, limit=limit, search=search)

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        manager = self._manager()
        if not manager:
            raise RuntimeError("A supported package manager is unavailable")
        if operation == "refresh":
            command = ["apt-get", "update"] if manager == "apt-get" else [manager, "makecache"]
        elif operation == "upgrade_all":
            command = ["apt-get", "upgrade", "-y"] if manager == "apt-get" else [manager, "upgrade", "-y"]
        elif operation == "upgrade_security":
            if manager == "apt-get":
                names = [self._checked_identifier(item["name"], "package name") for item in self._packages() if item["security"]]
                if not names:
                    return {"updated": 0, "reboot_required": self._reboot_required()}
                command = ["apt-get", "install", "--only-upgrade", "-y", *names]
            else:
                command = [manager, "upgrade", "--security", "-y"]
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        progress(10, "Preparing package operation")
        if cancelled():
            raise InterruptedError("System update cancelled before execution")
        result = self._run(command, timeout=3600, env={"DEBIAN_FRONTEND": "noninteractive"})
        for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
            log("stdout" if result.returncode == 0 else "stderr", line)
        self._result(result, "System update failed")
        progress(95, "Checking restart requirement")
        return {"operation": operation, "reboot_required": self._reboot_required(), "remaining_updates": len(self._packages())}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        return [
            ModuleDiagnostic(status="ok" if status.installed else "critical", title="Package manager", description=str(status.metrics.get("package_manager") or "Unavailable"), severity="ok" if status.installed else "critical"),
            ModuleDiagnostic(status="warning" if status.metrics.get("security_updates") else "ok", title="Security updates", description=str(status.metrics.get("security_updates", 0)), severity="warning" if status.metrics.get("security_updates") else "ok", recommended_action="Install security updates" if status.metrics.get("security_updates") else ""),
            ModuleDiagnostic(status="warning" if status.metrics.get("reboot_required") else "ok", title="Restart required", description="Yes" if status.metrics.get("reboot_required") else "No", severity="warning" if status.metrics.get("reboot_required") else "ok"),
        ]
