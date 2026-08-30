from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import local_auth
from app.identity.permissions import Permission

identity_service = importlib.import_module("app.identity.service")


class FakeSecretsService:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counter = 0

    def save(self, payload: Any, actor: str, secret_id: str | None = None) -> dict[str, Any]:
        self.counter += 1
        selected = secret_id or f"bootstrap-{self.counter}"
        self.values[selected] = str(payload.secret)
        return {"id": selected}

    def verified_secret(self, secret_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
        if secret_id not in self.values:
            raise KeyError(secret_id)
        assert module_id == local_auth.LOCAL_BOOTSTRAP_SECRET_MODULE
        assert purpose == "initial-local-admin"
        return {"id": secret_id, "secret": self.values[secret_id]}

    def delete(self, secret_id: str, actor: str) -> bool:
        return self.values.pop(secret_id, None) is not None


def config(tmp_path: Path):
    return SimpleNamespace(
        paths=SimpleNamespace(data_dir=str(tmp_path)),
        security=SimpleNamespace(system_uid_threshold=1000),
    )


def repo(monkeypatch, tmp_path: Path) -> tuple[local_auth.LocalAuthRepository, FakeSecretsService]:
    fake_secrets = FakeSecretsService()
    monkeypatch.setattr(local_auth, "get_config", lambda: config(tmp_path))
    monkeypatch.setattr(local_auth, "secrets_service", lambda: fake_secrets)
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
    return local_auth.LocalAuthRepository(tmp_path / "local-auth.sqlite3"), fake_secrets


def test_local_database_is_default_and_bootstraps_random_admin(monkeypatch, tmp_path):
    store, fake_secrets = repo(monkeypatch, tmp_path)
    assert store.auth_mode() == "local"
    users = store.users()
    assert len(users) == 1
    assert users[0]["username"] == "admin"
    assert users[0]["role"] == "admin"
    assert users[0]["enabled"] is True
    assert users[0]["posix_mapped"] is True

    secret_id = store._bootstrap_secret_id()
    assert secret_id
    assert secret_id in fake_secrets.values
    bootstrap_password = fake_secrets.values[secret_id]
    assert len(bootstrap_password) >= 24

    private = store._private_user("admin")
    assert private is not None
    password_hash = str(private["password_hash"])
    assert password_hash.startswith("scrypt$")
    assert bootstrap_password not in password_hash
    assert bootstrap_password.encode() not in store.path.read_bytes()


def test_bootstrap_password_authenticates_and_encrypted_secret_is_consumed(monkeypatch, tmp_path):
    store, fake_secrets = repo(monkeypatch, tmp_path)
    secret_id = store._bootstrap_secret_id()
    credentials = store.consume_bootstrap_credential()

    assert credentials is not None
    assert credentials["username"] == "admin"
    assert secret_id not in fake_secrets.values
    assert store._bootstrap_secret_id() == ""

    user = store.authenticate("admin", credentials["password"])

    assert user["username"] == "admin"
    assert user["home"] == "/home/admin"


def test_wrong_local_password_is_rejected(monkeypatch, tmp_path):
    store, _ = repo(monkeypatch, tmp_path)
    with pytest.raises(local_auth.LocalInvalidCredentials):
        store.authenticate("admin", "definitely-wrong-password")
    with pytest.raises(local_auth.LocalInvalidCredentials):
        store.authenticate("missing", "definitely-wrong-password")


def test_local_password_hash_uses_random_salt(monkeypatch, tmp_path):
    store, _ = repo(monkeypatch, tmp_path)
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
    store, _ = repo(monkeypatch, tmp_path)
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
    store, _ = repo(monkeypatch, tmp_path)
    store.set_auth_mode("system", "admin")
    assert store.auth_mode() == "system"
    with store.connect() as connection:
        connection.execute("UPDATE local_users SET enabled=0 WHERE role='admin'")
    with pytest.raises(ValueError):
        store.set_auth_mode("local", "system-admin")


def test_system_mode_does_not_create_local_bootstrap_admin(monkeypatch, tmp_path):
    fake_secrets = FakeSecretsService()
    monkeypatch.setattr(local_auth, "get_config", lambda: config(tmp_path))
    monkeypatch.setattr(local_auth, "secrets_service", lambda: fake_secrets)
    path = tmp_path / "local-auth.sqlite3"
    seed = local_auth.LocalAuthRepository.__new__(local_auth.LocalAuthRepository)
    seed.path = path
    seed.homes_root = tmp_path / "local-homes"
    import threading

    seed._lock = threading.RLock()
    seed._initialize()
    seed.set_auth_mode("system", "test")

    store = local_auth.LocalAuthRepository(path)

    assert store.auth_mode() == "system"
    assert store.count() == 0
    assert store._bootstrap_secret_id() == ""
    assert fake_secrets.values == {}


def test_local_login_requires_posix_mapping_after_valid_password(monkeypatch, tmp_path):
    store, _ = repo(monkeypatch, tmp_path)
    credentials = store.consume_bootstrap_credential()
    assert credentials is not None
    monkeypatch.setattr(local_auth, "_ensure_posix_mapping", lambda username: None)
    with pytest.raises(local_auth.LocalAuthConfigurationError):
        store.authenticate("admin", credentials["password"])


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
