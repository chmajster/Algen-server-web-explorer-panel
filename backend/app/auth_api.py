from __future__ import annotations

from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .activity import ActivityCategory, ActivityStatus, record_activity
from .audit import logger
from .auth import authenticate, normalize_username, user_home
from .ldap_auth import (
    AuthenticatedIdentity,
    LdapConfigurationError,
    LdapInvalidCredentials,
    LdapServiceUnavailable,
    authenticate_ldap,
    ldap_enabled,
    ldap_home,
)
from .security import clear_session, create_session, get_session_user, rate_limiter, require_csrf

router = APIRouter(prefix="/api/auth", tags=["authentication"])
AuthMethod = Literal["pam", "ldap"]


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False
    auth_method: AuthMethod | None = None


def current_user(request: Request):
    return get_session_user(request)


def csrf_user(request: Request):
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def _selected_provider(requested: AuthMethod | None) -> AuthMethod:
    enabled = ldap_enabled()
    if requested == "ldap" and not enabled:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Selected authentication method is not available.")
    if requested is not None:
        return requested
    return "ldap" if enabled else "pam"


def _pam_identity(username: str, password: str) -> AuthenticatedIdentity:
    authenticate(username, password)
    return AuthenticatedIdentity(username=username, provider="pam", home=user_home(username))


@router.get("/config")
def authentication_config():
    enabled = ldap_enabled()
    return {
        "pam_enabled": True,
        "ldap_enabled": enabled,
        "default_provider": "ldap" if enabled else "pam",
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    username = normalize_username(payload.username)
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{username}"
    provider: AuthMethod = "pam"
    try:
        rate_limiter.check(key)
        provider = _selected_provider(payload.auth_method)
        if provider == "ldap":
            identity = authenticate_ldap(username, payload.password)
        else:
            identity = _pam_identity(username, payload.password)
    except LdapInvalidCredentials as error:
        rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": 401, "provider": "ldap"},
            source="auth",
        )
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid username or password") from error
    except LdapConfigurationError as error:
        rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": 503, "provider": "ldap"},
            source="auth",
        )
        raise HTTPException(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "LDAP authentication service is temporarily unavailable.",
        ) from error
    except LdapServiceUnavailable as error:
        rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": 503, "provider": "ldap", "stage": error.stage},
            source="auth",
        )
        raise HTTPException(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "LDAP authentication service is temporarily unavailable.",
        ) from error
    except HTTPException as error:
        if error.status_code != 429:
            rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": error.status_code, "provider": provider},
            source="auth",
        )
        raise

    rate_limiter.clear(key)
    csrf = create_session(
        response,
        identity.username,
        auth_provider=identity.provider,
        remember_me=payload.remember_me,
    )
    logger.info("login user=%s provider=%s", identity.username, identity.provider)
    record_activity(
        ActivityCategory.login,
        "login",
        identity.username,
        details={
            "client": client,
            "persistent": payload.remember_me,
            "provider": identity.provider,
        },
        source="auth",
    )
    return {
        "username": identity.username,
        "home": identity.home,
        "csrf_token": csrf,
        "auth_provider": identity.provider,
    }


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(csrf_user)):
    logger.info("logout user=%s provider=%s", user.username, user.auth_provider)
    record_activity(
        ActivityCategory.login,
        "logout",
        user.username,
        details={"provider": user.auth_provider},
        source="auth",
    )
    clear_session(response, request)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    home = user_home(user.username) if user.auth_provider == "pam" else ldap_home(user.username)
    if not home:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid or expired session")
    return {
        "username": user.username,
        "home": home,
        "csrf_token": user.csrf_token,
        "auth_provider": user.auth_provider,
    }
