from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pam

from .protocol import BrokerRequest, BrokerResponse, Operation


logger = logging.getLogger("webnas.privileged_broker.authentication")
WEBNAS_PAM_SERVICE = "webnas"
WEBNAS_PAM_PATH = Path("/etc/pam.d/webnas")
MAX_USERNAME_LENGTH = 256
MAX_PASSWORD_LENGTH = 8192


def _response(
    request: BrokerRequest,
    *,
    ok: bool,
    exit_code: int = 0,
    error_code: str | None = None,
    stderr: str = "",
) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=ok,
        exit_code=exit_code,
        error_code=error_code,
        stderr=stderr,
    )


def _validate_payload(payload: dict[str, Any]) -> tuple[str, str]:
    if set(payload) != {"username", "password", "service"}:
        raise ValueError("unsupported PAM authentication parameters")

    username = payload.get("username")
    password = payload.get("password")
    service = payload.get("service")

    if (
        not isinstance(username, str)
        or not username
        or len(username) > MAX_USERNAME_LENGTH
        or any(character in username for character in ("\x00", ":", "/", "\\", "\n", "\r"))
    ):
        raise ValueError("invalid PAM username")
    if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_LENGTH or "\x00" in password:
        raise ValueError("invalid PAM password")
    if service != WEBNAS_PAM_SERVICE:
        raise ValueError("unsupported PAM service")
    return username, password


def dispatch(request: BrokerRequest) -> BrokerResponse:
    if request.operation != Operation.PAM_AUTH:
        return _response(
            request,
            ok=False,
            exit_code=126,
            error_code="POLICY_DENIED",
            stderr="unsupported authentication operation",
        )

    try:
        username, password = _validate_payload(request.payload)
    except ValueError as error:
        return _response(
            request,
            ok=False,
            exit_code=126,
            error_code="POLICY_DENIED",
            stderr=str(error),
        )

    if not WEBNAS_PAM_PATH.is_file():
        logger.error("pam_service_missing service=%s path=%s", WEBNAS_PAM_SERVICE, WEBNAS_PAM_PATH)
        return _response(
            request,
            ok=False,
            exit_code=127,
            error_code="PAM_UNAVAILABLE",
            stderr="PAM authentication is not configured for WebNAS",
        )

    try:
        authenticator = pam.pam()
        authenticated = bool(authenticator.authenticate(username, password, service=WEBNAS_PAM_SERVICE))
    except Exception as error:  # noqa: BLE001 - the privileged boundary must fail closed.
        logger.error("pam_auth_error user=%s service=%s error=%s", username, WEBNAS_PAM_SERVICE, type(error).__name__)
        return _response(
            request,
            ok=False,
            exit_code=127,
            error_code="PAM_UNAVAILABLE",
            stderr="PAM authentication service is unavailable",
        )

    if not authenticated:
        reason = str(getattr(authenticator, "reason", "") or "unknown")
        logger.warning("pam_auth_failed user=%s service=%s reason=%s", username, WEBNAS_PAM_SERVICE, reason)
        return _response(
            request,
            ok=False,
            exit_code=1,
            error_code="PAM_INVALID_CREDENTIALS",
            stderr="Invalid username or password",
        )

    return _response(request, ok=True)
