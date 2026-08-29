from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from app import startup_bootstrap
from app.security import SessionUser


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


@pytest.mark.parametrize("transfer_permission", ["transfers.view_all", "transfers.view_own"])
def test_bootstrap_defers_all_transfer_history(monkeypatch, transfer_permission: str) -> None:
    monkeypatch.setattr(
        startup_bootstrap,
        "settings_me",
        lambda request, user: {
            "username": user.username,
            "home": f"/home/{user.username}",
            "permissions": [transfer_permission],
            "language": "en-US",
        },
    )
    # Keep a sentinel on the module so any future reintroduction of task-store
    # access fails this regression for both global and per-user history.
    monkeypatch.setattr(
        startup_bootstrap,
        "task_store",
        SimpleNamespace(
            list_all=_unexpected("global transfer history must not block bootstrap"),
            list_for=_unexpected("per-user transfer history must not block bootstrap"),
        ),
        raising=False,
    )
    monkeypatch.setattr(startup_bootstrap, "admin_updates_progress", _unexpected("detailed update endpoint used"))
    monkeypatch.setattr(startup_bootstrap, "system_update_status", lambda user: {"state": "idle", "detailed": False})

    payload = startup_bootstrap.build_startup_payload(_request(), SessionUser("alice", "csrf"))

    assert payload["user"] == {"username": "alice", "home": "/home/alice", "csrf_token": "csrf"}
    assert payload["task_scope"] == "none"
    assert payload["tasks"] == []
    assert payload["update_detailed"] is False
    assert payload["update_progress"] == {"state": "idle", "detailed": False}
    assert "update_completion" not in payload


def test_bootstrap_keeps_detailed_update_state_but_not_transfer_history(monkeypatch) -> None:
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
    monkeypatch.setattr(startup_bootstrap, "admin_updates_progress", lambda user: {"state": "idle", "detailed": True})
    monkeypatch.setattr(startup_bootstrap, "system_update_status", _unexpected("public update endpoint used"))

    payload = startup_bootstrap.build_startup_payload(_request(), SessionUser("alice", "csrf"))

    assert payload["task_scope"] == "none"
    assert payload["tasks"] == []
    assert payload["update_detailed"] is True
    assert payload["update_progress"] == {"state": "idle", "detailed": True}
    assert "update_completion" not in payload


def test_bootstrap_response_is_never_cacheable(monkeypatch) -> None:
    monkeypatch.setattr(startup_bootstrap, "build_startup_payload", lambda request, user: {"ok": True})
    response = Response()

    assert startup_bootstrap.startup_bootstrap(_request(), response, SessionUser("alice", "csrf")) == {"ok": True}
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Cookie, Accept-Language"
