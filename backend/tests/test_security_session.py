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


def test_require_csrf_rejects_missing_token(session_store):
    response = Response()
    csrf = security.create_session(response, "alice")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    user = security.get_session_user(make_request(cookie))

    try:
        security.require_csrf(make_request(cookie), user)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("CSRF check should fail without token")

    security.require_csrf(make_request(cookie, csrf), user)
