from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app import auth, auth_api
from app.ldap_authentication import connection as ldap_connection
from app.ldap_authentication import repository as ldap_repository_factory
from app.ldap_authentication.models import (
    LdapAccessPolicyInput,
    LdapAuthenticationSettingsInput,
    LdapGroupMappingInput,
    LdapServerInput,
)
from app.ldap_authentication.repository import LdapAuthenticationRepository
from app.ldap_authentication import service as ldap_service
from app.security import SessionStore


class FakeSecretsService:
    def __init__(self) -> None:
        self.value = ""
        self.secret_id = "auth-secret"

    def save(self, payload, actor, secret_id=None):
        if payload.secret:
            self.value = payload.secret
        return {"id": secret_id or self.secret_id}

    def delete(self, secret_id, actor):
        self.value = ""

    def verified_secret(self, secret_id, *, module_id, purpose):
        return {"secret": self.value}


def settings(**overrides) -> LdapAuthenticationSettingsInput:
    values = {
        "enabled": True,
        "directory_type": "openldap",
        "servers": [
            {"id": "dc1", "host": "dc01.example.test", "port": 636, "priority": 10},
            {"id": "dc2", "host": "dc02.example.test", "port": 636, "priority": 20},
        ],
        "security_mode": "ldaps",
        "verify_tls": True,
        "base_dn": "dc=example,dc=test",
        "user_search_base": "ou=People,dc=example,dc=test",
        "user_search_filter": "(uid={username})",
        "username_attribute": "uid",
        "immutable_id_attribute": "entryUUID",
        "bind_dn": "cn=webnas-auth,ou=Services,dc=example,dc=test",
        "bind_password": "test-secret",
        "group_search_base": "ou=Groups,dc=example,dc=test",
    }
    values.update(overrides)
    return LdapAuthenticationSettingsInput(**values)


