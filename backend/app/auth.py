from __future__ import annotations

import os
import pwd
from pathlib import Path

import pam
from fastapi import HTTPException

from .audit import logger
from .config import get_config
from .privileged_broker.client import BrokerClient, BrokerError
from .privileged_broker.protocol import Operation
from .privileged_broker.runtime import broker_required


BLOCKED_LOGIN_SHELLS = {
    "",
    "/bin/false",
    "/usr/bin/false",
    "/sbin/nologin",
    "/usr/sbin/nologin",
}
LOCAL_PASSWD_PATH = Path("/etc/passwd")
WEBNAS_PAM_SERVICE = "webnas"
WEBNAS_PAM_PATH = Path("/etc/pam.d/webnas")


def normalize_username(username: str) -> str:
    return username.strip()


def is_local_passwd_user(username: str, passwd_path: Path = LOCAL_PASSWD_PATH) -> bool:
    """Return True only for accounts defined in the host's local /etc/passwd.

    ``pwd.getpwnam`` resolves through NSS and can therefore also return LDAP,
    SSSD, winbind, or nslcd identities. The PAM provider is intentionally the
    local-system namespace, so provider selection must not collapse an
    NSS-backed LDAP identity into PAM.
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

    # Provider namespace isolation: a remembered LDAP identity and a local
    # account with the same login must never become one WebNAS identity.
    try:
        from .ldap_authentication import is_ldap_identity

        if is_ldap_identity(username):
            raise HTTPException(401, "Invalid username or password")
    except ImportError:
        pass

    user = system_user(username)
    cfg = get_config()
    if user.pw_uid < cfg.security.system_uid_threshold and user.pw_uid != 0:
        raise HTTPException(403, "System service accounts cannot log in")
    if user.pw_shell in BLOCKED_LOGIN_SHELLS:
        raise HTTPException(403, "User shell does not allow login")
    if not user.pw_dir:
        raise HTTPException(403, "User has no home directory")
    return user


def _authenticate_with_broker(username: str, password: str) -> None:
    try:
        response = BrokerClient(timeout=30.0).request(
            Operation.PAM_AUTH,
            {"username": username, "password": password, "service": WEBNAS_PAM_SERVICE},
            actor="authentication",
        )
    except BrokerError as error:
        logger.error("pam_broker_unavailable user=%s error_code=%s", username, error.error_code)
        raise HTTPException(503, "PAM authentication service is unavailable") from error

    if response.ok:
        return
    if response.error_code == "PAM_INVALID_CREDENTIALS":
        logger.warning("pam_auth_failed user=%s service=%s", username, WEBNAS_PAM_SERVICE)
        raise HTTPException(401, "Invalid username or password")

    logger.error(
        "pam_broker_failed user=%s service=%s error_code=%s exit_code=%s",
        username,
        WEBNAS_PAM_SERVICE,
        response.error_code or "unknown",
        response.exit_code,
    )
    raise HTTPException(503, "PAM authentication service is unavailable")


def authenticate(username: str, password: str) -> None:
    assert_login_allowed(username)
    if not password:
        raise HTTPException(401, "Invalid username or password")
    cfg = get_config()
    service = str(cfg.auth.pam_service or "").strip()
    if service != WEBNAS_PAM_SERVICE:
        logger.error("pam_configuration_invalid configured_service=%s required_service=%s", service, WEBNAS_PAM_SERVICE)
        raise HTTPException(503, "PAM authentication is not configured for WebNAS")
    if not WEBNAS_PAM_PATH.is_file():
        logger.error("pam_service_missing service=%s path=%s", WEBNAS_PAM_SERVICE, WEBNAS_PAM_PATH)
        raise HTTPException(503, "PAM authentication is not configured for WebNAS")

    if broker_required():
        _authenticate_with_broker(username, password)
        return

    authenticator = pam.pam()
    if not authenticator.authenticate(username, password, service=WEBNAS_PAM_SERVICE):
        reason = getattr(authenticator, "reason", "")
        logger.warning(
            "pam_auth_failed user=%s service=%s reason=%s",
            username,
            WEBNAS_PAM_SERVICE,
            reason or "unknown",
        )
        raise HTTPException(401, "Invalid username or password")


def user_home(username: str) -> str:
    return system_user(username).pw_dir


def current_process_can_impersonate() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
