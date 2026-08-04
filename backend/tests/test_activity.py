from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from app import activity_api, auth_api
from app.activity import ActivityCategory, ActivityRepository, ActivityStatus


def test_activity_repository_persists_filters_summarizes_and_redacts(tmp_path: Path):
    path = tmp_path / "activity.sqlite3"
    repository = ActivityRepository(path)
    repository.add(
        actor="alice",
        category=ActivityCategory.login,
        action="login",
        details={"client": "192.0.2.10", "password": "never-store-this"},
        created_at=100,
    )
    repository.add(
        actor="bob",
        category=ActivityCategory.module,
        action="password=never-store-this",
        target="https://service:never-store-this@example.test/api",
        status=ActivityStatus.failure,
        summary="token=never-store-this",
        details={"nested": {"authorization": "Bearer never-store-this"}},
        created_at=200,
    )

    reloaded = ActivityRepository(path)
    items, total = reloaded.list(category=ActivityCategory.module, status=ActivityStatus.failure, search="bob")

    assert total == 1
    assert items[0].actor == "bob"
    assert items[0].details["nested"]["authorization"] == "[REDACTED]"
    assert "never-store-this" not in json.dumps(items[0].model_dump(), ensure_ascii=False)
    summary = reloaded.summary()
    assert summary["total"] == 2
    assert summary["categories"]["login"] == 1
    assert summary["categories"]["module"] == 1
    assert summary["statuses"]["failure"] == 1


def test_activity_api_limits_regular_users_to_their_own_events(monkeypatch, tmp_path: Path):
    repository = ActivityRepository(tmp_path / "activity.sqlite3")
    repository.add(actor="alice", category=ActivityCategory.file, action="mkdir")
    repository.add(actor="bob", category=ActivityCategory.administration, action="restart_system")
    monkeypatch.setattr(activity_api, "repository", lambda: repository)
    monkeypatch.setattr(activity_api, "has_permission", lambda username, permission: False)

    response = activity_api.activity_events(
        category=None,
        status=None,
        actor="bob",
        search="",
        since=None,
        until=None,
        page=1,
        page_size=50,
        user=SimpleNamespace(username="alice"),
    )
    summary = activity_api.activity_summary(SimpleNamespace(username="alice"))

    assert response["scope"] == "own"
    assert response["total"] == 1
    assert response["items"][0]["actor"] == "alice"
    assert summary["total"] == 1


def test_activity_api_grants_global_filtering_only_with_audit_permission(monkeypatch, tmp_path: Path):
    repository = ActivityRepository(tmp_path / "activity.sqlite3")
    repository.add(actor="alice", category=ActivityCategory.file, action="mkdir")
    repository.add(actor="bob", category=ActivityCategory.module, action="restart")
    monkeypatch.setattr(activity_api, "repository", lambda: repository)
    monkeypatch.setattr(activity_api, "has_permission", lambda username, permission: permission == "audit.view")

    response = activity_api.activity_events(
        category=ActivityCategory.module,
        status=None,
        actor="bob",
        search="restart",
        since=None,
        until=None,
        page=1,
        page_size=50,
        user=SimpleNamespace(username="auditor"),
    )

    assert response["scope"] == "global"
    assert response["total"] == 1
    assert response["items"][0]["actor"] == "bob"
    assert response["items"][0]["category"] == "module"


def test_failed_pam_login_records_metadata_without_the_password(monkeypatch):
    captured: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(auth_api.rate_limiter, "check", lambda key: None)
    monkeypatch.setattr(auth_api, "authenticate", lambda username, password: (_ for _ in ()).throw(HTTPException(401, "Invalid username or password")))
    monkeypatch.setattr(auth_api, "record_activity", lambda *args, **kwargs: captured.append((args, kwargs)))
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/login", "headers": [], "client": ("192.0.2.15", 12345)})

    with pytest.raises(HTTPException):
        auth_api.login(auth_api.LoginRequest(username="alice", password="do-not-store"), request, Response())

    assert captured[0][0][:3] == (ActivityCategory.login, "login", "alice")
    assert captured[0][1]["status"] == ActivityStatus.failure
    assert captured[0][1]["details"] == {"client": "192.0.2.15", "status_code": 401}
    assert "do-not-store" not in repr(captured)
