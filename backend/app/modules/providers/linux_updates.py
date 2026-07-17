from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ...config import get_config
from ...package_center.detached_updates import SESSION_ID_RE, read_update_state, update_session_directory, write_update_state
from ...package_center.distro import detect_distribution
from ...package_center.executor import apt_update_without_proxmox_enterprise, proxmox_enterprise_repository_failure, redact
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus
from .base import CancelCallback, LogCallback, ProgressCallback
from .infrastructure import CommandProvider


APT_INST_RE = re.compile(r"^Inst\s+(?P<name>[A-Za-z0-9][A-Za-z0-9+._:-]*)\s+(?:\[(?P<current>[^]]+)\]\s+)?\((?P<version>\S+)(?:\s+(?P<origin>[^)]+))?\)")


class LinuxUpdatesProvider(CommandProvider):
    allowed_tools = {"apt-get", "dnf", "yum"}

    @property
    def update_state_root(self) -> Path:
        return Path(get_config().paths.data_dir)

    @staticmethod
    def _process_alive(pid: Any) -> bool:
        if not isinstance(pid, int) or pid <= 1:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ValueError):
            return False
        return True

    @staticmethod
    def _screen_alive(screen: str, session_name: str) -> bool:
        result = subprocess.run(
            [screen, "-S", session_name, "-Q", "select", "."],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        return result.returncode == 0

    def _launch_screen(self, screen: str, session_name: str, directory: Path, session_id: str, command: list[str]) -> None:
        worker = Path(__file__).resolve().parents[1] / "linux_update_worker.py"
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        result = subprocess.run(
            # Lowercase -d starts screen detached and lets this launcher return
            # immediately. Uppercase -D keeps screen in the foreground and made
            # every package operation hit the ten-second launcher timeout.
            [screen, "-dmS", session_name, sys.executable, str(worker), "--state-dir", str(directory), "--session-id", session_id, "--", *command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
            env=clean_env,
        )
        if result.returncode != 0:
            error = redact(result.stderr.strip() or result.stdout.strip() or "GNU screen could not start the update worker")
            write_update_state(directory, {"session_id": session_id, "status": "failed", "finished_at": time.time(), "exit_code": result.returncode, "error": error})
            raise RuntimeError(error)

    @staticmethod
    def _forward_output(directory: Path, offset: int, log: LogCallback) -> int:
        try:
            with (directory / "output.log").open("rb") as handle:
                handle.seek(offset)
                output = handle.read()
                next_offset = handle.tell()
        except OSError:
            return offset
        for line in output.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                log("stdout", redact(line))
        return next_offset

    def _run_detached_update(self, command: list[str] | None, session_id: str, log: LogCallback, progress: ProgressCallback) -> dict[str, Any]:
        directory = update_session_directory(self.update_state_root, session_id)
        session_name = f"webnas-update-{session_id}"
        state = read_update_state(directory)
        screen_path = shutil.which("screen")
        if not screen_path and (not state or state["status"] not in {"completed", "failed"}):
            raise RuntimeError("GNU screen is required for durable system updates; install the 'screen' package or rerun the WebNAS installer")
        screen = screen_path or ""
        alive = self._screen_alive(screen, session_name) if state and screen else False
        worker_alive = self._process_alive((state or {}).get("pid"))

        if state and state["status"] == "running" and not alive and not worker_alive:
            refreshed = read_update_state(directory)
            if not refreshed or refreshed["status"] == "running":
                raise RuntimeError("Detached system update worker stopped before recording a result")
            state = refreshed
        if not state or (state["status"] == "launching" and not alive and not worker_alive):
            if command is None:
                raise RuntimeError("The detached update stopped before package execution and cannot be resumed safely")
            write_update_state(directory, {"session_id": session_id, "status": "launching", "started_at": time.time()})
            self._launch_screen(screen, session_name, directory, session_id, command)
            state = read_update_state(directory)

        progress(15, f"System update is running in screen session {session_name}")
        output_offset = 0
        started = time.monotonic()
        while True:
            output_offset = self._forward_output(directory, output_offset, log)
            state = read_update_state(directory)
            if state and state["status"] in {"completed", "failed"}:
                output_offset = self._forward_output(directory, output_offset, log)
                if state["status"] == "failed":
                    raise RuntimeError(redact(str(state.get("error") or "Detached system update failed")))
                progress(92, "Detached package operation completed")
                return {
                    "detached": True,
                    "screen_session": session_name,
                    "exit_code": int(state.get("exit_code", 0)),
                }
            if state and state["status"] == "running":
                alive = self._screen_alive(screen, session_name)
                if not alive and not self._process_alive(state.get("pid")):
                    time.sleep(0.2)
                    latest = read_update_state(directory)
                    if not latest or latest["status"] == "running":
                        raise RuntimeError("Detached system update worker stopped before recording a result")
            elapsed_progress = min(90, 15 + int((time.monotonic() - started) / 12))
            progress(elapsed_progress, f"System update continues in screen session {session_name}")
            time.sleep(1)

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
        screen_available = bool(shutil.which("screen"))
        health_message = f"{len(packages)} updates, {security} security updates" if manager else "A supported package manager is unavailable"
        if manager and not screen_available:
            health_message = "GNU screen is unavailable; install it before starting a durable update"
        return ModuleStatus(
            installed=bool(manager), package_version=None, update_available=bool(packages), service_state="available" if manager else "not_installed",
            configuration_valid=True if manager else None, health=ModuleHealth.degraded if security or reboot or (manager and not screen_available) else ModuleHealth.healthy if manager else ModuleHealth.not_installed,
            health_message=health_message,
            metrics={"updates": len(packages), "security_updates": security, "reboot_required": reboot, "package_manager": manager, "screen_available": screen_available},
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
        requested_session = payload.get("screen_session")
        if requested_session is not None and (not isinstance(requested_session, str) or not SESSION_ID_RE.fullmatch(requested_session)):
            raise RuntimeError("Invalid detached update session identifier")
        if operation in {"upgrade_all", "upgrade_security"} and requested_session:
            existing = read_update_state(update_session_directory(self.update_state_root, requested_session))
            if existing:
                progress(10, "Reconnecting to detached system update")
                resumed = self._run_detached_update(None, requested_session, log, progress)
                progress(95, "Checking restart requirement")
                return {"operation": operation, **resumed, "reboot_required": self._reboot_required(), "remaining_updates": len(self._packages())}
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
        detached: dict[str, Any] = {}
        if operation in {"upgrade_all", "upgrade_security"}:
            detached = self._run_detached_update(command, requested_session or secrets.token_hex(12), log, progress)
        else:
            result = self._run(command, timeout=3600, env={"DEBIAN_FRONTEND": "noninteractive"})
            if manager == "apt-get" and operation == "refresh" and result.returncode != 0 and proxmox_enterprise_repository_failure(result.stdout + "\n" + result.stderr):
                with apt_update_without_proxmox_enterprise() as (retry_command, removed):
                    if removed:
                        log("warning", "Proxmox Enterprise repository is unavailable without a subscription; retrying APT metadata refresh with that repository temporarily omitted")
                        result = self._run(retry_command, timeout=3600, env={"DEBIAN_FRONTEND": "noninteractive"})
            for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
                log("stdout" if result.returncode == 0 else "stderr", line)
            self._result(result, "System update failed")
        progress(95, "Checking restart requirement")
        return {"operation": operation, **detached, "reboot_required": self._reboot_required(), "remaining_updates": len(self._packages())}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        return [
            ModuleDiagnostic(status="ok" if status.installed else "critical", title="Package manager", description=str(status.metrics.get("package_manager") or "Unavailable"), severity="ok" if status.installed else "critical"),
            ModuleDiagnostic(status="ok" if status.metrics.get("screen_available") else "critical", title="Detached update worker", description="GNU screen available" if status.metrics.get("screen_available") else "Install the screen package", severity="ok" if status.metrics.get("screen_available") else "critical", recommended_action="Install GNU screen or rerun the WebNAS installer" if not status.metrics.get("screen_available") else ""),
            ModuleDiagnostic(status="warning" if status.metrics.get("security_updates") else "ok", title="Security updates", description=str(status.metrics.get("security_updates", 0)), severity="warning" if status.metrics.get("security_updates") else "ok", recommended_action="Install security updates" if status.metrics.get("security_updates") else ""),
            ModuleDiagnostic(status="warning" if status.metrics.get("reboot_required") else "ok", title="Restart required", description="Yes" if status.metrics.get("reboot_required") else "No", severity="warning" if status.metrics.get("reboot_required") else "ok"),
        ]
