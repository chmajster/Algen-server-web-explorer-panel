from __future__ import annotations

from dataclasses import dataclass
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
from .local_auth import (
    LocalAuthConfigurationError,
    LocalInvalidCredentials,
    auth_mode,
    authenticate_local,
    local_home,
)
from .security import clear_session, create_session, get_session_user, rate_limiter, require_csrf

router = APIRouter(prefix="/api/auth", tags=["authentication"])
AuthMethod = Literal["local", "pam", "ldap"]


@dataclass(frozen=True, slots=True)
class LocalAuthenticatedIdentity:
    username: str
    provider: Literal["local"]
    home: str
    display_name: str = ""


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
    mode = auth_mode()
    if mode == "local":
        if requested not in {None, "local"}:
            raise HTTPException(HTTPStatus.BAD_REQUEST, "Selected authentication method is not available.")
        return "local"

    enabled = ldap_enabled()
    if requested == "local":
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Selected authentication method is not available.")
    if requested == "ldap" and not enabled:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Selected authentication method is not available.")
    if requested is not None:
        return requested
    return "ldap" if enabled else "pam"


def _pam_identity(username: str, password: str) -> AuthenticatedIdentity:
    authenticate(username, password)
    return AuthenticatedIdentity(username=username, provider="pam", home=user_home(username))


def _local_identity(username: str, password: str) -> LocalAuthenticatedIdentity:
    try:
        user = authenticate_local(username, password)
    except ValueError as error:
        # Invalid local usernames are authentication failures, not application
        # errors. Keep the response indistinguishable from a bad password.
        raise LocalInvalidCredentials("Invalid username or password") from error
    return LocalAuthenticatedIdentity(
        username=str(user["username"]),
        provider="local",
        home=str(user["home"]),
        display_name=str(user.get("display_name") or ""),
    )


@router.get("/config")
def authentication_config():
    mode = auth_mode()
    if mode == "local":
        return {
            "mode": "local",
            "local_enabled": True,
            "pam_enabled": False,
            "ldap_enabled": False,
            "available_providers": ["local"],
            "default_provider": "local",
        }
    enabled = ldap_enabled()
    return {
        "mode": "system",
        "local_enabled": False,
        "pam_enabled": True,
        "ldap_enabled": enabled,
        "available_providers": ["ldap", "pam"] if enabled else ["pam"],
        "default_provider": "ldap" if enabled else "pam",
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    username = normalize_username(payload.username)
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{username}"
    provider: AuthMethod = "local" if auth_mode() == "local" else "pam"
    identity: LocalAuthenticatedIdentity | AuthenticatedIdentity
    try:
        rate_limiter.check(key)
        provider = _selected_provider(payload.auth_method)
        if provider == "local":
            identity = _local_identity(username, payload.password)
        elif provider == "ldap":
            identity = authenticate_ldap(username, payload.password)
        else:
            identity = _pam_identity(username, payload.password)
    except (LocalInvalidCredentials, LdapInvalidCredentials) as error:
        rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": 401, "provider": provider},
            source="auth",
        )
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid username or password") from error
    except LocalAuthConfigurationError as error:
        rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": 503, "provider": "local"},
            source="auth",
        )
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, "Local authentication service is unavailable.") from error
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
    if user.auth_provider == "local":
        home = local_home(user.username)
    elif user.auth_provider == "pam":
        home = user_home(user.username)
    else:
        home = ldap_home(user.username)
    if not home:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid or expired session")
    return {
        "username": user.username,
        "home": home,
        "csrf_token": user.csrf_token,
        "auth_provider": user.auth_provider,
    }
