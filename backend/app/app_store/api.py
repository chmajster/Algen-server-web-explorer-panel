from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import logger
from ..identity.permissions import Permission, authorize
from ..package_center.models import PackageAction
from ..security import SessionUser, get_session_user, require_csrf
from .models import AdminAction, SambaApplyRequest, SambaPassword, SambaSecuredApplyRequest, SambaServiceAction, SambaUserAction
from .samba import _run, preview_samba_config, read_samba_config, samba_status_payload, samba_users_payload
from .state import read_state


router = APIRouter(prefix="/api/apps")


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _enqueue_samba_config(config, confirm_smb1: bool, user: SessionUser) -> dict:
    # Provider/planning imports stay inside the operation boundary. Importing
    # them while app.apps is being loaded creates a cycle through SambaProvider.
    from ..modules.planning import provider_plan
    from ..modules.providers.samba import SambaProvider
    from ..package_center.jobs import manager
    from ..package_center.service import repository

    authorize(user, Permission.MODULES_CONFIGURE)
    validation = SambaProvider(user.username).validate_config(config.model_dump())
    if not validation.ok:
        raise HTTPException(422, {"code": "CONFIG_VALIDATION_FAILED", "message": "Samba configuration is invalid", "validation": validation.model_dump(mode="json")})
    if "smb1" in validation.confirmations_required and not confirm_smb1:
        raise HTTPException(400, {"code": "SECURITY_CONFIRMATION_REQUIRED", "message": "Enabling SMB1 requires explicit confirmation", "confirmation": "smb1"})
    plan = provider_plan("samba", PackageAction.apply, {"config": config.model_dump()}, backup=True)
    job = manager(repository()).enqueue(plan, user.username)
    logger.info("app_store_config actor=%s app=samba action=apply_config job=%s", user.username, job["id"])
    return {"job": job}


@router.get("/samba/status")
def samba_status(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return samba_status_payload()


@router.get("/samba/users")
def samba_users(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return samba_users_payload()


@router.post("/samba/preview")
def samba_preview(payload: SambaApplyRequest, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    return preview_samba_config(user.username, payload.config or read_samba_config())


@router.post("/samba/apply")
def samba_apply(payload: SambaSecuredApplyRequest, user: SessionUser = Depends(_current_user)):
    return _enqueue_samba_config(payload.config, payload.confirm_smb1, user)


@router.post("/samba/rollback")
def samba_rollback(payload: AdminAction, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_BACKUP_RESTORE)
    raise HTTPException(409, {"code": "MODULE_BACKUP_REQUIRED", "message": "Use the verified module backup restore endpoint"})


@router.post("/samba/service")
def samba_service(payload: SambaServiceAction, user: SessionUser = Depends(_current_user)):
    if payload.action not in {"start", "stop", "restart", "reload"}:
        raise HTTPException(400, "Unsupported Samba service action")
    from ..modules.planning import provider_plan
    from ..modules.router import ModuleAdminRequest, _enqueue

    authorize(user, Permission.MODULES_CONFIGURE)
    result = _enqueue(provider_plan("samba", PackageAction(payload.action), {}), ModuleAdminRequest(), user)
    logger.info("app_store_action actor=%s app=samba action=%s job=%s", user.username, payload.action, result["job"]["id"])
    return result


@router.post("/samba/users/enable")
def samba_user_enable(payload: SambaPassword, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    if not shutil.which("smbpasswd"):
        raise HTTPException(503, "smbpasswd is not installed")
    _run(["smbpasswd", "-s", "-a", payload.username], input_text=f"{payload.password}\n{payload.password}\n")
    _run(["smbpasswd", "-e", payload.username])
    logger.info("app_store_config actor=%s app=samba action=enable_samba_user target=%s", user.username, payload.username)
    return {"ok": True}


@router.post("/samba/users/disable")
def samba_user_disable(payload: SambaUserAction, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    if not shutil.which("smbpasswd"):
        raise HTTPException(503, "smbpasswd is not installed")
    _run(["smbpasswd", "-d", payload.username])
    logger.info("app_store_config actor=%s app=samba action=disable_samba_user target=%s", user.username, payload.username)
    return {"ok": True}


@router.get("/{app_id}/config")
def get_config_app(app_id: str, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_VIEW)
    if app_id != "samba":
        return read_state(app_id).get("config") or {}
    return read_samba_config().model_dump()


@router.put("/{app_id}/config")
def put_config_app(app_id: str, payload: SambaSecuredApplyRequest, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    if app_id != "samba":
        raise HTTPException(404, "Unsupported app module")
    return _enqueue_samba_config(payload.config, payload.confirm_smb1, user)


@router.post("/samba/smbpasswd")
def set_samba_password(payload: SambaPassword, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    if not shutil.which("smbpasswd"):
        raise HTTPException(503, "smbpasswd is not installed")
    _run(["smbpasswd", "-s", "-a", payload.username], input_text=f"{payload.password}\n{payload.password}\n")
    logger.info("app_store_config actor=%s app=samba action=set_samba_password target=%s", user.username, payload.username)
    return {"ok": True}
