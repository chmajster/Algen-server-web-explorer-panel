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
LOCAL_PASSWD_PATH = Path("/etc/passwd")


def normalize_username(username: str) -> str:
    return username.strip()


def is_local_passwd_user(username: str, passwd_path: Path = LOCAL_PASSWD_PATH) -> bool:
    """Return True only for accounts defined in the host's local /etc/passwd.

    ``pwd.getpwnam`` resolves through NSS and can therefore also return LDAP,
    SSSD, winbind, or nslcd identities. The PAM provider is intentionally the
    local-account provider, so provider selection must not silently collapse
    an NSS-backed LDAP identity into PAM.
    """

    username = normalize_username(username)
    if not username or ":" in username or "\x00" in username:
        return False
    try:
        with passwd_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line or line.startswith("#"):
                    continue
                name, separator, _rest = line.partition(":")
                if separator and name == username:
                    return True
    except OSError:
        logger.error("local_passwd_unavailable path=%s", passwd_path)
    return False


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
    if not is_local_passwd_user(username):
        raise HTTPException(401, "Invalid username or password")

    # A remembered LDAP identity and a newly-created local account with the
    # same name must not become one WebNAS identity. Fail closed until the
    # collision is administratively resolved.
    try:
        from .ldap_auth import is_ldap_identity

        if is_ldap_identity(username):
            raise HTTPException(401, "Invalid username or password")
    except ImportError:
        pass

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
    return system_user(username).pw_dir


def current_process_can_impersonate() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
