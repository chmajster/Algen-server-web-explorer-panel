from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import re
import secrets
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..activity import ActivityCategory, record_activity
from ..audit import logger
from ..package_center.jobs import manager
from ..package_center.models import ModuleStatus, PackageAction, PackagePlan, api_error
from ..rbac import authorize, current_user as current_admin, module_permission, mutating_user as mutating_admin
from ..package_center.service import get_module, list_modules, plan_operation, repository
from ..security import SessionUser
from .providers import get_provider
from .providers.docker import DockerProvider
from .providers.infrastructure import ApiConnectionProvider
from .providers.samba import SambaProvider, parse_smb_conf

router = APIRouter(prefix="/api/modules", tags=["modules"])
_status_cache: dict[str, tuple[float, ModuleStatus]] = {}
_status_lock = threading.RLock()


def _provider_status(module_id: str, actor: str, ttl: float = 5.0) -> ModuleStatus:
    now = time.monotonic()
    with _status_lock:
        cached = _status_cache.get(module_id)
        if cached and now - cached[0] < ttl:
            return cached[1]
    status = get_provider(module_id, actor).get_status()
    with _status_lock:
        _status_cache[module_id] = (now, status)
    return status


def _invalidate_status(module_id: str) -> None:
    with _status_lock:
        _status_cache.pop(module_id, None)


class ModuleAdminRequest(BaseModel):
    confirm: bool = True
    create_backup: bool = True
    remove_data: bool = False
    remove_config: bool = False
    confirm_name: str = ""


class ModuleApplyRequest(ModuleAdminRequest):
    config: dict[str, Any]
    confirm_smb1: bool = False


class ModuleValidateRequest(BaseModel):
    config: dict[str, Any]


class BackupCreateRequest(ModuleAdminRequest):
    description: str = Field(default="", max_length=200)


class SambaUserRequest(ModuleAdminRequest):
    password: str = Field(default="", max_length=1024)


class SambaImportRequest(BaseModel):
    content: str = Field(max_length=1_000_000)


class ModuleActionRequest(ModuleAdminRequest):
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def bounded_non_secret_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 512 * 1024:
            raise ValueError("module action payload exceeds 512 KiB")

        def inspect(item: Any) -> None:
            if isinstance(item, dict):
                for key, nested in item.items():
                    if any(marker in str(key).lower() for marker in ("password", "secret", "token", "credential")):
                        raise ValueError("secrets are not allowed in durable module action payloads")
                    inspect(nested)
            elif isinstance(item, list):
                for nested in item:
                    inspect(nested)

        inspect(value)
        return value


class ModuleConnectionRequest(ModuleAdminRequest):
    base_url: str = Field(max_length=300)
    username: str = Field(default="", max_length=128)
    secret: str | None = Field(default=None, max_length=2048)


class ComposeSaveRequest(ModuleAdminRequest):
    content: str = Field(max_length=512 * 1024)


def _authorize(user: SessionUser, module_id: str, operation: Literal["view", "operate", "configure", "install", "reinstall", "update", "uninstall", "backup", "restore", "backup_delete", "logs", "diagnostics"]) -> None:
    authorize(user, module_permission(module_id, operation))


def _assert_proxmox_allowed(module_id: str) -> None:
    if get_module(module_id)["blocked_by_proxmox"]:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Module operation is blocked by Proxmox Safe Mode")


def _module_summary(module: dict, actor: str) -> dict:
    provider = get_provider(module["id"], actor)
    status = _provider_status(module["id"], actor)
    state = dict(module.get("state") or {})
    if status.installed:
        state["installed"] = True
        state["installed_version"] = status.package_version or state.get("installed_version") or provider.manifest.version
        if provider.manifest.capabilities.update:
            state["update_available"] = status.update_available
    active = next((job for job in module.get("jobs", []) if job["status"] in {"queued", "running"}), None)
    return {**module, "state": state, "module_status": status.model_dump(mode="json"), "capabilities": provider.manifest.capabilities.model_dump(), "active_job": active}


