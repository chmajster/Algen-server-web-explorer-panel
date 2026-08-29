from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path

from fastapi import HTTPException, Request, Response

from .config import get_config
from .sqlite_utils import ClosingConnection


SESSION_CACHE_TTL_SECONDS = 2.0
SESSION_CACHE_MAX_ENTRIES = 512


@dataclass(frozen=True)
class SessionUser:
    username: str
    csrf_token: str


@dataclass(frozen=True)
class StoredSession:
    username: str
    csrf_token: str
    persistent: bool
    expires_at: float


class SessionStore:
    """Persistent, revocable sessions with a short, bounded, hash-keyed read cache."""

    def __init__(
        self,
        path: Path,
        token_pepper: str = "",
        *,
        cache_ttl_seconds: float = SESSION_CACHE_TTL_SECONDS,
        cache_max_entries: int = SESSION_CACHE_MAX_ENTRIES,
    ) -> None:
        self.path = path
        self._token_pepper = token_pepper.encode("utf-8")
        self._cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache_max_entries = max(0, int(cache_max_entries))
        self._cache: OrderedDict[str, tuple[StoredSession, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    persistent INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(username);
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _hash(self, token: str) -> str:
        return hmac.new(self._token_pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _cache_session(self, token_hash: str, session: StoredSession) -> None:
        if self._cache_ttl_seconds <= 0 or self._cache_max_entries <= 0:
            return
        self._cache.pop(token_hash, None)
        self._cache[token_hash] = (session, time.monotonic() + self._cache_ttl_seconds)
        while len(self._cache) > self._cache_max_entries:
            self._cache.popitem(last=False)

    def invalidate(self, token: str) -> None:
        """Drop one cached token after an out-of-band change to its persisted session."""
        token_hash = self._hash(token)
        with self._lock:
            self._cache.pop(token_hash, None)

    def create(self, token: str, username: str, csrf_token: str, *, persistent: bool, expires_at: float) -> None:
        now = time.time()
        token_hash = self._hash(token)
        session = StoredSession(username=username, csrf_token=csrf_token, persistent=persistent, expires_at=expires_at)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO auth_sessions(token_hash,username,csrf_token,persistent,created_at,expires_at) VALUES (?,?,?,?,?,?)",
                (token_hash, username, csrf_token, int(persistent), now, expires_at),
            )
            self._cache_session(token_hash, session)

    def resolve(self, token: str) -> StoredSession | None:
        token_hash = self._hash(token)
        now = time.time()
        with self._lock:
            cached = self._cache.get(token_hash)
            if cached is not None:
                session, cache_deadline = cached
                if session.expires_at <= now:
                    self._cache.pop(token_hash, None)
                    with self._connect() as connection:
                        connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
                    return None
                if cache_deadline > time.monotonic():
                    self._cache.move_to_end(token_hash)
                    return session
                self._cache.pop(token_hash, None)

            with self._connect() as connection:
                row = connection.execute(
                    "SELECT username,csrf_token,persistent,expires_at FROM auth_sessions WHERE token_hash=?",
                    (token_hash,),
                ).fetchone()
                if row and float(row["expires_at"]) <= now:
                    connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
                    return None
            if not row:
                return None
            session = StoredSession(
                username=str(row["username"]),
                csrf_token=str(row["csrf_token"]),
                persistent=bool(row["persistent"]),
                expires_at=float(row["expires_at"]),
            )
            self._cache_session(token_hash, session)
            return session

    def revoke(self, token: str) -> None:
        token_hash = self._hash(token)
        with self._lock, self._connect() as connection:
            self._cache.pop(token_hash, None)
            connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))

    def revoke_user(self, username: str) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            stale = [token_hash for token_hash, (session, _) in self._cache.items() if session.username == username]
            for token_hash in stale:
                self._cache.pop(token_hash, None)
            return max(0, int(cursor.rowcount))


class LoginRateLimiter:
    """Thread-safe sliding-window limiter that tracks authentication failures only."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _window(self, key: str, now: float) -> deque[float]:
        window = self._attempts[key]
        while window and window[0] < now - 60:
            window.popleft()
        return window

    def check(self, key: str) -> None:
        cfg = get_config()
        now = time.time()
        with self._lock:
            window = self._window(key, now)
            if len(window) >= cfg.security.rate_limit_login_per_minute:
                raise HTTPException(HTTPStatus.TOO_MANY_REQUESTS, "Too many login attempts")

    def record_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            self._window(key, now).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


rate_limiter = LoginRateLimiter()


@lru_cache
def _store(path: str, token_pepper: str) -> SessionStore:
    return SessionStore(Path(path), token_pepper)


def _session_store() -> SessionStore:
    cfg = get_config()
    return _store(str(Path(cfg.paths.data_dir) / "sessions.sqlite3"), cfg.security.session_secret)


def invalidate_user_sessions(username: str) -> int:
    return _session_store().revoke_user(username)


def create_session(response: Response, username: str, *, remember_me: bool = False) -> str:
    cfg = get_config()
    csrf_token = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(48)
    lifetime = (cfg.auth.remember_me_lifetime_days * 24 * 60 * 60) if remember_me else (cfg.auth.session_lifetime_hours * 60 * 60)
    _session_store().create(token, username, csrf_token, persistent=remember_me, expires_at=time.time() + lifetime)
    response.set_cookie(
        cfg.auth.session_cookie_name,
        token,
        httponly=True,
        # Use the configured transport policy for both browser-session and
        # persistent cookies. Forcing Secure only for remembered sessions
        # makes them unusable on the default HTTP installation.
        secure=cfg.security.cookie_secure,
        samesite="strict",
        max_age=lifetime if remember_me else None,
        path="/",
    )
    return csrf_token


def clear_session(response: Response, request: Request | None = None) -> None:
    cfg = get_config()
    if request is not None:
        raw = request.cookies.get(cfg.auth.session_cookie_name)
        if raw:
            _session_store().revoke(raw)
    response.delete_cookie(
        cfg.auth.session_cookie_name,
        path="/",
        secure=cfg.security.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def get_session_user(request: Request) -> SessionUser:
    cfg = get_config()
    raw = request.cookies.get(cfg.auth.session_cookie_name)
    if not raw:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Authentication required")
    session = _session_store().resolve(raw)
    if session is None:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Invalid or expired session")
    return SessionUser(username=session.username, csrf_token=session.csrf_token)


def require_csrf(request: Request, user: SessionUser) -> None:
    token = request.headers.get("x-csrf-token")
    if token and secrets.compare_digest(token, user.csrf_token):
        return

    reason_code = "missing_header" if not token else "token_mismatch"
    reason = (
        "The X-CSRF-Token header is missing."
        if not token
        else "The submitted CSRF token does not match the current authenticated session."
    )
    raise HTTPException(
        HTTPStatus.FORBIDDEN,
        detail={
            "code": "INVALID_CSRF_TOKEN",
            "message": "Invalid CSRF token",
            "reason_code": reason_code,
            "reason": reason,
            "hint": "Refresh the page and retry the operation. If the problem persists, sign out and sign in again.",
            "recovery": "refresh_or_reauthenticate",
            "endpoint": request.url.path,
            "request_method": request.method,
            "expected_header": "X-CSRF-Token",
            "csrf_header_present": bool(token),
            "session_valid": True,
        },
    )
