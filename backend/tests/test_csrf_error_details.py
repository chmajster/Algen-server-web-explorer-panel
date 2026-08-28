import pytest
from fastapi import HTTPException, Request

from app.security import SessionUser, require_csrf


def make_request(csrf: str | None = None, *, path: str = "/api/settings", method: str = "PATCH") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if csrf is not None:
        headers.append((b"x-csrf-token", csrf.encode("latin-1")))
    return Request({"type": "http", "method": method, "path": path, "headers": headers})


@pytest.mark.parametrize(
    ("submitted_token", "reason_code", "header_present"),
    [
        (None, "missing_header", False),
        ("stale-token", "token_mismatch", True),
    ],
)
def test_require_csrf_returns_safe_structured_diagnostics(submitted_token, reason_code, header_present):
    user = SessionUser(username="alice", csrf_token="current-token")

    with pytest.raises(HTTPException) as error:
        require_csrf(make_request(submitted_token), user)

    assert error.value.status_code == 403
    detail = error.value.detail
    assert detail["code"] == "INVALID_CSRF_TOKEN"
    assert detail["message"] == "Invalid CSRF token"
    assert detail["reason_code"] == reason_code
    assert detail["recovery"] == "refresh_or_reauthenticate"
    assert detail["endpoint"] == "/api/settings"
    assert detail["request_method"] == "PATCH"
    assert detail["expected_header"] == "X-CSRF-Token"
    assert detail["csrf_header_present"] is header_present
    assert detail["session_valid"] is True
    assert "current-token" not in str(detail)
    assert "stale-token" not in str(detail)


def test_require_csrf_accepts_the_current_token():
    user = SessionUser(username="alice", csrf_token="current-token")

    require_csrf(make_request("current-token"), user)
