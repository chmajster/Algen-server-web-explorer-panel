from __future__ import annotations

import shutil
from typing import Any

from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, api_error
from ...package_center.service import get_module
from ..cron.public import CronJobCreate, CronJobUpdate, CronReadOnlyError, server_timezone, service
from .base import CancelCallback, LogCallback, ModuleProvider, ProgressCallback


class CronProvider(ModuleProvider):
    def __init__(self, module_id: str = "cron") -> None:
        super().__init__(module_id)

    def get_status(self) -> ModuleStatus:
        module = get_module(self.module_id)
        installed = bool(module["state"]["installed"])
        daemon = service().system.daemon()
        state, enabled = service().system.service_state(daemon)
        configuration_valid = service().config_valid()
        dashboard = service().dashboard()
        healthy = bool(daemon and state == "active" and configuration_valid)
        health = ModuleHealth.not_installed if not installed else ModuleHealth.healthy if healthy else ModuleHealth.degraded
        return ModuleStatus(
            installed=installed,
            package_version=module["state"].get("installed_version"),
            available_version=module["state"].get("available_version"),
            update_available=bool(module["state"].get("update_available")),
            service_state=state if installed else "not_installed",
            service_enabled=bool(enabled),
            services={daemon: {"state": state, "enabled": bool(enabled), "required": True}} if daemon else {},
            configuration_valid=configuration_valid,
            health=health,
            health_message="Cron Manager is ready" if healthy else "Cron/crond or the managed configuration requires attention",
            metrics={
                "jobs": dashboard.total,
                "active_jobs": dashboard.active,
                "disabled_jobs": dashboard.inactive,
                "errors": dashboard.errors,
                "daemon": daemon or "",
                "crontab_available": bool(shutil.which("crontab")),
                "timezone": str(server_timezone()),
            },
        )

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        self.assert_capability("diagnostics")
        blocked = bool(get_module(self.module_id)["blocked_by_proxmox"])
        result: list[ModuleDiagnostic] = []
        for item in service().diagnostics(blocked_by_proxmox=blocked):
            severity = "ok" if item.status == "ok" else "warning"
            result.append(ModuleDiagnostic(
                status=severity,
                title=item.title,
                description=item.detail,
                details=item.code,
                severity=severity,
                recommended_action=item.recommendation,
            ))
        return result

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation not in self.manifest.capabilities.actions:
            api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported Cron Manager operation")
        if get_module(self.module_id)["blocked_by_proxmox"]:
            api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Cron mutations are blocked by Proxmox Safe Mode")
        if cancelled():
            raise InterruptedError("Cron operation cancelled")
        progress(10, "Load validated Cron Manager input")
        reference = str(payload.get("input_ref") or "")
        data = service().read_input(reference) if reference else {}
        try:
            if operation == "job_create":
                result = service().create(CronJobCreate.model_validate(data["job"]), actor)
            elif operation == "job_update":
                result = service().update(str(payload.get("job_id") or ""), CronJobUpdate.model_validate(data["job"]), actor)
            elif operation == "job_enable":
                result = service().set_enabled(str(payload.get("job_id") or ""), True, actor)
            elif operation == "job_disable":
                result = service().set_enabled(str(payload.get("job_id") or ""), False, actor)
            elif operation == "job_delete":
                service().delete(str(payload.get("job_id") or ""), actor)
                result = None
            elif operation == "job_duplicate":
                result = service().duplicate(str(payload.get("job_id") or ""), actor, new_id=str(payload.get("new_id") or "") or None)
            else:
                api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported Cron Manager operation")
            if cancelled():
                raise InterruptedError("Cron operation cancelled after safe transaction boundary")
            progress(95, "Verify managed cron configuration")
            if not service().config_valid():
                raise RuntimeError("Cron configuration verification failed")
            log("stdout", f"Cron Manager operation {operation} completed")
            service().discard_input(reference)
            return {"job": result.model_dump(mode="json") if result else None, "configuration_valid": True}
        except (CronReadOnlyError, KeyError) as error:
            raise RuntimeError("Cron job is unavailable or read only") from error
