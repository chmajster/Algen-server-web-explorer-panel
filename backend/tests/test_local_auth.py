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


def test_local_database_is_default_and_bootstraps_random_admin(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    assert store.auth_mode() == "local"
    users = store.users()
    assert len(users) == 1
    assert users[0]["username"] == "admin"
    assert users[0]["role"] == "admin"
    assert users[0]["enabled"] is True
    assert users[0]["posix_mapped"] is True
    assert store.bootstrap_path.exists()
    assert store.bootstrap_path.stat().st_mode & 0o777 == 0o600

    private = store._private_user("admin")
    assert private is not None
    password_hash = str(private["password_hash"])
    assert password_hash.startswith("scrypt$")
    assert "Password:" not in password_hash


def test_bootstrap_password_authenticates_and_file_is_consumed(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    content = store.bootstrap_path.read_text(encoding="utf-8")
    password = next(line.split(": ", 1)[1] for line in content.splitlines() if line.startswith("Password: "))

    user = store.authenticate("admin", password)

    assert user["username"] == "admin"
    assert user["home"] == "/home/admin"
    assert not store.bootstrap_path.exists()


def test_wrong_local_password_is_rejected(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    with pytest.raises(local_auth.LocalInvalidCredentials):
        store.authenticate("admin", "definitely-wrong-password")
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
    with pytest.raises(ValueError):
        store.update_user("admin", role="user")
    with pytest.raises(ValueError):
        store.update_user("admin", enabled=False)
    with pytest.raises(ValueError):
        store.delete_user("admin")

    store.create_user("second-admin", "another correct battery password", role="admin")
    updated = store.update_user("admin", role="user")
    assert updated["role"] == "user"


def test_switch_to_local_requires_enabled_local_admin(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    store.set_auth_mode("system", "admin")
    assert store.auth_mode() == "system"
    with store.connect() as connection:
        connection.execute("UPDATE local_users SET enabled=0 WHERE role='admin'")
    with pytest.raises(ValueError):
        store.set_auth_mode("local", "system-admin")


def test_local_login_requires_posix_mapping_after_valid_password(monkeypatch, tmp_path):
    store = repo(monkeypatch, tmp_path)
    content = store.bootstrap_path.read_text(encoding="utf-8")
    password = next(line.split(": ", 1)[1] for line in content.splitlines() if line.startswith("Password: "))
    monkeypatch.setattr(local_auth, "_ensure_posix_mapping", lambda username: None)
    with pytest.raises(local_auth.LocalAuthConfigurationError):
        store.authenticate("admin", password)


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
