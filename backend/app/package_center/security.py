from __future__ import annotations

from fastapi import HTTPException, Request

from ..security import SessionUser, get_session_user, require_csrf
from ..rbac import access_profile


def is_admin(username: str) -> bool:
    return bool(access_profile(username)["is_admin"])


def current_admin(request: Request) -> SessionUser:
    user = get_session_user(request)
    if not is_admin(user.username):
        raise HTTPException(403, {"code": "ADMIN_REQUIRED", "message": "Administrator privileges required"})
    return user


def current_user(request: Request) -> SessionUser:
    return get_session_user(request)


def mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def mutating_admin(request: Request) -> SessionUser:
    user = current_admin(request)
    require_csrf(request, user)
    return user
