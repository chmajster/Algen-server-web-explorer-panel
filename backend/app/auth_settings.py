from __future__ import annotations

from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .activity import ActivityCategory, ActivityStatus, record_activity
from .identity.service import access_profile
from .local_auth import AuthMode, LocalInvalidCredentials, auth_mode, repository as local_repository
from .security import (
    SessionUser,
    get_session_user,
    invalidate_provider_user_sessions,
    require_csrf,
)


router = APIRouter(prefix="/api/settings/authentication", tags=["settings", "authentication"])


class AuthenticationModeUpdate(BaseModel):
    mode: AuthMode


class LocalUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=33)
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["admin", "operator", "auditor", "user"] = "user"
    display_name: str = Field(default="", max_length=256)


class LocalUserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=12, max_length=1024)
    role: Literal["admin", "operator", "auditor", "user"] | None = None
    enabled: bool | None = None
    display_name: str | None = Field(default=None, max_length=256)


class LocalPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


def _session_user(request: Request, *, mutate: bool) -> SessionUser:
    user = get_session_user(request)
    if mutate:
        require_csrf(request, user)
    return user


def _admin_user(request: Request, *, mutate: bool) -> SessionUser:
    user = _session_user(request, mutate=mutate)
    profile = access_profile(user.username)
    if not bool(profile.get("is_admin")):
        raise HTTPException(HTTPStatus.FORBIDDEN, "Administrator access required")
    return user


def admin_read(request: Request) -> SessionUser:
    return _admin_user(request, mutate=False)


def admin_write(request: Request) -> SessionUser:
    return _admin_user(request, mutate=True)


def local_write(request: Request) -> SessionUser:
    user = _session_user(request, mutate=True)
    if user.auth_provider != "local":
        raise HTTPException(HTTPStatus.CONFLICT, "This password endpoint is available only for local WebNAS accounts")
    return user


def _state() -> dict:
    store = local_repository()
    active_mode = auth_mode()
    configured_mode = store.auth_mode()
    users = store.users()
    return {
        "mode": active_mode,
        "configured_mode": configured_mode,
        "restart_required": active_mode != configured_mode,
        "default_mode": "local",
        "local_database_enabled": active_mode == "local",
        "system_authentication_enabled": active_mode == "system",
        "local_user_count": len(users),
        "local_enabled_admin_count": store.enabled_admin_count(),
    }


@router.get("")
def get_authentication_settings(user: SessionUser = Depends(admin_read)):
    return _state()


@router.put("")
def set_authentication_settings(
    payload: AuthenticationModeUpdate,
    user: SessionUser = Depends(admin_write),
):
    store = local_repository()
    previous_configured_mode = store.auth_mode()
    try:
        configured_mode = store.set_auth_mode(payload.mode, user.username)
    except ValueError as error:
        raise HTTPException(HTTPStatus.CONFLICT, str(error)) from error
    if configured_mode != previous_configured_mode:
        record_activity(
            ActivityCategory.administration,
            "auth.mode.changed",
            user.username,
            details={
                "active": auth_mode(),
                "previous_configured": previous_configured_mode,
                "configured": configured_mode,
                "restart_required": auth_mode() != configured_mode,
            },
            source="settings",
        )
    return {**_state(), "reauthentication_required": False}


@router.post("/local-password")
def change_local_password(
    payload: LocalPasswordChange,
    user: SessionUser = Depends(local_write),
):
    store = local_repository()
    try:
        store.authenticate(user.username, payload.current_password)
        store.update_user(user.username, password=payload.new_password)
    except LocalInvalidCredentials as error:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid username or password") from error
    except ValueError as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    record_activity(
        ActivityCategory.configuration,
        "password_change",
        user.username,
        target=user.username,
        details={"provider": "local"},
        source="settings",
    )
    return {"ok": True}


@router.get("/local-users")
def get_local_users(user: SessionUser = Depends(admin_read)):
    return {"users": local_repository().users()}


@router.post("/local-users")
def create_local_user(
    payload: LocalUserCreate,
    user: SessionUser = Depends(admin_write),
):
    try:
        created = local_repository().create_user(
            payload.username,
            payload.password,
            role=payload.role,
            display_name=payload.display_name,
        )
    except ValueError as error:
        raise HTTPException(HTTPStatus.CONFLICT, str(error)) from error
    record_activity(
        ActivityCategory.administration,
        "auth.local_user.created",
        user.username,
        target=created["username"],
        details={"role": created["role"], "enabled": created["enabled"]},
        source="settings",
    )
    return created


@router.patch("/local-users/{username}")
def update_local_user(
    username: str,
    payload: LocalUserPatch,
    user: SessionUser = Depends(admin_write),
):
    try:
        updated = local_repository().update_user(
            username,
            role=payload.role,
            enabled=payload.enabled,
            display_name=payload.display_name,
            password=payload.password,
        )
    except LookupError as error:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(error)) from error
    except ValueError as error:
        raise HTTPException(HTTPStatus.CONFLICT, str(error)) from error
    if payload.password is not None or payload.enabled is False or payload.role is not None:
        invalidate_provider_user_sessions(username, "local")
    record_activity(
        ActivityCategory.administration,
        "auth.local_user.updated",
        user.username,
        target=updated["username"],
        details={
            "role": updated["role"],
            "enabled": updated["enabled"],
            "password_changed": payload.password is not None,
        },
        source="settings",
    )
    return updated


@router.delete("/local-users/{username}")
def delete_local_user(
    username: str,
    user: SessionUser = Depends(admin_write),
):
    if user.auth_provider == "local" and user.username.casefold() == username.casefold():
        raise HTTPException(HTTPStatus.CONFLICT, "The currently signed-in local user cannot be deleted")
    try:
        local_repository().delete_user(username)
    except LookupError as error:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(error)) from error
    except ValueError as error:
        raise HTTPException(HTTPStatus.CONFLICT, str(error)) from error
    invalidate_provider_user_sessions(username, "local")
    record_activity(
        ActivityCategory.administration,
        "auth.local_user.deleted",
        user.username,
        target=username,
        status=ActivityStatus.success,
        source="settings",
    )
    return {"ok": True}
