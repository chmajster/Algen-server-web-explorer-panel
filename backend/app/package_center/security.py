from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from ..auth import authenticate
from ..config import get_config
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


def reauthenticate(user: SessionUser, password: str) -> None:
    now = time.time()
    with _reauth_lock:
        attempts = _reauth_attempts[user.username]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= get_config().security.rate_limit_admin_per_minute:
            raise HTTPException(429, {"code": "RATE_LIMITED", "message": "Too many administrative authentication attempts"})
        attempts.append(now)
    try:
        authenticate(user.username, password)
    except HTTPException as error:
        raise HTTPException(401, {"code": "AUTHENTICATION_FAILED", "message": "Administrator authentication failed"}) from error


_reauth_lock = threading.Lock()
_reauth_attempts: defaultdict[str, deque[float]] = defaultdict(deque)
