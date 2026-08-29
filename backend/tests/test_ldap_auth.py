from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app import auth_api, ldap_auth
from app.ldap_auth import (
    LdapInvalidCredentials,
    LdapSettings,
    LdapSettingsInput,
    authenticate_ldap,
    ldap_user_search_filter,
)
from app.security import SessionStore


def ldap_settings(**overrides) -> LdapSettings:
    values = {
        "enabled": True,
        "server": "ldap.example.com",
        "port": 389,
        "security_mode": "starttls",
        "verify_tls": True,
        "connect_timeout": 5.0,
        "operation_timeout": 10.0,
        "base_dn": "dc=example,dc=com",
        "user_search_base": "ou=people,dc=example,dc=com",
        "user_search_filter": "(uid={username})",
        "username_attribute": "uid",
        "bind_dn": "cn=webnas,ou=services,dc=example,dc=com",
        "bind_secret_id": "secret-id",
        "display_name_attribute": "displayName",
        "email_attribute": "mail",
    }
    values.update(overrides)
    return LdapSettings(**values)


class FakeConnection:
    def __init__(self, response=None):
        self.response = response or []
        self.searches = []
        self.unbound = False

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return True

    def unbind(self):
        self.unbound = True


class FakeSettingsRepository:
    def __init__(self, settings: LdapSettings):
        self.settings = settings
        self.remembered = []

    def get(self):
        return self.settings

    def remember_identity(self, username, dn, *, display_name="", email=""):
        self.remembered.append((username, dn, display_name, email))
        return f"/tmp/ldap-home/{username}"


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


def test_ldap_settings_are_disabled_and_tls_verified_by_default():
    settings = LdapSettingsInput()
    assert settings.enabled is False
    assert settings.security_mode == "starttls"
    assert settings.verify_tls is True


def test_search_filter_requires_exact_username_placeholder():
    with pytest.raises(ValueError):
        LdapSettingsInput(user_search_filter="(uid=static)")
    with pytest.raises(ValueError):
        LdapSettingsInput(user_search_filter="(|(uid={username})(mail={username}))")


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
def test_search_filter_escapes_rfc4515_metacharacters(username, escaped):
    assert ldap_user_search_filter("(uid={username})", username) == f"(uid={escaped})"


@pytest.mark.parametrize("entries", [[], [
    {"type": "searchResEntry", "dn": "uid=alice,dc=example,dc=com", "attributes": {"uid": "alice"}},
    {"type": "searchResEntry", "dn": "uid=alice2,dc=example,dc=com", "attributes": {"uid": "alice"}},
]])
def test_ldap_login_requires_exactly_one_search_result(monkeypatch, entries):
    repo = FakeSettingsRepository(ldap_settings())
    service = FakeConnection(entries)
    monkeypatch.setattr(ldap_auth, "settings_repository", lambda: repo)
    monkeypatch.setattr(ldap_auth, "_bind_password", lambda settings, purpose: "bind-secret")
    monkeypatch.setattr(ldap_auth, "_connection", lambda *args, **kwargs: service)
    monkeypatch.setattr(ldap_auth, "_assert_identity_namespace_available", lambda username: None)

    with pytest.raises(LdapInvalidCredentials):
        authenticate_ldap("alice", "correct-user-password")

    assert service.unbound is True
    assert repo.remembered == []


