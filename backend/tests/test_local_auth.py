from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import local_auth
from app.identity.permissions import Permission

identity_service = importlib.import_module("app.identity.service")


def config(tmp_path: Path):
    return SimpleNamespace(
        paths=SimpleNamespace(data_dir=str(tmp_path)),
        security=SimpleNamespace(system_uid_threshold=1000),
    )


def repo(monkeypatch, tmp_path: Path) -> local_auth.LocalAuthRepository:
    monkeypatch.setattr(local_auth, "get_config", lambda: config(tmp_path))
    monkeypatch.setattr(
        local_auth,
        "_ensure_posix_mapping",
        lambda username: {"uid": 12000, "gid": 12000, "home": f"/home/{username}"},
    )
    monkeypatch.setattr(
        local_auth,
        "_posix_mapping",
        lambda username: {"uid": 12000, "gid": 12000, "home": f"/home/{username}"},
    )
    return local_auth.LocalAuthRepository(tmp_path / "local-auth.sqlite3")


def test_local_database_is_default_and_installer_bootstrap_creates_chris(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    assert store.auth_mode() == "local"
    assert store.count() == 0

    user, password = store.bootstrap_admin("chris", "1")

    assert user is not None
    assert user["username"] == "chris"
    assert user["role"] == "admin"
    assert user["enabled"] is True
    assert user["posix_mapped"] is True
    assert password == "1"
    private = store._private_user("chris")
    assert private is not None
    password_hash = str(private["password_hash"])
    assert password_hash.startswith("scrypt$")
    assert password_hash != "1"
    assert local_auth.verify_password("1", password_hash)


def test_bootstrap_admin_only_works_on_empty_database(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    first, _ = store.bootstrap_admin("chris", "1")
    second, password = store.bootstrap_admin("other", "1")
    assert first is not None
    assert second is None
    assert password == ""


def test_wrong_local_password_is_rejected(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    store.bootstrap_admin("chris", "1")
    with pytest.raises(local_auth.LocalInvalidCredentials):
        store.authenticate("chris", "definitely-wrong-password")
    with pytest.raises(local_auth.LocalInvalidCredentials):
        store.authenticate("missing", "definitely-wrong-password")


def test_local_password_hash_uses_random_salt(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    first = store.create_user("alice", "correct horse battery staple", role="user")
    assert first["username"] == "alice"
    first_private = store._private_user("alice")
    assert first_private is not None
    first_hash = str(first_private["password_hash"])
    store.update_user("alice", password="correct horse battery staple")
    second_private = store._private_user("alice")
    assert second_private is not None
    second_hash = str(second_private["password_hash"])
    assert first_hash != second_hash
    assert local_auth.verify_password("correct horse battery staple", second_hash)


def test_last_enabled_local_admin_cannot_be_removed_or_downgraded(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    store.bootstrap_admin("chris", "1")
    with pytest.raises(ValueError):
        store.update_user("chris", role="user")
    with pytest.raises(ValueError):
        store.update_user("chris", enabled=False)
    with pytest.raises(ValueError):
        store.delete_user("chris")

    store.create_user("second-admin", "another correct battery password", role="admin")
    updated = store.update_user("chris", role="user")
    assert updated["role"] == "user"


def test_switch_to_local_requires_enabled_local_admin(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    store.bootstrap_admin("chris", "1")
    store.set_auth_mode("system", "chris")
    assert store.auth_mode() == "system"
    with store.connect() as connection:
        connection.execute("UPDATE local_users SET enabled=0 WHERE role='admin'")
    with pytest.raises(ValueError):
        store.set_auth_mode("local", "system-admin")


def test_active_auth_mode_is_frozen_until_startup_reload(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    store.bootstrap_admin("chris", "1")
    monkeypatch.setattr(local_auth, "repository", lambda: store)

    assert local_auth.initialize_active_auth_mode() == "local"
    assert local_auth.auth_mode() == "local"

    store.set_auth_mode("system", "chris")

    assert local_auth.configured_auth_mode() == "system"
    assert local_auth.auth_mode() == "local"
    assert local_auth.authenticate_local("chris", "1")["username"] == "chris"

    assert local_auth.initialize_active_auth_mode() == "system"
    assert local_auth.auth_mode() == "system"
    assert local_auth.configured_auth_mode() == "system"

    with pytest.raises(local_auth.LocalAuthConfigurationError):
        local_auth.authenticate_local("chris", "1")

    store.set_auth_mode("local", "chris")
    local_auth.initialize_active_auth_mode()


def test_system_mode_does_not_create_local_bootstrap_admin(monkeypatch, tmp_path):
    monkeypatch.setattr(local_auth, "get_config", lambda: config(tmp_path))
    path = tmp_path / "local-auth.sqlite3"
    seed = local_auth.LocalAuthRepository(path)
    seed.set_auth_mode("system", "test")

    store = local_auth.LocalAuthRepository(path)

    assert store.auth_mode() == "system"
    assert store.count() == 0


def test_local_login_requires_posix_mapping_after_valid_password(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    store.bootstrap_admin("chris", "1")
    monkeypatch.setattr(local_auth, "_ensure_posix_mapping", lambda username: None)
    with pytest.raises(local_auth.LocalAuthConfigurationError):
        store.authenticate("chris", "1")


def test_local_profile_uses_database_role_not_linux_admin(monkeypatch):
    monkeypatch.setattr(local_auth, "auth_mode", lambda: "local")
    monkeypatch.setattr(
        local_auth,
        "local_user",
        lambda username: {
            "username": username,
            "role": "admin",
            "enabled": True,
            "home": "/home/admin",
        },
    )
    monkeypatch.setattr(local_auth, "local_posix_mapping", lambda username: None)
    monkeypatch.setattr(identity_service.linux_accounts, "is_linux_admin", lambda username: True)

    profile = identity_service._local_database_profile("admin")

    assert profile is not None
    assert profile["role"] == "admin"
    assert profile["linux_admin"] is False
    assert profile["is_admin"] is True
    assert Permission.ACCESS_MANAGE_ROLES.value in profile["permissions"]
    assert Permission.FILES_VIEW.value not in profile["permissions"]
    assert Permission.FILES_VIEW.value in profile["denied_permissions"]


def test_local_profile_keeps_file_permissions_with_safe_posix_mapping(monkeypatch):
    monkeypatch.setattr(local_auth, "auth_mode", lambda: "local")
    monkeypatch.setattr(
        local_auth,
        "local_user",
        lambda username: {
            "username": username,
            "role": "user",
            "enabled": True,
            "home": "/home/alice",
        },
    )
    monkeypatch.setattr(
        local_auth,
        "local_posix_mapping",
        lambda username: {"uid": 12000, "gid": 12000, "home": "/home/alice"},
    )

    profile = identity_service._local_database_profile("alice")

    assert profile is not None
    assert Permission.FILES_VIEW.value in profile["permissions"]
    assert profile["denied_permissions"] == []
