from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..identity.permissions import Permission, authorize
from ..security import SessionUser, get_session_user, require_csrf
from .models import StorePlugin
from .service import PLUGIN_CODEX_TEMPLATE, service


router = APIRouter(prefix="/api/apps/plugins", tags=["plugins"])


def _user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


@router.get("")
def list_plugins(user: SessionUser = Depends(_user)):
    authorize(user, Permission.MODULES_VIEW)
    return {"plugins": [item.model_dump(mode="json") for item in service().list()], "codex_template": PLUGIN_CODEX_TEMPLATE}


@router.post("")
def create_plugin(payload: StorePlugin, user: SessionUser = Depends(_user)):
    authorize(user, Permission.MODULES_INSTALL)
    return service().create(payload, user.username).model_dump(mode="json")


@router.put("/{plugin_id}")
def update_plugin(plugin_id: str, payload: StorePlugin, user: SessionUser = Depends(_user)):
    authorize(user, Permission.MODULES_INSTALL)
    return service().update(plugin_id, payload, user.username).model_dump(mode="json")


@router.delete("/{plugin_id}")
def delete_plugin(plugin_id: str, user: SessionUser = Depends(_user)):
    authorize(user, Permission.MODULES_UNINSTALL)
    service().delete(plugin_id, user.username)
    return {"ok": True}