def test_ldap_login_binds_the_exact_user_and_jit_provisions_identity(monkeypatch):
    entry = {
        "type": "searchResEntry",
        "dn": "uid=alice,ou=people,dc=example,dc=com",
        "attributes": {
            "uid": "alice",
            "displayName": "Alice Example",
            "mail": "alice@example.com",
        },
    }
    repo = FakeSettingsRepository(ldap_settings())
    service = FakeConnection([entry])
    user_connection = FakeConnection()
    calls = []

    def connection(settings, *, user: str, password: str):
        calls.append((user, password))
        return service if len(calls) == 1 else user_connection

    monkeypatch.setattr(ldap_auth, "settings_repository", lambda: repo)
    monkeypatch.setattr(ldap_auth, "_bind_password", lambda settings, purpose: "bind-secret")
    monkeypatch.setattr(ldap_auth, "_connection", connection)
    monkeypatch.setattr(ldap_auth, "_assert_identity_namespace_available", lambda username: None)

    identity = authenticate_ldap("alice", "correct-user-password")

    assert calls == [
        ("cn=webnas,ou=services,dc=example,dc=com", "bind-secret"),
        ("uid=alice,ou=people,dc=example,dc=com", "correct-user-password"),
    ]
    assert identity.provider == "ldap"
    assert identity.home == "/tmp/ldap-home/alice"
    assert repo.remembered == [
        ("alice", "uid=alice,ou=people,dc=example,dc=com", "Alice Example", "alice@example.com")
    ]


def test_ldap_identity_cannot_collide_with_local_linux_user(monkeypatch):
    monkeypatch.setattr(ldap_auth.pwd, "getpwnam", lambda username: SimpleNamespace(pw_name=username))
    with pytest.raises(LdapInvalidCredentials):
        ldap_auth._assert_identity_namespace_available("admin")


def test_ldap_identity_cannot_inherit_existing_local_rbac_policy(monkeypatch):
    def missing_local_user(username):
        raise KeyError(username)

    monkeypatch.setattr(ldap_auth.pwd, "getpwnam", missing_local_user)
    monkeypatch.setattr(
        ldap_auth,
        "identity_repository",
        lambda: SimpleNamespace(user_policy=lambda username: {"role": "Administrator"}),
    )
    with pytest.raises(LdapInvalidCredentials):
        ldap_auth._assert_identity_namespace_available("admin")


def test_provider_defaults_follow_ldap_enabled(monkeypatch):
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: False)
    assert auth_api._selected_provider(None) == "pam"
    assert auth_api._selected_provider("pam") == "pam"
    with pytest.raises(HTTPException) as error:
        auth_api._selected_provider("ldap")
    assert error.value.status_code == 400

    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    assert auth_api._selected_provider(None) == "ldap"
    assert auth_api._selected_provider("ldap") == "ldap"
    assert auth_api._selected_provider("pam") == "pam"


def test_failed_ldap_login_never_calls_pam(monkeypatch):
    pam_calls = []
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    monkeypatch.setattr(auth_api, "authenticate_ldap", lambda username, password: (_ for _ in ()).throw(LdapInvalidCredentials()))
    monkeypatch.setattr(auth_api, "_pam_identity", lambda username, password: pam_calls.append(username))
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
    assert pam_calls == []


def test_failed_pam_login_never_calls_ldap(monkeypatch):
    ldap_calls = []
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    monkeypatch.setattr(auth_api, "authenticate_ldap", lambda username, password: ldap_calls.append(username))

    def fail_pam(username, password):
        raise HTTPException(401, "Invalid username or password")

    monkeypatch.setattr(auth_api, "_pam_identity", fail_pam)
    monkeypatch.setattr(auth_api, "record_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_api.rate_limiter, "check", lambda key: None)
    monkeypatch.setattr(auth_api.rate_limiter, "record_failure", lambda key: None)

    with pytest.raises(HTTPException) as error:
        auth_api.login(
            auth_api.LoginRequest(username="alice", password="bad", auth_method="pam"),
            request_from(),
            Response(),
        )
    assert error.value.status_code == 401
    assert ldap_calls == []


def test_session_store_persists_authentication_provider(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.sqlite3", "pepper")
    store.create(
        "ldap-token",
        "alice",
        "csrf",
        persistent=False,
        expires_at=9999999999,
        auth_provider="ldap",
    )
    ldap_session = store.resolve("ldap-token")
    assert ldap_session is not None
    assert ldap_session.auth_provider == "ldap"

    store.create(
        "pam-token",
        "root",
        "csrf2",
        persistent=False,
        expires_at=9999999999,
    )
    pam_session = store.resolve("pam-token")
    assert pam_session is not None
    assert pam_session.auth_provider == "pam"