@router.get("")
def modules(user: SessionUser = Depends(current_admin)):
    return [_module_summary(item, user.username) for item in list_modules() if _can_view(user, item["id"])]


def _can_view(user: SessionUser, module_id: str) -> bool:
    try:
        _authorize(user, module_id, "view")
        return True
    except Exception:
        return False


@router.get("/{module_id}")
def module_detail(module_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    return _module_summary(get_module(module_id), user.username)


@router.get("/{module_id}/status")
def module_status(module_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    return _provider_status(module_id, user.username)


@router.get("/{module_id}/resources/{resource}")
def module_resource(module_id: str, resource: str, limit: int = Query(200, ge=1, le=1000), search: str = "", user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", resource):
        api_error(400, "INVALID_RESOURCE", "Invalid module resource")
    return get_provider(module_id, user.username).list_resources(resource, limit=limit, search=search[:200])


@router.get("/{module_id}/connection")
def module_connection(module_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    provider = get_provider(module_id, user.username)
    if not isinstance(provider, ApiConnectionProvider):
        api_error(404, "MODULE_CONNECTION_NOT_SUPPORTED", "Module has no API connection settings")
    return provider.public_connection()


@router.put("/{module_id}/connection")
def save_module_connection(module_id: str, payload: ModuleConnectionRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "configure")
    _assert_proxmox_allowed(module_id)
    provider = get_provider(module_id, user.username)
    if not isinstance(provider, ApiConnectionProvider):
        api_error(404, "MODULE_CONNECTION_NOT_SUPPORTED", "Module has no API connection settings")
    result = provider.save_connection(payload.base_url, payload.username, payload.secret)
    _invalidate_status(module_id)
    logger.info("module_connection actor=%s module=%s action=save", user.username, module_id)
    record_activity(ActivityCategory.module, "connection_update", user.username, target=module_id, source="modules")
    return result


@router.put("/docker/compose/{project}")
def save_docker_compose(project: str, payload: ComposeSaveRequest, user: SessionUser = Depends(mutating_admin)):
    api_error(409, "TYPED_DOCKER_API_REQUIRED", "Docker Compose changes are available only through the typed Containers Manager API")


@router.get("/docker/compose/{project}")
def get_docker_compose(project: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, "docker", "configure")
    return DockerProvider(user.username).get_compose(project)


@router.get("/{module_id}/config")
def module_config(module_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    return get_provider(module_id, user.username).get_config()


@router.post("/{module_id}/validate")
def module_validate(module_id: str, payload: ModuleValidateRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "configure")
    return get_provider(module_id, user.username).validate_config(payload.config)


def _provider_plan(module_id: str, action: PackageAction, payload: dict[str, Any], *, backup: bool = False) -> PackagePlan:
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


def _enqueue(plan: PackagePlan, payload: ModuleAdminRequest, user: SessionUser) -> dict:
    if not payload.confirm:
        api_error(400, "PLAN_CONFIRMATION_REQUIRED", "The operation plan must be confirmed")
    _invalidate_status(plan.module_id)
    job = manager(repository()).enqueue(plan, user.username)
    logger.info("module_action actor=%s module=%s action=%s job=%s", user.username, plan.module_id, plan.action.value, job["id"])
    return {"job": job}


@router.post("/{module_id}/apply")
def module_apply(module_id: str, payload: ModuleApplyRequest, user: SessionUser = Depends(mutating_admin)):
    if module_id == "docker":
        api_error(409, "TYPED_DOCKER_API_REQUIRED", "Docker daemon changes require the typed Containers Manager API and PAM confirmation")
    _authorize(user, module_id, "configure")
    validation = get_provider(module_id, user.username).validate_config(payload.config)
    if not validation.ok:
        api_error(422, "CONFIG_VALIDATION_FAILED", "Module configuration is invalid", validation=validation.model_dump(mode="json"))
    if "smb1" in validation.confirmations_required and not payload.confirm_smb1:
        api_error(400, "SECURITY_CONFIRMATION_REQUIRED", "Enabling SMB1 requires explicit confirmation", confirmation="smb1")
    return _enqueue(_provider_plan(module_id, PackageAction.apply, {"config": payload.config}, backup=True), payload, user)


@router.get("/{module_id}/logs")
def module_logs(module_id: str, source: str = "", lines: int = Query(200, ge=1, le=1000), search: str = "", level: str = "", user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "logs")
    provider = get_provider(module_id, user.username)
    sources = provider.get_log_sources()
    selected = source or (sources[0]["id"] if sources else "")
    return {"sources": sources, **provider.get_logs(selected, lines, search, level)}


@router.get("/{module_id}/diagnostics")
def module_diagnostics(module_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    jobs = repository().list_jobs(module_id=module_id, limit=100)
    latest = next((job for job in jobs if job["action"] == "diagnostics" and job["status"] == "completed"), None)
    return {"diagnostics": (latest or {}).get("result", {}).get("diagnostics", []), "job": latest}


@router.post("/{module_id}/diagnostics")
def run_module_diagnostics(module_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "diagnostics")
    return _enqueue(_provider_plan(module_id, PackageAction.diagnostics, {}), payload, user)


@router.get("/{module_id}/backups")
def module_backups(module_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    return get_provider(module_id, user.username).list_backups()


@router.post("/{module_id}/backups")
def create_module_backup(module_id: str, payload: BackupCreateRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "backup")
    _assert_proxmox_allowed(module_id)
    backup = get_provider(module_id, user.username).create_backup(user.username, payload.description)
    logger.info("module_backup actor=%s module=%s action=create backup=%s", user.username, module_id, backup["id"])
    record_activity(ActivityCategory.module, "backup_create", user.username, target=module_id, details={"backup_id": backup["id"]}, source="modules")
    return backup


@router.post("/{module_id}/backups/{backup_id}/restore")
def restore_module_backup(module_id: str, backup_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    if module_id == "docker":
        api_error(409, "TYPED_DOCKER_API_REQUIRED", "Docker restores require the typed Containers Manager API and PAM confirmation")
    _authorize(user, module_id, "restore")
    return _enqueue(_provider_plan(module_id, PackageAction.restore, {"backup_id": backup_id}, backup=True), payload, user)


@router.delete("/{module_id}/backups/{backup_id}")
def delete_module_backup(module_id: str, backup_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    if module_id == "docker":
        api_error(409, "TYPED_DOCKER_API_REQUIRED", "Docker backup changes require the typed Containers Manager API")
    _authorize(user, module_id, "backup_delete")
    _assert_proxmox_allowed(module_id)
    get_provider(module_id, user.username).delete_backup(backup_id)
    logger.info("module_backup actor=%s module=%s action=delete backup=%s", user.username, module_id, backup_id)
    record_activity(ActivityCategory.module, "backup_delete", user.username, target=module_id, details={"backup_id": backup_id}, source="modules")
    return {"ok": True}


@router.post("/{module_id}/service/{action}")
def module_service_action(module_id: str, action: Literal["start", "stop", "restart", "reload", "enable", "disable"], payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    if module_id == "docker":
        api_error(409, "TYPED_DOCKER_API_REQUIRED", "Docker service changes require the typed Containers Manager API and PAM confirmation")
    _authorize(user, module_id, "operate")
    return _enqueue(_provider_plan(module_id, PackageAction(action), {}), payload, user)


@router.post("/{module_id}/actions/{operation}")
def module_management_action(module_id: str, operation: str, payload: ModuleActionRequest, user: SessionUser = Depends(mutating_admin)):
    if module_id == "docker":
        api_error(409, "TYPED_DOCKER_API_REQUIRED", "This Docker operation is available only through the typed Containers Manager API")
    _authorize(user, module_id, "operate")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", operation):
        api_error(400, "INVALID_MODULE_ACTION", "Invalid module action")
    provider = get_provider(module_id, user.username)
    if operation not in provider.manifest.capabilities.actions:
        api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported module action")
    # Route-controlled fields are assigned last so a client cannot override the
    # validated operation or choose the name of a privileged screen session.
    action_payload = {**payload.payload, "operation": operation}
    if module_id == "linux-updates" and operation in {"upgrade_all", "upgrade_security"}:
        action_payload["screen_session"] = secrets.token_hex(12)
    return _enqueue(_provider_plan(module_id, PackageAction.manage, action_payload), payload, user)


def _package_action(module_id: str, action: PackageAction, payload: ModuleAdminRequest, user: SessionUser) -> dict:
    if module_id == "docker" and action in {PackageAction.install, PackageAction.reinstall, PackageAction.update, PackageAction.uninstall}:
        api_error(409, "TYPED_DOCKER_API_REQUIRED", "Docker Engine package changes require the typed Containers Manager API and PAM confirmation")
    provider = get_provider(module_id, user.username)
    provider.assert_capability("update" if action == PackageAction.reinstall else action.value)
    if action == PackageAction.uninstall and payload.remove_data and module_id == "samba" and payload.confirm_name != "Samba":
        api_error(400, "MODULE_NAME_CONFIRMATION_REQUIRED", "Type Samba to confirm removal of module data")
    if action == PackageAction.uninstall and payload.remove_data and module_id == "ansible-controller" and payload.confirm_name != "Ansible":
        api_error(400, "MODULE_NAME_CONFIRMATION_REQUIRED", "Type Ansible to confirm removal of all local controller data")
    plan = plan_operation(module_id, action, remove_data=payload.remove_data)
    if module_id == "ansible-controller" and action == PackageAction.uninstall:
        managed = [host for host in getattr(provider, "store").list_hosts() if host.get("managed_user_created")]
        plan.warnings.append("Remote algen-ansible accounts are never removed automatically")
        if managed:
            names = ", ".join(f"{host['name']} ({host['address']})" for host in managed[:20])
            plan.warnings.append(f"Remote hosts with a module-created managed account ({len(managed)}): {names}")
    plan.payload["remove_config"] = payload.remove_config
    plan.create_backup = payload.create_backup and action in {PackageAction.reinstall, PackageAction.update, PackageAction.uninstall} and provider.manifest.capabilities.backups
    if payload.remove_config:
        plan.warnings.append("WebNAS-managed module configuration will be removed")
    return _enqueue(plan, payload, user)


@router.post("/{module_id}/install")
def module_install(module_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "install")
    return _package_action(module_id, PackageAction.install, payload, user)


@router.post("/{module_id}/update")
def module_update(module_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "update")
    return _package_action(module_id, PackageAction.update, payload, user)


@router.post("/{module_id}/reinstall")
def module_reinstall(module_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "reinstall")
    return _package_action(module_id, PackageAction.reinstall, payload, user)


@router.post("/{module_id}/uninstall")
def module_uninstall(module_id: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, module_id, "uninstall")
    return _package_action(module_id, PackageAction.uninstall, payload, user)


@router.get("/{module_id}/jobs/{job_id}/events")
async def module_job_events(module_id: str, job_id: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, module_id, "view")
    async def events():
        previous = ""
        while True:
            job = repository().get_job(job_id)
            if not job or job["module_id"] != module_id:
                yield 'event: error\ndata: {"code":"JOB_NOT_FOUND"}\n\n'
                return
            data = json.dumps(job, ensure_ascii=False)
            if data != previous:
                yield f"data: {data}\n\n"
                previous = data
            if job["status"] in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(.75)
    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/samba/users")
def samba_users(user: SessionUser = Depends(current_admin)):
    _authorize(user, "samba", "view")
    return SambaProvider(user.username).users()


@router.post("/samba/users/{username}/{action}")
def samba_user_action(username: str, action: Literal["add", "password", "enable", "disable", "remove"], payload: SambaUserRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, "samba", "configure")
    SambaProvider(user.username).manage_user(action, username, payload.password)
    logger.info("module_user actor=%s module=samba action=%s target=%s", user.username, action, username)
    record_activity(ActivityCategory.module, f"samba_user_{action}", user.username, target="samba", details={"username": username}, source="modules")
    return {"ok": True}


@router.get("/samba/sessions")
def samba_sessions(user: SessionUser = Depends(current_admin)):
    _authorize(user, "samba", "view")
    return SambaProvider(user.username).sessions()


@router.get("/samba/shares/{share_name}/test")
def samba_share_test(share_name: str, user: SessionUser = Depends(current_admin)):
    _authorize(user, "samba", "view")
    return SambaProvider(user.username).test_share_access(share_name)


@router.delete("/samba/shares/{share_name}")
def samba_share_remove(share_name: str, payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, "samba", "configure")
    provider = SambaProvider(user.username)
    config = provider.get_config()
    shares = config.get("shares") or []
    remaining = [item for item in shares if str(item.get("name", "")).casefold() != share_name.casefold()]
    if len(remaining) == len(shares):
        api_error(404, "SHARE_NOT_FOUND", "Samba share was not found")
    next_config = {**config, "shares": remaining}
    validation = provider.validate_config(next_config)
    if not validation.ok:
        api_error(422, "CONFIG_VALIDATION_FAILED", "Samba configuration without the share is invalid", validation=validation.model_dump(mode="json"))
    result = _enqueue(_provider_plan("samba", PackageAction.apply, {"config": next_config}, backup=True), payload, user)
    logger.info("module_share actor=%s module=samba action=remove share=%s job=%s", user.username, share_name, result["job"]["id"])
    return result


@router.post("/samba/import/validate")
def samba_import_validate(payload: SambaImportRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, "samba", "configure")
    try:
        config = parse_smb_conf(payload.content)
    except ValueError as error:
        api_error(422, "IMPORT_VALIDATION_FAILED", str(error))
    return {"config": config.model_dump(), "validation": SambaProvider(user.username).validate_config(config.model_dump())}


@router.get("/samba/firewall")
def samba_firewall(user: SessionUser = Depends(current_admin)):
    _authorize(user, "samba", "view")
    adapter = "ufw" if shutil.which("ufw") else "firewalld" if shutil.which("firewall-cmd") else "unsupported"
    plan = [["ufw", "allow", "Samba"]] if adapter == "ufw" else [["firewall-cmd", "--permanent", "--add-service=samba"], ["firewall-cmd", "--reload"]] if adapter == "firewalld" else []
    return {"adapter": adapter, "ports": ["137/udp", "138/udp", "139/tcp", "445/tcp"], "can_manage": adapter != "unsupported", "plan": plan}


@router.post("/samba/firewall/open")
def samba_firewall_open(payload: ModuleAdminRequest, user: SessionUser = Depends(mutating_admin)):
    _authorize(user, "samba", "configure")
    if shutil.which("ufw"):
        commands = [[shutil.which("ufw") or "ufw", "allow", "Samba"]]
    elif shutil.which("firewall-cmd"):
        executable = shutil.which("firewall-cmd") or "firewall-cmd"
        commands = [[executable, "--permanent", "--add-service=samba"], [executable, "--reload"]]
    else:
        api_error(409, "FIREWALL_UNSUPPORTED", "No supported firewall was detected")
    if not payload.confirm:
        return {"plan": commands, "requires_confirmation": True}
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False, shell=False)
        if result.returncode != 0:
            api_error(500, "FIREWALL_UPDATE_FAILED", result.stderr.strip() or "Could not update firewall")
    logger.info("module_firewall actor=%s module=samba action=open_ports", user.username)
    record_activity(ActivityCategory.module, "firewall_open", user.username, target="samba", source="modules")
    return {"ok": True, "plan": commands}