def request_from(ip: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": [],
            "client": (ip, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_ldap_authentication_defaults_to_tls_verification():
    payload = LdapAuthenticationSettingsInput()
    assert payload.enabled is False
    assert payload.security_mode.value == "starttls"
    assert payload.verify_tls is True
    assert payload.failover_strategy.value == "priority"


def test_user_filter_requires_single_placeholder():
    with pytest.raises(ValueError):
        LdapAuthenticationSettingsInput(user_search_filter="(uid=static)")
    with pytest.raises(ValueError):
        LdapAuthenticationSettingsInput(user_search_filter="(|(uid={username})(mail={username}))")


@pytest.mark.parametrize(
    ("username", "escaped"),
    [
        ("*", r"\2a"),
        ("admin*", r"admin\2a"),
        (")(", r"\29\28"),
        ("foo)(uid=*)", r"foo\29\28uid=\2a\29"),
        ("\\", r"\5c"),
        ("\x00", r"\00"),
    ],
)
def test_rfc4515_filter_escaping(username: str, escaped: str):
    assert ldap_service.ldap_user_search_filter("(uid={username})", username) == f"(uid={escaped})"


def test_priority_failover_orders_enabled_servers():
    payload = settings(enabled=False, bind_password="")
    endpoints = ldap_connection.endpoints(payload.model_dump(mode="json"))
    assert [item.label for item in endpoints] == ["dc01.example.test:636", "dc02.example.test:636"]


def test_round_robin_never_changes_server_set():
    payload = settings(enabled=False, bind_password="", failover_strategy="round_robin")
    first = ldap_connection.endpoints(payload.model_dump(mode="json"))
    second = ldap_connection.endpoints(payload.model_dump(mode="json"))
    assert {item.label for item in first} == {"dc01.example.test:636", "dc02.example.test:636"}
    assert {item.label for item in second} == {"dc01.example.test:636", "dc02.example.test:636"}
    assert first[0].label != second[0].label


def test_auth_repository_never_returns_bind_password(monkeypatch, tmp_path: Path):
    fake = FakeSecretsService()
    monkeypatch.setattr("app.ldap_authentication.repository.secrets_service", lambda: fake)
    repo = LdapAuthenticationRepository(tmp_path / "ldap-auth.sqlite3")
    saved = repo.save(settings(), "admin")
    assert saved["bind_password_configured"] is True
    assert "bind_password" not in saved
    assert "bind_secret_id" not in saved
    assert repo.settings(include_secret_id=True)["bind_secret_id"] == "auth-secret"


def test_legacy_auth_settings_migrate_only_to_authentication(monkeypatch, tmp_path: Path):
    path = tmp_path / "ldap-auth.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE ldap_settings(
            id INTEGER PRIMARY KEY, enabled INTEGER, server TEXT, port INTEGER,
            security_mode TEXT, verify_tls INTEGER, connect_timeout REAL,
            operation_timeout REAL, base_dn TEXT, user_search_base TEXT,
            user_search_filter TEXT, username_attribute TEXT, bind_dn TEXT,
            bind_secret_id TEXT, display_name_attribute TEXT, email_attribute TEXT
        );
        INSERT INTO ldap_settings VALUES(
            1,1,'ldap-old.example.test',389,'starttls',1,5,10,
            'dc=example,dc=test','ou=People,dc=example,dc=test','(uid={username})',
            'uid','cn=legacy-bind,dc=example,dc=test','legacy-secret','cn','mail'
        );
        """
    )
    connection.commit()
    connection.close()
    repo = LdapAuthenticationRepository(path)
    migrated = repo.settings(include_secret_id=True)
    assert migrated["enabled"] is True
    assert migrated["servers"][0]["host"] == "ldap-old.example.test"
    assert migrated["bind_secret_id"] == "legacy-secret"
    assert not any(table[0].startswith("ldap_manager") for table in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())


def test_access_policy_deny_has_priority(tmp_path: Path):
    repo = LdapAuthenticationRepository(tmp_path / "ldap-auth.sqlite3")
    repo.save_mapping(
        LdapGroupMappingInput(group_dn="cn=WebNAS-Admins,ou=Groups,dc=example,dc=test", role="admin"),
        "admin",
    )
    repo.save_access_policy(
        LdapAccessPolicyInput(
            mode="mapped_groups",
            allow_groups=["cn=WebNAS-Admins,ou=Groups,dc=example,dc=test"],
            deny_groups=["cn=Disabled-WebNAS,ou=Groups,dc=example,dc=test"],
        ),
        "admin",
    )
    allowed, mappings = ldap_service._evaluate_access(
        repo,
        ["cn=WebNAS-Admins,ou=Groups,dc=example,dc=test"],
    )
    assert allowed is True
    assert mappings[0]["role"] == "admin"
    denied, _ = ldap_service._evaluate_access(
        repo,
        [
            "cn=WebNAS-Admins,ou=Groups,dc=example,dc=test",
            "cn=Disabled-WebNAS,ou=Groups,dc=example,dc=test",
        ],
    )
    assert denied is False


def test_identity_is_keyed_by_immutable_id_and_survives_rename(monkeypatch, tmp_path: Path):
    repo = LdapAuthenticationRepository(tmp_path / "ldap-auth.sqlite3")
    fake_identity_repo = SimpleNamespace(
        user_policy=lambda username: None,
        rename_user_policy=lambda old, new, actor: None,
    )
    monkeypatch.setattr("app.ldap_authentication.repository.identity_repository", lambda: fake_identity_repo)
    original = repo.remember_identity(
        "uuid-1", "alice", "uid=alice,dc=example,dc=test",
        display_name="Alice", email="alice@example.test", uid=12001, gid=12000,
        home="/home/alice", groups=[], logged_in=True,
    )
    renamed = repo.remember_identity(
        "uuid-1", "alice.renamed", "uid=alice.renamed,dc=example,dc=test",
        display_name="Alice", email="alice@example.test", uid=12001, gid=12000,
        home="/home/alice", groups=[], logged_in=False,
    )
    assert original["immutable_id"] == renamed["immutable_id"] == "uuid-1"
    assert renamed["username"] == "alice.renamed"
    assert repo.identity_by_username("alice") is None


def test_session_store_keeps_provider_and_identity_id(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.sqlite3", "pepper", cache_ttl_seconds=0)
    store.create(
        "token", "alice", "csrf", persistent=False,
        expires_at=time.time() + 60, auth_provider="ldap", identity_id="uuid-1",
    )
    session = store.resolve("token")
    assert session is not None
    assert session.auth_provider == "ldap"
    assert session.identity_id == "uuid-1"
    assert store.revoke_identity("ldap", "uuid-1") == 1
    assert store.resolve("token") is None


def test_pam_missing_webnas_service_fails_closed(monkeypatch):
    monkeypatch.setattr(auth, "assert_login_allowed", lambda username: None)
    monkeypatch.setattr(auth, "get_config", lambda: SimpleNamespace(auth=SimpleNamespace(pam_service="webnas")))
    monkeypatch.setattr(auth.WEBNAS_PAM_PATH, "is_file", lambda: False)
    with pytest.raises(HTTPException) as error:
        auth.authenticate("alice", "secret")
    assert error.value.status_code == 503


def test_system_provider_selection_never_falls_back(monkeypatch):
    monkeypatch.setattr(auth_api, "auth_mode", lambda: "system")
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    assert auth_api._selected_provider("ldap") == "ldap"
    assert auth_api._selected_provider("pam") == "pam"
    with pytest.raises(HTTPException):
        auth_api._selected_provider("local")


def test_failed_ldap_login_does_not_try_pam(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(auth_api, "auth_mode", lambda: "system")
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    monkeypatch.setattr(
        auth_api,
        "authenticate_ldap",
        lambda username, password: (_ for _ in ()).throw(ldap_service.LdapInvalidCredentials()),
    )
    monkeypatch.setattr(auth_api, "_pam_identity", lambda username, password: calls.append("pam"))
    monkeypatch.setattr(auth_api, "record_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_api.rate_limiter, "check", lambda key: None)
    monkeypatch.setattr(auth_api.rate_limiter, "record_failure", lambda key: None)
    with pytest.raises(HTTPException) as error:
        auth_api.login(
            auth_api.LoginRequest(username="alice", password="bad", auth_method="ldap"),
            request_from(),
            Response(),
        )
    assert error.value.status_code == 401
    assert calls == []
