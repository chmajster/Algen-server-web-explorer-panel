from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

from ...package_center.executor import redact
from ...package_center.manifests import load_manifest
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleManifest, ModuleStatus, ModuleValidationResult, PackageAction, api_error

LogCallback = Callable[[str, str], None]
ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class ModuleProvider:
    """Controlled module adapter. Frontend input never becomes a command or path."""

    service_actions = {"start", "stop", "restart", "reload", "enable", "disable"}

    def __init__(self, module_id: str) -> None:
        self.module_id = module_id
        self.manifest: ModuleManifest = load_manifest(module_id)

    def assert_capability(self, capability: str) -> None:
        if not hasattr(self.manifest.capabilities, capability) or not bool(getattr(self.manifest.capabilities, capability)):
            api_error(409, "CAPABILITY_NOT_SUPPORTED", f"Module does not support {capability}")

    @staticmethod
    def _systemctl(service: str, action: str) -> subprocess.CompletedProcess[str]:
        if action not in ModuleProvider.service_actions | {"is-active", "is-enabled"}:
            api_error(400, "INVALID_SERVICE_ACTION", "Unsupported service action")
        executable = shutil.which("systemctl")
        if not executable:
            return subprocess.CompletedProcess(["systemctl", action, service], 127, "", "systemctl unavailable")
        return subprocess.run([executable, action, service], capture_output=True, text=True, timeout=30, check=False, shell=False)

    @staticmethod
    def _service_uptime(service: str) -> tuple[int | None, float | None]:
        executable = shutil.which("systemctl")
        if not executable:
            return None, None
        result = subprocess.run([executable, "show", service, "--property=ActiveEnterTimestampMonotonic", "--value"], capture_output=True, text=True, timeout=8, check=False, shell=False)
        value = result.stdout.strip()
        if result.returncode != 0 or not value.isdigit() or int(value) <= 0:
            return None, None
        uptime = max(0, int(time.monotonic() - int(value) / 1_000_000))
        return uptime, time.time() - uptime

    def get_status(self) -> ModuleStatus:
        from ...package_center.service import get_module

        payload = get_module(self.module_id)
        jobs = payload.get("jobs") or []
        latest = jobs[0] if jobs else {}
        service_details: dict[str, dict[str, Any]] = {}
        for definition in self.manifest.services:
            state = payload.get("services", {}).get(definition.name, "unknown")
            enabled_result = self._systemctl(definition.name, "is-enabled") if shutil.which("systemctl") else None
            uptime, active_since = self._service_uptime(definition.name) if state == "active" else (None, None)
            service_details[definition.name] = {
                "state": state,
                "enabled": bool(enabled_result and enabled_result.returncode == 0),
                "required": definition.required,
                "uptime_seconds": uptime,
                "active_since": active_since,
            }
        installed = bool(payload["state"]["installed"])
        active = any(item["state"] == "active" for item in service_details.values())
        required_failed = any(item["required"] and item["state"] != "active" for item in service_details.values())
        health = ModuleHealth.not_installed if not installed else ModuleHealth.degraded if required_failed else ModuleHealth.healthy if active or not service_details else ModuleHealth.unknown
        return ModuleStatus(
            installed=installed,
            package_version=payload["state"].get("installed_version"),
            available_version=payload["state"].get("available_version"),
            update_available=bool(payload["state"].get("update_available")),
            service_state="active" if active else "inactive" if installed else "not_installed",
            service_enabled=any(bool(item["enabled"]) for item in service_details.values()),
            services=service_details,
            configuration_valid=None,
            health=health,
            health_message="Module is operating normally" if health == ModuleHealth.healthy else "One or more required services are inactive" if health == ModuleHealth.degraded else "Module is not installed" if not installed else "Module status is unknown",
            last_action=str(latest.get("action") or ""),
            last_action_status=str(latest.get("status") or ""),
            last_action_time=latest.get("finished_at") or latest.get("created_at"),
            last_error=str(latest.get("error") or ""),
        )

    def get_config(self) -> dict[str, Any]:
        self.assert_capability("configure")
        api_error(409, "CONFIG_NOT_IMPLEMENTED", "This module has no WebNAS configuration adapter")

    def validate_config(self, config: dict[str, Any]) -> ModuleValidationResult:
        self.assert_capability("configure")
        return ModuleValidationResult(ok=False, errors=["This module has no WebNAS configuration adapter"])

    def get_log_sources(self) -> list[dict[str, str]]:
        self.assert_capability("logs")
        return [{"id": f"journal:{item.name}", "label": item.name} for item in self.manifest.services]

    def get_logs(self, source: str, lines: int = 200, search: str = "", level: str = "") -> dict[str, Any]:
        self.assert_capability("logs")
        allowed = {item["id"]: item["label"] for item in self.get_log_sources()}
        if source not in allowed:
            api_error(400, "INVALID_LOG_SOURCE", "Unsupported module log source")
        executable = shutil.which("journalctl")
        output: list[str] = []
        if executable:
            service = allowed[source]
            result = subprocess.run([executable, "-u", service, "-n", str(min(max(lines, 1), 1000)), "--no-pager"], capture_output=True, text=True, timeout=15, check=False, shell=False)
            output = result.stdout.splitlines() if result.returncode == 0 else [result.stderr]
        needle = search.strip().lower()
        level_needle = level.strip().lower()
        cleaned = [redact(item) for item in output]
        if needle:
            cleaned = [item for item in cleaned if needle in item.lower()]
        if level_needle:
            cleaned = [item for item in cleaned if level_needle in item.lower()]
        selected: list[str] = []
        size = 0
        for item in reversed(cleaned[-1000:]):
            encoded = len(item.encode("utf-8", errors="replace")) + 1
            if size + encoded > 512 * 1024:
                break
            selected.append(item)
            size += encoded
        selected.reverse()
        return {"source": source, "lines": selected, "truncated": len(selected) < len(cleaned)}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        self.assert_capability("diagnostics")
        status = self.get_status()
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "warning", title="Module status", description=status.health_message, details=status.service_state, severity="ok" if status.health == ModuleHealth.healthy else "warning", recommended_action="Review inactive services" if status.health != ModuleHealth.healthy else "")]

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        if resource not in self.manifest.capabilities.resources:
            api_error(404, "MODULE_RESOURCE_NOT_FOUND", "Unsupported module resource")
        api_error(409, "RESOURCE_NOT_IMPLEMENTED", "This module has no resource adapter")

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation not in self.manifest.capabilities.actions:
            api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported module action")
        api_error(409, "ACTION_NOT_IMPLEMENTED", "This module has no management adapter")

    def list_backups(self) -> list[dict[str, Any]]:
        self.assert_capability("backups")
        return []

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        self.assert_capability("backups")
        api_error(409, "BACKUPS_NOT_IMPLEMENTED", "This module has no backup adapter")

    def delete_backup(self, backup_id: str) -> None:
        self.assert_capability("backups")
        api_error(409, "BACKUPS_NOT_IMPLEMENTED", "This module has no backup adapter")

    def cleanup_after_uninstall(self, actor: str, remove_config: bool) -> dict[str, Any]:
        return {"managed_config_removed": False}

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if action in {PackageAction.start, PackageAction.stop, PackageAction.restart, PackageAction.reload, PackageAction.enable, PackageAction.disable}:
            self.assert_capability("reload" if action == PackageAction.reload else "service_control")
            for index, definition in enumerate(self.manifest.services):
                if cancelled():
                    raise InterruptedError("Module operation cancelled")
                progress(10 + int(index / max(1, len(self.manifest.services)) * 70), f"{action.value.title()} {definition.name}")
                result = self._systemctl(definition.name, action.value)
                log("stdout" if result.returncode == 0 else "stderr", result.stdout.strip() or result.stderr.strip() or f"{action.value} {definition.name}")
                if result.returncode != 0 and definition.required:
                    raise RuntimeError(f"Could not {action.value} required service {definition.name}")
            progress(90, "Verify module state")
            status = self.get_status()
            if action in {PackageAction.start, PackageAction.restart, PackageAction.reload} and any(item["required"] and item["state"] != "active" for item in status.services.values()):
                raise RuntimeError("Required module service is not active after the operation")
            if action == PackageAction.stop and any(item["required"] and item["state"] == "active" for item in status.services.values()):
                raise RuntimeError("Required module service is still active after stop")
            if action == PackageAction.enable and any(item["required"] and not item["enabled"] for item in status.services.values()):
                raise RuntimeError("Required module service is not enabled after the operation")
            return {"status": status.model_dump(mode="json")}
        if action == PackageAction.diagnostics:
            progress(20, "Collect module diagnostics")
            report = [item.model_dump(mode="json") for item in self.run_diagnostics()]
            progress(95, "Diagnostics completed")
            return {"diagnostics": report}
        if action == PackageAction.manage:
            operation = str(payload.get("operation") or "")
            if operation not in self.manifest.capabilities.actions:
                api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported module action")
            return self.manage(operation, payload, actor, log, progress, cancelled)
        api_error(409, "OPERATION_NOT_SUPPORTED", "Provider operation is not supported")
