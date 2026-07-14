from __future__ import annotations

import grp
import pwd

from fastapi import HTTPException, Request

from ..auth import authenticate
from ..security import SessionUser, get_session_user, require_csrf


def is_admin(username: str) -> bool:
    try:
        user = pwd.getpwnam(username)
        if user.pw_uid == 0:
            return True
        groups = {item.gr_name for item in grp.getgrall() if username in item.gr_mem or item.gr_gid == user.pw_gid}
    except KeyError:
        return False
    return bool(groups & {"sudo", "wheel"})


def current_admin(request: Request) -> SessionUser:
    user = get_session_user(request)
    if not is_admin(user.username):
        raise HTTPException(403, {"code": "ADMIN_REQUIRED", "message": "Administrator privileges required"})
    return user


def mutating_admin(request: Request) -> SessionUser:
    user = current_admin(request)
    require_csrf(request, user)
    return user


def reauthenticate(user: SessionUser, password: str) -> None:
    try:
        authenticate(user.username, password)
    except HTTPException as error:
        raise HTTPException(401, {"code": "AUTHENTICATION_FAILED", "message": "Administrator authentication failed"}) from error
