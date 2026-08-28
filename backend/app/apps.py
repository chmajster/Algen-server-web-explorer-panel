"""Compatibility facade for the legacy ``app.apps`` import path.

The HTTP router, Samba implementation, persistent state and plugin store live in
focused subsystems. This module intentionally contains no in-memory job store
and starts no background threads.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException

from .app_store import samba as _samba
from .app_store import state as _state
from .app_store.api import router
from .app_store.models import AdminAction, SambaApplyRequest, SambaConfig, SambaPassword, SambaSecuredApplyRequest, SambaServiceAction, SambaShare, SambaUserAction
from .app_store.service import all_manifests as _all_manifests
from .app_store.service import load_manifest as _load_manifest
from .audit import logger
from .config import get_config
from .identity.permissions import Permission, authorize
from .plugins.models import StorePlugin
from .plugins.service import PLUGIN_CODEX_TEMPLATE, service as plugin_service
from .plugins.validator import PluginValidator
from .proxmox_guard import safe_mode_active
from .security import SessionUser


MODULES_DIR = Path(__file__).resolve().parent / "modules"
APP_STATE_DIR = Path(get_config().paths.data_dir) / "apps"
APP_LOG_DIR = Path("/var/log/webnas/apps")
SAMBA_CONF = _samba.SAMBA_CONF
SAMBA_ALGEN_CONF = _samba.SAMBA_ALGEN_CONF
SHARE_RE = _samba.SHARE_RE
SAFE_SAMBA_VFS_OBJECTS = _samba.SAFE_SAMBA_VFS_OBJECTS

_validate_share_path_impl = _samba.validate_share_path
_preview_samba_config_impl = _samba.preview_samba_config
_write_samba_config_impl = _samba.write_samba_config


def _sync_legacy_overrides() -> None:
    _state.APP_STATE_DIR = APP_STATE_DIR
    _samba.SAMBA_CONF = SAMBA_CONF
    _samba.SAMBA_ALGEN_CONF = SAMBA_ALGEN_CONF
    _samba.safe_mode_active = safe_mode_active
    _samba.validate_share_path = validate_share_path


def _require_admin(user: SessionUser, permission: Permission = Permission.MODULES_CONFIGURE) -> None:
    authorize(user, permission)


def _job_error_message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        if isinstance(error.detail, str):
            return error.detail
        if isinstance(error.detail, dict):
            return str(error.detail.get("message") or error.detail.get("detail") or "Administrative operation failed")
    if isinstance(error, subprocess.TimeoutExpired):
        command = error.cmd[0] if isinstance(error.cmd, list) and error.cmd else "Command"
        return f"{Path(str(command)).name} timed out after {error.timeout} seconds"
    return str(error) or "Administrative operation failed"


def load_manifest(app_id: str) -> dict:
    return _load_manifest(app_id)


def all_manifests() -> list[dict]:
    return _all_manifests()


def app_state_path(app_id: str) -> Path:
    _sync_legacy_overrides()
    return _state.app_state_path(app_id)


def read_state(app_id: str) -> dict:
    _sync_legacy_overrides()
    return _state.read_state(app_id)


def write_state(app_id: str, state: dict) -> None:
    _sync_legacy_overrides()
    _state.write_state(app_id, state)


def plan_install(app_id: str) -> list[str]:
    manifest = load_manifest(app_id)
    if app_id == "samba" and not shutil.which("apt-get"):
        return ["Samba module requires apt-get on Debian/Ubuntu-like systems."]
    steps = [f"Install packages: {', '.join(manifest.get('apt_packages', []))}"]
    steps += [f"Enable/start service: {service}" for service in manifest.get("systemd_services", [])]
    return steps


def assert_app_allowed_on_host(app_id: str) -> None:
    manifest = load_manifest(app_id)
    if safe_mode_active() and not manifest.get("proxmox_safe", False):
        raise HTTPException(403, "Module is blocked by Proxmox Safe Mode")


def read_samba_config() -> SambaConfig:
    _sync_legacy_overrides()
    return _samba.read_samba_config()


def backup_smb_conf(now: str | None = None) -> Path | None:
    _sync_legacy_overrides()
    return _samba.backup_smb_conf(now)


def backup_algen_smb_conf(now: str | None = None) -> Path | None:
    _sync_legacy_overrides()
    return _samba.backup_algen_smb_conf(now)


def remove_smb_conf_include() -> None:
    _sync_legacy_overrides()
    _samba.remove_smb_conf_include()


def validate_share_path(username: str, share: SambaShare) -> Path:
    _sync_legacy_overrides()
    return _validate_share_path_impl(username, share)


def validate_share_model(share: SambaShare) -> None:
    _sync_legacy_overrides()
    _samba.validate_share_model(share)


def validate_samba_config(config: SambaConfig) -> None:
    _sync_legacy_overrides()
    _samba.validate_samba_config(config)


def render_smb_conf(config: SambaConfig) -> str:
    _sync_legacy_overrides()
    return _samba.render_smb_conf(config)


def testparm_config(config_text: str) -> dict:
    _sync_legacy_overrides()
    return _samba.testparm_config(config_text)


def preview_samba_config(username: str, config: SambaConfig) -> dict:
    _sync_legacy_overrides()
    return _preview_samba_config_impl(username, config)


def write_samba_config(username: str, config: SambaConfig) -> None:
    _sync_legacy_overrides()
    _samba.preview_samba_config = preview_samba_config
    _write_samba_config_impl(username, config)


def samba_service_names() -> list[str]:
    return _samba.samba_service_names()


def samba_port_status() -> dict[str, bool]:
    return _samba.samba_port_status()


def samba_users_payload() -> list[dict]:
    return _samba.samba_users_payload()


def samba_status_payload() -> dict:
    _sync_legacy_overrides()
    return _samba.samba_status_payload()


def rollback_samba_config(username: str) -> dict:
    _sync_legacy_overrides()
    result = _samba.rollback_samba_config(username)
    logger.info("app_store_config actor=%s app=samba action=rollback", username)
    return result


def _validate_plugin(plugin: StorePlugin) -> StorePlugin:
    plugin.codex_instructions = plugin.codex_instructions.strip() or PLUGIN_CODEX_TEMPLATE.format(github_url=plugin.github_url, branch=plugin.branch)
    return PluginValidator().validate_store_plugin(plugin)


def read_store_plugins() -> list[StorePlugin]:
    return plugin_service().list()


def write_store_plugins(plugins: list[StorePlugin]) -> None:
    repository = plugin_service().repository
    wanted = {item.id for item in plugins}
    for existing in repository.list():
        if existing.id not in wanted:
            repository.delete(existing.id)
    for plugin in plugins:
        repository.upsert(_validate_plugin(plugin))


def list_apps(user: SessionUser):
    authorize(user, Permission.MODULES_VIEW)
    from .package_center.service import list_modules

    return list_modules()


def get_app(app_id: str, user: SessionUser):
    authorize(user, Permission.MODULES_VIEW)
    from .package_center.service import get_module

    return get_module(app_id)


def install_app(app_id: str, payload: AdminAction, user: SessionUser):
    _require_admin(user, Permission.MODULES_INSTALL)
    from .package_center.jobs import manager as package_manager
    from .package_center.models import PackageAction
    from .package_center.service import plan_operation, repository

    plan = plan_operation(app_id, PackageAction.install)
    if payload.dry_run:
        return {"dry_run": True, "plan": plan.model_dump()}
    logger.info("app_store_action actor=%s app=%s action=install", user.username, app_id)
    return {"job": package_manager(repository()).enqueue(plan, user.username)}


def uninstall_app(app_id: str, payload: AdminAction, user: SessionUser):
    _require_admin(user, Permission.MODULES_UNINSTALL)
    from .package_center.jobs import manager as package_manager
    from .package_center.models import PackageAction
    from .package_center.service import plan_operation, repository

    plan = plan_operation(app_id, PackageAction.uninstall)
    if payload.dry_run:
        return {"dry_run": True, "plan": plan.model_dump()}
    logger.info("app_store_action actor=%s app=%s action=uninstall", user.username, app_id)
    return {"job": package_manager(repository()).enqueue(plan, user.username)}


def update_app(app_id: str, payload: AdminAction, user: SessionUser):
    _require_admin(user, Permission.MODULES_UPDATE)
    from .package_center.jobs import manager as package_manager
    from .package_center.models import PackageAction
    from .package_center.service import plan_operation, repository

    plan = plan_operation(app_id, PackageAction.update)
    if payload.dry_run:
        return {"dry_run": True, "plan": plan.model_dump()}
    logger.info("app_store_action actor=%s app=%s action=update", user.username, app_id)
    return {"job": package_manager(repository()).enqueue(plan, user.username)}


def _service_action(app_id: str, action: str, payload: AdminAction, user: SessionUser) -> dict:
    _require_admin(user)
    from .app_store.service import run_service

    if payload.dry_run:
        return {"dry_run": True, "steps": [f"systemctl {action} service(s) from manifest"]}
    logger.info("app_store_action actor=%s app=%s action=%s", user.username, app_id, action)
    run_service(app_id, action)
    return {"ok": True}


def start_app(app_id: str, payload: AdminAction, user: SessionUser):
    return _service_action(app_id, "start", payload, user)


def stop_app(app_id: str, payload: AdminAction, user: SessionUser):
    return _service_action(app_id, "stop", payload, user)


def restart_app(app_id: str, payload: AdminAction, user: SessionUser):
    return _service_action(app_id, "restart", payload, user)


def app_logs(app_id: str, user: SessionUser):
    authorize(user, Permission.MODULES_LOGS)
    from .package_center.service import repository

    jobs = repository().list_jobs(module_id=app_id, limit=20)
    return {"jobs": jobs, "lines": [entry["line"] for job in reversed(jobs) for entry in job["log_tail"]][-500:]}
