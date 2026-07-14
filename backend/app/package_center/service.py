from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from ..config import get_config
from ..proxmox_guard import safe_mode_active
from .distro import compatible, detect_distribution, packages_for
from .executor import command_preview
from .manifests import discover_manifests, load_manifest
from .models import ModuleManifest, PackageAction, PackagePlan, api_error
from .repository import PackageRepository

_repository: PackageRepository | None = None
_repository_lock = threading.Lock()


def repository() -> PackageRepository:
    global _repository
    with _repository_lock:
        expected = Path(get_config().paths.data_dir) / "package-center.sqlite3"
        if _repository is None or _repository.path != expected:
            _repository = PackageRepository(expected)
            try:
                from ..apps import read_store_plugins

                _repository.import_legacy_sources([item.model_dump(mode="json") for item in read_store_plugins()])
            except Exception:
                pass
        return _repository


def _migrate_samba_state(repo: PackageRepository) -> None:
    if "samba" in repo.installed():
        return
    try:
        from ..apps import read_state

        state = read_state("samba")
        if state.get("installed") or shutil.which("smbd"):
            repo.mark_installed("samba", str(state.get("version") or "1.0.0"), "migration", False)
    except Exception:
        pass


def service_status(service: str) -> str:
    if not shutil.which("systemctl"):
        return "unsupported"
    result = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=5, check=False, shell=False)
    return result.stdout.strip() or "inactive"


def module_payload(manifest: ModuleManifest, installed: dict[str, dict], jobs: list[dict] | None = None) -> dict:
    distro = detect_distribution()
    record = installed.get(manifest.id)
    module_jobs = jobs if jobs is not None else repository().list_jobs(module_id=manifest.id, limit=20)
    latest = module_jobs[0] if module_jobs else None
    is_compatible = compatible(manifest, distro)
    blocked = safe_mode_active() and not manifest.proxmox_safe
    services = {name: service_status(name) for name in manifest.systemd_services}
    installed_version = record["version"] if record else None
    update_available = bool(installed_version and installed_version != manifest.version)
    if blocked:
        status = "blocked"
    elif not is_compatible:
        status = "incompatible"
    elif latest and latest["status"] in {"queued", "running"}:
        status = "installing"
    elif latest and latest["status"] == "failed":
        status = "error"
    elif record and record.get("requires_reboot"):
        status = "reboot_required"
    elif update_available:
        status = "update_available"
    elif record and any(value == "active" for value in services.values()):
        status = "running"
    elif record and services:
        status = "stopped"
    elif record:
        status = "installed"
    else:
        status = "available"
    return {
        "id": manifest.id,
        "manifest": manifest.model_dump(mode="json"),
        "state": {"installed": bool(record), "installed_version": installed_version, "available_version": manifest.version, "update_available": update_available, "requires_reboot": bool(record and record.get("requires_reboot"))},
        "services": services,
        "status": status,
        "compatible": is_compatible,
        "blocked_by_proxmox": blocked,
        "distribution": distro.model_dump(),
        "jobs": module_jobs,
    }


def list_modules(
    *, search: str = "", category: str = "", status: str = "", compatible_only: bool = False, installed_only: bool = False, updates_only: bool = False
) -> list[dict]:
    repo = repository()
    _migrate_samba_state(repo)
    installed = repo.installed()
    needle = search.strip().lower()
    result = []
    for manifest in discover_manifests():
        payload = module_payload(manifest, installed)
        if needle and needle not in f"{manifest.name} {manifest.description} {manifest.long_description}".lower():
            continue
        if category and manifest.category != category:
            continue
        if status and payload["status"] != status:
            continue
        if compatible_only and not payload["compatible"]:
            continue
        if installed_only and not payload["state"]["installed"]:
            continue
        if updates_only and not payload["state"]["update_available"]:
            continue
        result.append(payload)
    return result


def get_module(module_id: str) -> dict:
    manifest = load_manifest(module_id)
    repo = repository()
    _migrate_samba_state(repo)
    return module_payload(manifest, repo.installed())


def plan_operation(module_id: str, action: PackageAction, *, remove_data: bool = False) -> PackagePlan:
    manifest = load_manifest(module_id)
    repo = repository()
    installed = repo.installed()
    distro = detect_distribution()
    is_compatible = compatible(manifest, distro)
    blocked = safe_mode_active() and not manifest.proxmox_safe
    if blocked:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Module is blocked by Proxmox Safe Mode")
    if action in {PackageAction.install, PackageAction.update, PackageAction.uninstall} and not is_compatible:
        code = "PACKAGE_MANAGER_UNAVAILABLE" if distro.package_manager is None else "MODULE_INCOMPATIBLE"
        api_error(409, code, "Module is not compatible with this system")
    if action == PackageAction.uninstall and not manifest.removable:
        api_error(409, "MODULE_NOT_REMOVABLE", "Module cannot be removed")
    record = installed.get(module_id)
    packages = packages_for(manifest, distro)
    conflicts = [item for item in manifest.conflicts if item in installed]
    warnings: list[str] = []
    if conflicts:
        warnings.append(f"Installed module conflicts: {', '.join(conflicts)}")
    if remove_data:
        warnings.append("Module data directories will be permanently removed")
    if manifest.requires_reboot:
        warnings.append("A system restart is required after this operation")
    if action == PackageAction.uninstall:
        warnings.append("Configuration and user data are preserved by default")
    steps: list[str] = []
    plan = PackagePlan(
        module_id=module_id,
        action=action,
        distribution=distro,
        compatible=is_compatible,
        blocked_by_proxmox=blocked,
        packages=packages,
        services=manifest.systemd_services,
        ports=manifest.ports,
        config_paths=manifest.config_paths,
        data_paths=manifest.data_paths,
        permissions=manifest.permissions,
        dependencies=manifest.dependencies,
        conflicts=conflicts,
        warnings=warnings,
        requires_reboot=manifest.requires_reboot,
        remove_data=remove_data,
        previous_version=record["version"] if record else None,
        target_version=None if action == PackageAction.uninstall else manifest.version,
        steps=steps,
    )
    plan.steps = [" ".join(command) for command in command_preview(plan, manifest)]
    return plan


def categories() -> list[str]:
    return sorted({manifest.category for manifest in discover_manifests()})
