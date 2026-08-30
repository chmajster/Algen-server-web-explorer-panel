import hashlib
import hmac
import sqlite3
import time

import pytest
from fastapi import HTTPException, Request, Response

from app import security


@pytest.fixture
def session_store(monkeypatch, tmp_path):
    store = security.SessionStore(tmp_path / "sessions.sqlite3", "test-session-secret")
    monkeypatch.setattr(security, "_session_store", lambda: store)
    return store


def make_request(cookie: str = "", csrf: str | None = None) -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode("latin-1")))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def test_session_cookie_roundtrip(session_store):
    response = Response()

    csrf = security.create_session(response, "alice")
    header = response.headers["set-cookie"]
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    user = security.get_session_user(make_request(cookie))

    assert user.username == "alice"
    assert user.csrf_token == csrf
    assert "HttpOnly" in header
    assert "SameSite=strict" in header
    assert "Max-Age" not in header
    assert "expires=" not in header.casefold()


def test_remembered_session_uses_a_long_lived_cookie_over_http(session_store, monkeypatch):
    cfg = security.get_config().model_copy(deep=True)
    cfg.security.cookie_secure = False
    monkeypatch.setattr(security, "get_config", lambda: cfg)
    response = Response()

    security.create_session(response, "alice", remember_me=True)

    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "; Secure" not in header
    assert "SameSite=strict" in header
    assert "Max-Age=2592000" in header


def test_remembered_session_respects_secure_cookie_configuration(session_store, monkeypatch):
    cfg = security.get_config().model_copy(deep=True)
    cfg.security.cookie_secure = True
    monkeypatch.setattr(security, "get_config", lambda: cfg)
    response = Response()

    security.create_session(response, "alice", remember_me=True)

    assert "; Secure" in response.headers["set-cookie"]


def test_store_keeps_only_a_hash_of_the_bearer_token(session_store):
    response = Response()
    security.create_session(response, "alice", remember_me=True)
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    token = cookie.split("=", 1)[1]

    with sqlite3.connect(session_store.path) as connection:
        stored_hash = connection.execute("SELECT token_hash FROM auth_sessions").fetchone()[0]

    assert stored_hash == hmac.new(b"test-session-secret", token.encode("utf-8"), hashlib.sha256).hexdigest()
    assert stored_hash != token


def test_session_store_reuses_recent_database_resolution(monkeypatch, tmp_path):
    store = security.SessionStore(tmp_path / "sessions.sqlite3", "test-session-secret", cache_ttl_seconds=60)
    store.create("token", "alice", "csrf", persistent=False, expires_at=time.time() + 60)
    store._cache.clear()
    original_connect = store._connect
    connect_count = 0

    def counted_connect():
        nonlocal connect_count
        connect_count += 1
        return original_connect()

    monkeypatch.setattr(store, "_connect", counted_connect)

    first = store.resolve("token")
    second = store.resolve("token")

    assert first == second
    assert first is not None
    assert first.username == "alice"
    assert connect_count == 1


def test_session_cache_is_bounded_and_evicts_oldest_entry(tmp_path):
    store = security.SessionStore(
        tmp_path / "sessions.sqlite3",
        "test-session-secret",
        cache_ttl_seconds=60,
        cache_max_entries=2,
    )
    for index in range(3):
        store.create(f"token-{index}", "alice", f"csrf-{index}", persistent=False, expires_at=time.time() + 60)

    assert len(store._cache) == 2
    assert store._hash("token-0") not in store._cache
    assert store._hash("token-1") in store._cache
    assert store._hash("token-2") in store._cache


def test_explicit_cache_invalidation_observes_persisted_session_changes(tmp_path):
    store = security.SessionStore(tmp_path / "sessions.sqlite3", "test-session-secret", cache_ttl_seconds=60)
    store.create("token", "alice", "csrf", persistent=False, expires_at=time.time() + 60)
    assert store.resolve("token") is not None

    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE auth_sessions SET expires_at=0 WHERE token_hash=?", (store._hash("token"),))
        connection.commit()

    store.invalidate("token")
    assert store.resolve("token") is None


