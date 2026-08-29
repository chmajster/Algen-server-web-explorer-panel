from __future__ import annotations

from types import SimpleNamespace

from fastapi import Request, Response

from app import startup_bootstrap
from app.security import SessionUser


class _Task:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def to_dict(self) -> dict[str, str]:
        return {"id": self.task_id}


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/bootstrap",
        "headers": [(b"accept-language", b"en-US")],
    })


def _unexpected(message: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(message)

    return fail


def test_bootstrap_defers_global_transfer_history_and_keeps_detailed_updates(monkeypatch) -> None:
    monkeypatch.setattr(
        startup_bootstrap,
        "settings_me",
        lambda request, user: {
            "username": user.username,
            "home": f"/home/{user.username}",
            "permissions": ["transfers.view_all", "updates.view"],
            "language": "en-US",
        },
    )
    monkeypatch.setattr(
        startup_bootstrap,
        "task_store",
        SimpleNamespace(
            list_all=_unexpected("global transfer history must not block bootstrap"),
            list_for=_unexpected("own tasks used for global transfer permission"),
        ),
    )
    monkeypatch.setattr(startup_bootstrap, "admin_updates_progress", lambda user: {"state": "idle", "detailed": True})
    monkeypatch.setattr(startup_bootstrap, "system_update_status", _unexpected("public update endpoint used"))
    payload = startup_bootstrap.build_startup_payload(_request(), SessionUser("alice", "csrf"))

    assert payload["user"] == {"username": "alice", "home": "/home/alice", "csrf_token": "csrf"}
    assert payload["task_scope"] == "none"
    assert payload["tasks"] == []
    assert payload["update_detailed"] is True
    assert payload["update_progress"] == {"state": "idle", "detailed": True}
    assert "update_completion" not in payload


def test_bootstrap_uses_own_tasks_and_public_update_state(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        startup_bootstrap,
        "settings_me",
        lambda request, user: {
            "username": user.username,
            "home": f"/home/{user.username}",
            "permissions": ["transfers.view_own"],
            "language": "en-US",
        },
    )
    monkeypatch.setattr(
        startup_bootstrap,
        "task_store",
        SimpleNamespace(
            list_all=_unexpected("global tasks used"),
            list_for=lambda username: (calls.append(username) or [_Task("own")]),
        ),
    )
    monkeypatch.setattr(startup_bootstrap, "admin_updates_progress", _unexpected("detailed update endpoint used"))
    monkeypatch.setattr(startup_bootstrap, "system_update_status", lambda user: {"state": "idle", "detailed": False})
    payload = startup_bootstrap.build_startup_payload(_request(), SessionUser("alice", "csrf"))

    assert payload["task_scope"] == "own"
    assert payload["tasks"] == [{"id": "own"}]
    assert payload["update_detailed"] is False
    assert payload["update_progress"] == {"state": "idle", "detailed": False}
    assert "update_completion" not in payload
    assert calls == ["alice"]


def test_bootstrap_response_is_never_cacheable(monkeypatch) -> None:
    monkeypatch.setattr(startup_bootstrap, "build_startup_payload", lambda request, user: {"ok": True})
    response = Response()

    assert startup_bootstrap.startup_bootstrap(_request(), response, SessionUser("alice", "csrf")) == {"ok": True}
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Cookie, Accept-Language"
