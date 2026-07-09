from __future__ import annotations

import os
import pwd

import pam
from fastapi import HTTPException

from .config import get_config


BLOCKED_LOGIN_SHELLS = {
    "",
    "/bin/false",
    "/usr/bin/false",
    "/sbin/nologin",
    "/usr/sbin/nologin",
}


def system_user(username: str) -> pwd.struct_passwd:
    try:
        return pwd.getpwnam(username)
    except KeyError as exc:
        raise HTTPException(401, "Unknown local user") from exc


def assert_login_allowed(username: str) -> pwd.struct_passwd:
    if not username or "/" in username or "\x00" in username:
        raise HTTPException(400, "Invalid username")
    user = system_user(username)
    cfg = get_config()
    if user.pw_uid < cfg.security.system_uid_threshold:
        raise HTTPException(403, "System service accounts cannot log in")
    if user.pw_shell in BLOCKED_LOGIN_SHELLS:
        raise HTTPException(403, "User shell does not allow login")
    if not user.pw_dir:
        raise HTTPException(403, "User has no home directory")
    return user


def authenticate(username: str, password: str) -> None:
    assert_login_allowed(username)
    if not password:
        raise HTTPException(401, "Invalid username or password")
    authenticator = pam.pam()
    if not authenticator.authenticate(username, password):
        raise HTTPException(401, "Invalid username or password")


def user_home(username: str) -> str:
    return system_user(username).pw_dir


def current_process_can_impersonate() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
