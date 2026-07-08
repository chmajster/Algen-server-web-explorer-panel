from fastapi import HTTPException, Request, Response

from app import security


def make_request(cookie: str = "", csrf: str | None = None) -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode("latin-1")))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def test_session_cookie_roundtrip():
    response = Response()

    csrf = security.create_session(response, "alice")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    user = security.get_session_user(make_request(cookie))

    assert user.username == "alice"
    assert user.csrf_token == csrf


def test_require_csrf_rejects_missing_token():
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
