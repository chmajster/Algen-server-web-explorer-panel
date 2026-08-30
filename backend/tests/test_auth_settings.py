from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import auth_settings
from app.local_auth import LocalInvalidCredentials
from app.security import SessionUser


class FakeStore:
    def __init__(self):
        self.mode = "local"
        self.authenticated: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str | None]] = []

    def auth_mode(self):
        return self.mode

    def set_auth_mode(self, mode, actor):
        self.mode = mode
        return mode

    def users(self):
        return [{"username": "admin", "role": "admin", "enabled": True}]

    def enabled_admin_count(self):
        return 1

    def authenticate(self, username, password):
        self.authenticated.append((username, password))
        if password != "correct-current-password":
            raise LocalInvalidCredentials()
        return {"username": username}

    def update_user(self, username, *, role=None, enabled=None, display_name=None, password=None):
        self.updated.append((username, password))
        return {"username": username, "role": "admin", "enabled": True}


def local_session() -> SessionUser:
    return SessionUser(username="admin", csrf_token="csrf", auth_provider="local")


def test_authentication_mode_change_invalidates_all_sessions(monkeypatch):
    store = FakeStore()
    invalidations: list[bool] = []
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "invalidate_all_sessions", lambda: invalidations.append(True) or 3)
    monkeypatch.setattr(auth_settings, "record_activity", lambda *args, **kwargs: None)

    result = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="system"),
        user=local_session(),
    )

    assert store.mode == "system"
    assert invalidations == [True]
    assert result["reauthentication_required"] is True
    assert result["mode"] == "system"


def test_no_session_invalidation_when_mode_is_unchanged(monkeypatch):
    store = FakeStore()
    invalidations: list[bool] = []
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "invalidate_all_sessions", lambda: invalidations.append(True) or 0)

    result = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="local"),
        user=local_session(),
    )

    assert invalidations == []
    assert result["reauthentication_required"] is False


def test_local_user_changes_own_password_after_current_password_verification(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "record_activity", lambda *args, **kwargs: None)

    result = auth_settings.change_local_password(
        auth_settings.LocalPasswordChange(
            current_password="correct-current-password",
            new_password="a-new-local-password-123",
        ),
        user=local_session(),
    )

    assert result == {"ok": True}
    assert store.authenticated == [("admin", "correct-current-password")]
    assert store.updated == [("admin", "a-new-local-password-123")]


def test_local_user_password_change_rejects_wrong_current_password(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)

    with pytest.raises(HTTPException) as error:
        auth_settings.change_local_password(
            auth_settings.LocalPasswordChange(
                current_password="wrong-current-password",
                new_password="a-new-local-password-123",
            ),
            user=local_session(),
        )

    assert error.value.status_code == 401
    assert store.updated == []


def test_local_password_dependency_rejects_non_local_session(monkeypatch):
    monkeypatch.setattr(
        auth_settings,
        "get_session_user",
        lambda request: SessionUser(username="root", csrf_token="csrf", auth_provider="pam"),
    )
    monkeypatch.setattr(auth_settings, "require_csrf", lambda request, user: None)
    request = SimpleNamespace()

    with pytest.raises(HTTPException) as error:
        auth_settings.local_write(request)

    assert error.value.status_code == 409
