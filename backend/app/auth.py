from __future__ import annotations

import os
import pwd
from pathlib import Path

import pam
from fastapi import HTTPException

from .audit import logger
from .config import get_config


BLOCKED_LOGIN_SHELLS = {
    "",
    "/bin/false",
    "/usr/bin/false",
    "/sbin/nologin",
    "/usr/sbin/nologin",
}


def normalize_username(username: str) -> str:
    return username.strip()


def system_user(username: str) -> pwd.struct_passwd:
    username = normalize_username(username)
    try:
        return pwd.getpwnam(username)
    except KeyError as exc:
        raise HTTPException(401, "Unknown local user") from exc


def assert_login_allowed(username: str) -> pwd.struct_passwd:
    username = normalize_username(username)
    if not username or "/" in username or "\x00" in username:
        raise HTTPException(400, "Invalid username")
    user = system_user(username)
    cfg = get_config()
    # UID 0 is an explicit identity/RBAC break-glass administrator. PAM and
    # the interactive-shell checks below still apply; all other service UIDs
    # remain blocked by the configured threshold.
    if user.pw_uid < cfg.security.system_uid_threshold and user.pw_uid != 0:
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
    cfg = get_config()
    service = cfg.auth.pam_service
    if not Path(f"/etc/pam.d/{service}").exists():
        logger.warning("pam_service_missing service=%s fallback=login", service)
        service = "login"
    authenticator = pam.pam()
    if not authenticator.authenticate(username, password, service=service):
        reason = getattr(authenticator, "reason", "")
        logger.warning("pam_auth_failed user=%s service=%s reason=%s", username, service, reason or "unknown")
        raise HTTPException(401, "Invalid username or password")


def user_home(username: str) -> str:
    try:
        return system_user(username).pw_dir
    except HTTPException as error:
        if error.status_code != 401:
            raise
        # LDAP identities deliberately cannot collide with local Linux users.
        # Their application home is managed under the WebNAS data directory.
        from .ldap_auth import ldap_home

        home = ldap_home(username)
        if home:
            return home
        raise


def current_process_can_impersonate() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