def test_revoke_user_invalidates_database_and_cached_sessions(tmp_path):
    store = security.SessionStore(tmp_path / "sessions.sqlite3", "test-session-secret", cache_ttl_seconds=60)
    store.create("alice-1", "alice", "csrf-1", persistent=False, expires_at=time.time() + 60)
    store.create("alice-2", "alice", "csrf-2", persistent=True, expires_at=time.time() + 60)
    store.create("bob-1", "bob", "csrf-3", persistent=False, expires_at=time.time() + 60)

    assert store.revoke_user("alice") == 2
    assert store.resolve("alice-1") is None
    assert store.resolve("alice-2") is None
    assert store.resolve("bob-1") is not None
    assert all(session.username != "alice" for session, _ in store._cache.values())


def test_logout_revokes_the_current_token(session_store):
    login_response = Response()
    security.create_session(login_response, "alice", remember_me=True)
    cookie = login_response.headers["set-cookie"].split(";", 1)[0]
    request = make_request(cookie)

    logout_response = Response()
    security.clear_session(logout_response, request)

    with pytest.raises(HTTPException) as error:
        security.get_session_user(request)
    assert error.value.status_code == 401
    assert "Max-Age=0" in logout_response.headers["set-cookie"]


def test_expired_server_side_session_is_rejected(session_store):
    session_store.create("expired-token", "alice", "csrf", persistent=True, expires_at=time.time() - 1)

    with pytest.raises(HTTPException) as error:
        security.get_session_user(make_request("webnas_session=expired-token"))

    assert error.value.status_code == 401


@pytest.mark.parametrize("submitted_token", [None, "wrong-token"])
def test_require_csrf_rejects_missing_and_invalid_tokens(session_store, submitted_token):
    response = Response()
    csrf = security.create_session(response, "alice")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    user = security.get_session_user(make_request(cookie))

    with pytest.raises(HTTPException) as error:
        security.require_csrf(make_request(cookie, submitted_token), user)

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "INVALID_CSRF_TOKEN"
    assert error.value.detail["message"] == "Invalid CSRF token"
    assert error.value.detail["reason_code"] == ("missing_header" if submitted_token is None else "token_mismatch")
    assert error.value.detail["csrf_header_present"] is (submitted_token is not None)
    assert error.value.detail["session_valid"] is True

    security.require_csrf(make_request(cookie, csrf), user)


def test_login_rate_limiter_counts_only_recorded_failures(monkeypatch):
    cfg = security.get_config().model_copy(deep=True)
    cfg.security.rate_limit_login_per_minute = 2
    monkeypatch.setattr(security, "get_config", lambda: cfg)
    limiter = security.LoginRateLimiter()

    for _ in range(10):
        limiter.check("client:alice")

    limiter.record_failure("client:alice")
    limiter.check("client:alice")
    limiter.record_failure("client:alice")

    with pytest.raises(HTTPException) as error:
        limiter.check("client:alice")
    assert error.value.status_code == 429

    limiter.clear("client:alice")
    limiter.check("client:alice")


def test_session_store_migrates_pre_identity_schema(tmp_path):
    path = tmp_path / "legacy-sessions.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE auth_sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                csrf_token TEXT NOT NULL,
                persistent INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX idx_auth_sessions_expiry ON auth_sessions(expires_at);
            CREATE INDEX idx_auth_sessions_user ON auth_sessions(username);
            """
        )
    store = security.SessionStore(path, "pepper", cache_ttl_seconds=0)
    with store._connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(auth_sessions)").fetchall()}
        indexes = {row["name"] for row in connection.execute("PRAGMA index_list(auth_sessions)").fetchall()}
    assert {"auth_provider", "identity_id"} <= columns
    assert "idx_auth_sessions_identity" in indexes
