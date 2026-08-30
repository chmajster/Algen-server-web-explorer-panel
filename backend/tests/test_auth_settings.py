from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import auth_settings
from app.local_auth import LocalInvalidCredentials
from app.security import SessionUser


class FakeStore:
    def __init__(self, mode: str = "local"):
        self.mode = mode
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


def system_session() -> SessionUser:
    return SessionUser(username="root", csrf_token="csrf", auth_provider="pam")


def test_local_to_system_is_saved_as_pending_without_session_invalidation(monkeypatch):
    store = FakeStore("local")
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "auth_mode", lambda: "local")
    monkeypatch.setattr(auth_settings, "record_activity", lambda *args, **kwargs: None)

    result = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="system"),
        user=local_session(),
    )

    assert store.mode == "system"
    assert result["mode"] == "local"
    assert result["configured_mode"] == "system"
    assert result["restart_required"] is True
    assert result["reauthentication_required"] is False
    assert not hasattr(auth_settings, "invalidate_all_sessions")


def test_admin_session_remains_usable_after_pending_mode_change(monkeypatch):
    store = FakeStore("local")
    session = local_session()
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "auth_mode", lambda: "local")
    monkeypatch.setattr(auth_settings, "record_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_settings, "get_session_user", lambda request: session)
    monkeypatch.setattr(auth_settings, "require_csrf", lambda request, user: None)
    monkeypatch.setattr(auth_settings, "access_profile", lambda username: {"is_admin": True})

    auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="system"),
        user=session,
    )

    assert auth_settings.admin_read(SimpleNamespace()) is session


def test_pending_change_can_be_cancelled_before_restart(monkeypatch):
    store = FakeStore("local")
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "auth_mode", lambda: "local")
    monkeypatch.setattr(auth_settings, "record_activity", lambda *args, **kwargs: None)

    pending = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="system"),
        user=local_session(),
    )
    cancelled = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="local"),
        user=local_session(),
    )

    assert pending["restart_required"] is True
    assert cancelled["mode"] == "local"
    assert cancelled["configured_mode"] == "local"
    assert cancelled["restart_required"] is False
    assert cancelled["reauthentication_required"] is False


def test_system_to_local_is_pending_without_invalidating_current_session(monkeypatch):
    store = FakeStore("system")
    session = system_session()
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "auth_mode", lambda: "system")
    monkeypatch.setattr(auth_settings, "record_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_settings, "get_session_user", lambda request: session)
    monkeypatch.setattr(auth_settings, "require_csrf", lambda request, user: None)
    monkeypatch.setattr(auth_settings, "access_profile", lambda username: {"is_admin": True})

    result = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="local"),
        user=session,
    )

    assert result["mode"] == "system"
    assert result["configured_mode"] == "local"
    assert result["restart_required"] is True
    assert result["reauthentication_required"] is False
    assert auth_settings.admin_read(SimpleNamespace()) is session


def test_no_restart_required_when_configured_mode_matches_active_mode(monkeypatch):
    store = FakeStore("local")
    monkeypatch.setattr(auth_settings, "local_repository", lambda: store)
    monkeypatch.setattr(auth_settings, "auth_mode", lambda: "local")

    result = auth_settings.set_authentication_settings(
        auth_settings.AuthenticationModeUpdate(mode="local"),
        user=local_session(),
    )

    assert result["mode"] == "local"
    assert result["configured_mode"] == "local"
    assert result["restart_required"] is False
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
