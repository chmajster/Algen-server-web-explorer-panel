from __future__ import annotations

import asyncio

from fastapi import Request, Response

from app import password_session_policy as policy
from app.security import SessionUser


def _request(method: str = "POST", path: str = "/api/settings/change-password") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )


def test_successful_self_service_password_change_revokes_pam_sessions(monkeypatch):
    revoked: list[str] = []
    monkeypatch.setattr(policy, "get_session_user", lambda _request: SessionUser("alice", "csrf"))
    monkeypatch.setattr(policy, "invalidate_user_sessions", revoked.append)

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(policy.password_change_session_policy(_request(), call_next))

    assert response.status_code == 200
    assert revoked == ["alice"]


def test_failed_password_change_does_not_revoke_sessions(monkeypatch):
    revoked: list[str] = []
    monkeypatch.setattr(policy, "get_session_user", lambda _request: SessionUser("alice", "csrf"))
    monkeypatch.setattr(policy, "invalidate_user_sessions", revoked.append)

    async def call_next(_request: Request) -> Response:
        return Response(status_code=400)

    asyncio.run(policy.password_change_session_policy(_request(), call_next))

    assert revoked == []
