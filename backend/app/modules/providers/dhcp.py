from __future__ import annotations

from typing import Any

from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, ModuleValidationResult, PackageAction, api_error
from ..dhcp.models import DhcpConfiguration
from ..dhcp.service import DhcpConflictError, DhcpNotFoundError, service
from .base import CancelCallback, LogCallback, ModuleProvider, ProgressCallback


class DhcpProvider(ModuleProvider):
    """Controlled provider for Kea DHCPv4 and ISC dhcpd."""

    def __init__(self, module_id: str = "dhcp") -> None:
        super().__init__(module_id)

    @staticmethod
    def _installed() -> bool:
        from ...package_center.repository import repository

        return "dhcp" in repository().installed()

    def get_status(self) -> ModuleStatus:
        from ...package_center.service import get_module

        module = get_module("dhcp")
        status = service().status(installed=self._installed(), blocked_by_proxmox=bool(module["blocked_by_proxmox"]))
        health = {
            "healthy": ModuleHealth.healthy,
            "degraded": ModuleHealth.degraded,
            "failed": ModuleHealth.failed,
            "not_installed": ModuleHealth.not_installed,
        }.get(status.health, ModuleHealth.unknown)
        return ModuleStatus(
            installed=status.installed,
            package_version=status.version or None,
            service_state=status.service_state,
            service_enabled=status.service_enabled,
            services={status.service: {"state": status.service_state, "enabled": status.service_enabled, "required": True, "uptime_seconds": status.uptime_seconds}} if status.service else {},
            configuration_valid=status.configuration_valid,
            health=health,
            health_message="DHCP service and configuration are healthy" if health == ModuleHealth.healthy else "DHCP Manager requires attention" if health != ModuleHealth.not_installed else "DHCP backend is not installed",
            last_error=status.last_errors[-1] if status.last_errors else "",
            metrics={
                "backend": status.backend.value,
                "interfaces": status.interfaces,
                "active_leases": status.active_leases,
                "available_addresses": status.available_addresses,
                "used_addresses": status.used_addresses,
                "subnet_count": status.subnet_count,
                "reservation_count": status.reservation_count,
                "blocked_by_proxmox": status.blocked_by_proxmox,
            },
        )

    def get_config(self) -> dict[str, Any]:
        self.assert_capability("configure")
        return service().configuration().model_dump(mode="json")

    def validate_config(self, config: dict[str, Any]) -> ModuleValidationResult:
        self.assert_capability("configure")
        try:
            value = DhcpConfiguration.model_validate(config)
            result = service().validate_configuration(value)
        except ValueError as error:
            return ModuleValidationResult(ok=False, errors=[str(error)])
        return ModuleValidationResult(
            ok=result.ok,
            errors=[item.message for item in result.issues if item.level == "error"],
            warnings=[item.message for item in result.issues if item.level == "warning"],
            validator_output=result.native_output,
        )

    def get_log_sources(self) -> list[dict[str, str]]:
        backend = service().backend()
        unit = service().system.selected_service(backend)
        return [{"id": f"journal:{unit}", "label": unit}] if unit else []

    def get_logs(self, source: str, lines: int = 200, search: str = "", level: str = "") -> dict[str, Any]:
        allowed = {item["id"] for item in self.get_log_sources()}
        if source and source not in allowed:
            api_error(400, "INVALID_LOG_SOURCE", "Unsupported DHCP log source")
        return service().logs(limit=lines, search=search, level=level, since="")

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        from ...package_center.service import get_module

        self.assert_capability("diagnostics")
        blocked = bool(get_module("dhcp")["blocked_by_proxmox"])
        values = service().diagnostics(installed=self._installed(), blocked_by_proxmox=blocked)
        return [
            ModuleDiagnostic(
                status="ok" if item.status == "PASS" else "warning" if item.status == "WARNING" else "critical",
                title=item.title,
                description=item.detail or item.code,
                severity="ok" if item.status == "PASS" else "warning" if item.status == "WARNING" else "critical",
                recommended_action=item.recommendation,
            )
            for item in values
        ]

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        config = service().configuration()
        if resource == "subnets":
            items = [item.model_dump(mode="json") for item in config.subnets]
        elif resource == "reservations":
            items = [item.model_dump(mode="json") for item in config.reservations]
        elif resource == "leases":
            items = [item.model_dump(mode="json") for item in service().leases(search=search)]
        elif resource == "interfaces":
            items = [item.model_dump(mode="json") for item in service().interfaces()]
        else:
            return super().list_resources(resource, limit=limit, search=search)
        if search and resource in {"subnets", "reservations", "interfaces"}:
            needle = search.casefold()
            items = [item for item in items if needle in str(item).casefold()]
        return {"resource": resource, "items": items[: min(max(limit, 1), 2000)], "total": len(items)}

    def list_backups(self) -> list[dict[str, Any]]:
        values = []
        for item in service().list_backups():
            values.append({
                **item,
                "module_id": "dhcp",
                "created_at": item.get("timestamp", 0),
                "created_by": item.get("actor", ""),
                "checksum": item.get("sha256", ""),
                "package_version": item.get("version", ""),
                "size": 0,
            })
        return values

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        return service().create_backup(actor, description, automatic)

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation not in self.manifest.capabilities.actions:
            api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported DHCP action")
        reference = str(payload.get("input_ref") or "")
        staged: dict[str, Any] = {}
        if reference:
            staged = service().read_input(reference)
        object_id = str(payload.get("object_id") or "")
        try:
            if cancelled():
                raise InterruptedError("DHCP operation cancelled before execution")
            progress(10, "Validate typed DHCP operation")
            if operation == "config_apply":
                config = DhcpConfiguration.model_validate(staged["configuration"])
                plan = service().plan(config)
                if not plan.validation.ok:
                    raise DhcpConflictError("configuration plan contains validation errors")
                progress(30, "Backup and apply DHCP configuration")
                result = service().apply_configuration(config, actor)
                result["plan"] = plan.model_dump(mode="json")
            elif operation.startswith("subnet_") or operation.startswith("reservation_"):
                progress(30, "Build and validate DHCP configuration candidate")
                result = service().mutate_configuration(operation, object_id, staged, actor)
            elif operation == "lease_to_reservation":
                progress(30, "Convert active lease to reservation")
                result = service().convert_lease(object_id, staged, actor)
            elif operation == "lease_to_host":
                progress(30, "Link DHCP lease with central Hosts Manager")
                result = {"host": service().add_lease_to_hosts(object_id, actor, str(staged.get("ssh_user") or "algen-ansible"))}
            elif operation == "host_to_reservation":
                progress(30, "Create reservation from central Hosts Manager host")
                result = service().reservation_from_host(
                    object_id, str(staged["subnet_id"]), str(staged["mac_address"]), str(staged.get("hostname") or ""),
                    bool(staged.get("create_dns_record")), str(staged.get("dns_provider") or "auto"), actor,
                )
            elif operation == "backup_create":
                result = {"backup": service().create_backup(actor, str(staged.get("description") or ""))}
            elif operation == "backup_restore":
                result = service().restore_backup(object_id, actor)
            elif operation == "backup_delete":
                service().delete_backup(object_id)
                result = {"deleted": object_id}
            elif operation == "service_control":
                result = service().service_control(str(staged.get("action") or ""))
            else:
                api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported DHCP action")
            if cancelled():
                raise InterruptedError("DHCP operation cancelled")
            progress(95, "Verify DHCP operation")
            log("stdout", f"DHCP operation {operation} completed")
            return result
        except (DhcpConflictError, DhcpNotFoundError, ValueError) as error:
            log("stderr", str(error))
            raise
        finally:
            service().discard_input(reference)

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if action in {PackageAction.start, PackageAction.stop, PackageAction.restart, PackageAction.reload, PackageAction.enable, PackageAction.disable}:
            progress(20, f"{action.value.title()} detected DHCP service")
            result = service().service_control(action.value)
            progress(95, "Verify DHCP service state")
            return result
        return super().execute_operation(action, payload, actor, log, progress, cancelled)
