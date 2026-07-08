from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import get_config


@dataclass(frozen=True)
class SessionUser:
    username: str
    csrf_token: str


class LoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        cfg = get_config()
        now = time.time()
        window = self._attempts[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= cfg.security.rate_limit_login_per_minute:
            raise HTTPException(HTTPStatus.TOO_MANY_REQUESTS, "Too many login attempts")
        window.append(now)


rate_limiter = LoginRateLimiter()


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().security.session_secret, salt="webnas-session")


def create_session(response: Response, username: str) -> str:
    cfg = get_config()
    csrf_token = secrets.token_urlsafe(32)
    value = _serializer().dumps({"username": username, "csrf": csrf_token})
    response.set_cookie(
        cfg.auth.session_cookie_name,
        value,
        httponly=True,
        secure=cfg.security.cookie_secure,
        samesite="strict",
        max_age=60 * 60 * 12,
        path="/",
    )
    return csrf_token


def clear_session(response: Response) -> None:
    response.delete_cookie(get_config().auth.session_cookie_name, path="/")


def get_session_user(request: Request) -> SessionUser:
    cfg = get_config()
    raw = request.cookies.get(cfg.auth.session_cookie_name)
    if not raw:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Authentication required")
    try:
        data = _serializer().loads(raw, max_age=60 * 60 * 12)
    except BadSignature as exc:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid session") from exc
    return SessionUser(username=data["username"], csrf_token=data["csrf"])


def require_csrf(request: Request, user: SessionUser) -> None:
    token = request.headers.get("x-csrf-token")
    if not token or not secrets.compare_digest(token, user.csrf_token):
        raise HTTPException(HTTPStatus.FORBIDDEN, "Invalid CSRF token")
