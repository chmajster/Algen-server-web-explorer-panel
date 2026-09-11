from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from .security import get_session_user, invalidate_user_sessions


async def password_change_session_policy(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Revoke PAM sessions after a successful self-service password change.

    The settings endpoint changes the system credential during request handling.
    Revocation is deliberately performed after the response has been produced so
    the request that changed the password can complete normally while every
    subsequent request must authenticate with the new credential.
    """
    response = await call_next(request)
    if (
        request.method == "POST"
        and request.url.path == "/api/settings/change-password"
        and 200 <= response.status_code < 300
    ):
        try:
            user = get_session_user(request)
        except Exception:  # noqa: BLE001 - endpoint already enforced authentication.
            return response
        invalidate_user_sessions(user.username)
    return response
