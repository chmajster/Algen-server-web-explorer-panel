"""Public operation-planning contract shared by managed modules."""

from typing import Any

from ..package_center.models import PackageAction, PackagePlan, api_error
from ..package_center.service import get_module
from .providers import get_provider


def provider_plan(module_id: str, action: PackageAction, payload: dict[str, Any], *, backup: bool = False) -> PackagePlan:
    module = get_module(module_id)
    manifest = get_provider(module_id).manifest
    if module["blocked_by_proxmox"]:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Module operation is blocked by Proxmox Safe Mode")
    capability = "actions" if action == PackageAction.manage else "diagnostics" if action == PackageAction.diagnostics else "configure" if action == PackageAction.apply else "backups" if action == PackageAction.restore else "reload" if action == PackageAction.reload else "service_control"
    get_provider(module_id).assert_capability(capability)
    return PackagePlan(
        module_id=module_id,
        action=action,
        distribution=module["distribution"],
        compatible=module["compatible"],
        blocked_by_proxmox=module["blocked_by_proxmox"],
        services=manifest.systemd_services,
        config_paths=manifest.config_paths,
        warnings=["A configuration backup will be created before the operation"] if backup else [],
        steps={
            PackageAction.apply: ["Validate configuration", "Create configuration backup", "Write candidate atomically", "Reload service", "Verify service and configuration", "Rollback automatically on failure"],
            PackageAction.restore: ["Verify backup checksum", "Create safety backup", "Restore configuration atomically", "Reload service", "Verify restored state"],
            PackageAction.diagnostics: ["Collect controlled diagnostic checks", "Store report"],
        }.get(action, [f"{action.value.title()} declared module services", "Verify module status"]),
        payload=payload,
        create_backup=backup,
    )
