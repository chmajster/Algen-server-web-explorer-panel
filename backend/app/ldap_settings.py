from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .activity import ActivityCategory, ActivityStatus, record_activity
from .identity.service import access_profile
from .ldap_auth import (
    LdapConfigurationError,
    LdapServiceUnavailable,
    LdapSettingsInput,
    settings_repository,
    test_ldap_connection,
)
from .security import SessionUser, get_session_user, require_csrf


router = APIRouter(prefix="/api/settings/authentication/ldap", tags=["settings", "authentication"])


def _admin_user(request: Request, *, mutate: bool) -> SessionUser:
    user = get_session_user(request)
    if mutate:
        require_csrf(request, user)
    profile = access_profile(user.username)
    if not bool(profile.get("is_admin")):
        raise HTTPException(HTTPStatus.FORBIDDEN, "Administrator access required")
    return user


def admin_read(request: Request) -> SessionUser:
    return _admin_user(request, mutate=False)


def admin_write(request: Request) -> SessionUser:
    return _admin_user(request, mutate=True)


@router.get("")
def get_ldap_settings(user: SessionUser = Depends(admin_read)):
    settings = settings_repository().get()
    return settings.public_dict()


@router.put("")
def save_ldap_settings(
    payload: LdapSettingsInput,
    user: SessionUser = Depends(admin_write),
):
    try:
        saved = settings_repository().save(payload, user.username)
    except (ValueError, ValidationError) as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    record_activity(
        ActivityCategory.administration,
        "ldap.settings.updated",
        user.username,
        details={"enabled": saved.enabled, "security_mode": saved.security_mode},
        source="settings",
    )
    return saved.public_dict()


@router.post("/test")
def test_saved_ldap_settings(user: SessionUser = Depends(admin_write)):
    try:
        result = test_ldap_connection()
    except LdapConfigurationError as error:
        record_activity(
            ActivityCategory.administration,
            "ldap.connection.tested",
            user.username,
            status=ActivityStatus.failure,
            details={"stage": "configuration"},
            source="settings",
        )
        raise HTTPException(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            {"code": "LDAP_CONFIGURATION_INVALID", "message": "LDAP search configuration is invalid."},
        ) from error
    except LdapServiceUnavailable as error:
        record_activity(
            ActivityCategory.administration,
            "ldap.connection.tested",
            user.username,
            status=ActivityStatus.failure,
            details={"stage": error.stage},
            source="settings",
        )
        message = {
            "connect": "LDAP server is unavailable.",
            "tls": "LDAP TLS verification failed.",
            "bind": "LDAP bind failed.",
            "search": "LDAP search configuration is invalid.",
        }.get(error.stage, "LDAP connection test failed.")
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY,
            {"code": error.code, "message": message},
        ) from error

    record_activity(
        ActivityCategory.administration,
        "ldap.connection.tested",
        user.username,
        details={"stage": result["stage"]},
        source="settings",
    )
    return {"ok": True, "message": "LDAP connection successful."}
