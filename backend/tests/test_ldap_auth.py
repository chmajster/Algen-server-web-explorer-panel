from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app import auth, auth_api, ldap_auth
from app.ldap_auth import (
    LdapInvalidCredentials,
    LdapServiceUnavailable,
    LdapSettings,
    LdapSettingsInput,
    authenticate_ldap,
    ldap_user_search_filter,
)
from app.security import SessionStore

identity_service_module = importlib.import_module("app.identity.service")


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
    def __init__(self, response=None, *, search_result: bool = True):
        self.response = response or []
        self.search_result = search_result
        self.searches = []
        self.unbound = False

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return self.search_result

    def unbind(self):
        self.unbound = True


class FakeSettingsRepository:
    def __init__(self, settings: LdapSettings, identities=None):
        self.settings = settings
        self.identities = identities or {}
        self.remembered = []

    def get(self):
        return self.settings

    def identity(self, username):
        return self.identities.get(username.casefold())

    def remember_identity(self, username, dn, *, home, display_name="", email=""):
        self.remembered.append((username, dn, home, display_name, email))
        self.identities[username.casefold()] = {
            "username": username,
            "dn": dn,
            "home": home,
            "display_name": display_name,
            "email": email,
        }
        return home

    def home(self, username):
        identity = self.identity(username)
        return str(identity["home"]) if identity else None


class FakeSecretsService:
    def __init__(self):
        self.secret_id = "ldap-secret"
        self.secret = ""

    def save(self, payload, actor, secret_id=None):
        if payload.secret:
            self.secret = payload.secret
        return {"id": secret_id or self.secret_id}

    def delete(self, secret_id, actor):
        self.secret = ""

    def verified_secret(self, secret_id, *, module_id, purpose):
        return {"secret": self.secret}


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


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [
            {"type": "searchResEntry", "dn": "uid=alice,dc=example,dc=com", "attributes": {"uid": "alice"}},
            {"type": "searchResEntry", "dn": "uid=alice2,dc=example,dc=com", "attributes": {"uid": "alice"}},
        ],
    ],
)
def test_ldap_login_requires_exactly_one_search_result(monkeypatch, entries):
    repo = FakeSettingsRepository(ldap_settings())
    service = FakeConnection(entries)
    monkeypatch.setattr(ldap_auth, "settings_repository", lambda: repo)
    monkeypatch.setattr(ldap_auth, "_bind_password", lambda settings, purpose: "bind-secret")
    monkeypatch.setattr(ldap_auth, "_connection", lambda *args, **kwargs: service)

    with pytest.raises(LdapInvalidCredentials):
        authenticate_ldap("alice", "correct-user-password")

    assert service.unbound is True
    assert repo.remembered == []


def test_ldap_login_rejects_entry_whose_username_attribute_does_not_match(monkeypatch):
    entry = {
        "type": "searchResEntry",
        "dn": "uid=bob,ou=people,dc=example,dc=com",
        "attributes": {"uid": "bob"},
    }
    repo = FakeSettingsRepository(ldap_settings())
    service = FakeConnection([entry])
    monkeypatch.setattr(ldap_auth, "settings_repository", lambda: repo)
    monkeypatch.setattr(ldap_auth, "_bind_password", lambda settings, purpose: "bind-secret")
    monkeypatch.setattr(ldap_auth, "_connection", lambda *args, **kwargs: service)

    with pytest.raises(LdapInvalidCredentials):
        authenticate_ldap("alice", "correct-user-password")


def test_ldap_login_binds_exact_user_and_uses_nss_posix_home(monkeypatch):
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
    monkeypatch.setattr(
        ldap_auth,
        "_posix_identity",
        lambda username: SimpleNamespace(pw_name=username, pw_uid=12000, pw_gid=12000, pw_dir="/home/alice"),
    )

    identity = authenticate_ldap("alice", "correct-user-password")

    assert calls == [
        ("cn=webnas,ou=services,dc=example,dc=com", "bind-secret"),
        ("uid=alice,ou=people,dc=example,dc=com", "correct-user-password"),
    ]
    assert identity.provider == "ldap"
    assert identity.home == "/home/alice"
    assert repo.remembered == [
        ("alice", "uid=alice,ou=people,dc=example,dc=com", "/home/alice", "Alice Example", "alice@example.com")
    ]


def test_ldap_identity_requires_nss_posix_mapping(monkeypatch):
    def missing_user(username):
        raise KeyError(username)

    monkeypatch.setattr(ldap_auth.pwd, "getpwnam", missing_user)
    with pytest.raises(LdapServiceUnavailable) as error:
        ldap_auth._posix_identity("alice")
    assert error.value.stage == "identity"
    assert error.value.code == "LDAP_POSIX_IDENTITY_UNAVAILABLE"


def test_ldap_identity_rejects_unsafe_uid(monkeypatch):
    monkeypatch.setattr(
        ldap_auth.pwd,
        "getpwnam",
        lambda username: SimpleNamespace(pw_name=username, pw_uid=0, pw_gid=0, pw_dir="/root"),
    )
    with pytest.raises(LdapServiceUnavailable) as error:
        ldap_auth._posix_identity("root")
    assert error.value.code == "LDAP_POSIX_IDENTITY_UNSAFE"


def test_ldap_identity_cannot_collide_with_local_passwd_user(monkeypatch):
    monkeypatch.setattr(auth, "is_local_passwd_user", lambda username: True)
    with pytest.raises(LdapInvalidCredentials):
        ldap_auth._assert_identity_namespace_available("admin")


def test_first_ldap_login_cannot_inherit_existing_system_rbac_policy(monkeypatch):
    monkeypatch.setattr(auth, "is_local_passwd_user", lambda username: False)
    monkeypatch.setattr(ldap_auth, "is_ldap_identity", lambda username: False)
    monkeypatch.setattr(
        ldap_auth,
        "identity_repository",
        lambda: SimpleNamespace(user_policy=lambda username: {"role": "Administrator"}),
    )
    with pytest.raises(LdapInvalidCredentials):
        ldap_auth._assert_identity_namespace_available("admin")


def test_known_ldap_identity_can_keep_explicit_rbac_policy(monkeypatch):
    monkeypatch.setattr(auth, "is_local_passwd_user", lambda username: False)
    monkeypatch.setattr(ldap_auth, "is_ldap_identity", lambda username: True)
    monkeypatch.setattr(
        ldap_auth,
        "identity_repository",
        lambda: SimpleNamespace(user_policy=lambda username: {"role": "Operator"}),
    )
    ldap_auth._assert_identity_namespace_available("alice")


def test_ldap_identity_never_inherits_linux_admin(monkeypatch):
    monkeypatch.setattr(ldap_auth, "is_ldap_identity", lambda username: True)
    monkeypatch.setattr(identity_service_module.linux_accounts, "is_linux_admin", lambda username: True)
    assert identity_service_module._provider_safe_linux_admin("alice") is False


def test_local_passwd_detection_does_not_treat_nss_only_user_as_pam(tmp_path: Path):
    passwd = tmp_path / "passwd"
    passwd.write_text(
        "root:x:0:0:root:/root:/bin/bash\nlocal:x:1000:1000:Local:/home/local:/bin/bash\n",
        encoding="utf-8",
    )
    assert auth.is_local_passwd_user("local", passwd) is True
    assert auth.is_local_passwd_user("ldap-user", passwd) is False


def test_bind_password_is_preserved_when_settings_update_omits_secret(monkeypatch, tmp_path: Path):
    fake_secrets = FakeSecretsService()
    monkeypatch.setattr(ldap_auth, "secrets_service", lambda: fake_secrets)
    repo = ldap_auth.LdapSettingsRepository(tmp_path / "ldap.sqlite3")
    initial = LdapSettingsInput(
        enabled=True,
        server="ldap.example.com",
        port=389,
        security_mode="starttls",
        verify_tls=True,
        base_dn="dc=example,dc=com",
        user_search_base="ou=people,dc=example,dc=com",
        user_search_filter="(uid={username})",
        username_attribute="uid",
        bind_dn="cn=webnas,ou=services,dc=example,dc=com",
        bind_password="top-secret",
    )
    saved = repo.save(initial, "admin")
    assert saved.bind_password_configured is True
    assert fake_secrets.secret == "top-secret"
    assert "bind_password" not in saved.public_dict()
    assert "bind_secret_id" not in saved.public_dict()

    updated = repo.save(initial.model_copy(update={"bind_password": "", "connect_timeout": 7.0}), "admin")
    assert updated.connect_timeout == 7.0
    assert updated.bind_password_configured is True
    assert fake_secrets.secret == "top-secret"


def test_local_mode_is_default_provider_and_rejects_system_providers(monkeypatch):
    monkeypatch.setattr(auth_api, "auth_mode", lambda: "local")
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    assert auth_api._selected_provider(None) == "local"
    assert auth_api._selected_provider("local") == "local"
    for provider in ("pam", "ldap"):
        with pytest.raises(HTTPException) as error:
            auth_api._selected_provider(provider)
        assert error.value.status_code == 400


def test_system_mode_provider_defaults_follow_ldap_enabled(monkeypatch):
    monkeypatch.setattr(auth_api, "auth_mode", lambda: "system")
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: False)
    assert auth_api._selected_provider(None) == "pam"
    assert auth_api._selected_provider("pam") == "pam"
    with pytest.raises(HTTPException):
        auth_api._selected_provider("local")
    with pytest.raises(HTTPException):
        auth_api._selected_provider("ldap")

    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    assert auth_api._selected_provider(None) == "ldap"
    assert auth_api._selected_provider("ldap") == "ldap"
    assert auth_api._selected_provider("pam") == "pam"


def test_failed_ldap_login_never_calls_pam_or_local(monkeypatch):
    pam_calls = []
    local_calls = []
    monkeypatch.setattr(auth_api, "auth_mode", lambda: "system")
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    monkeypatch.setattr(auth_api, "authenticate_ldap", lambda username, password: (_ for _ in ()).throw(LdapInvalidCredentials()))
    monkeypatch.setattr(auth_api, "_pam_identity", lambda username, password: pam_calls.append(username))
    monkeypatch.setattr(auth_api, "_local_identity", lambda username, password: local_calls.append(username))
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
    assert local_calls == []


def test_failed_pam_login_never_calls_ldap_or_local(monkeypatch):
    ldap_calls = []
    local_calls = []
    monkeypatch.setattr(auth_api, "auth_mode", lambda: "system")
    monkeypatch.setattr(auth_api, "ldap_enabled", lambda: True)
    monkeypatch.setattr(auth_api, "authenticate_ldap", lambda username, password: ldap_calls.append(username))
    monkeypatch.setattr(auth_api, "_local_identity", lambda username, password: local_calls.append(username))

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
    assert local_calls == []


def test_session_store_persists_all_authentication_providers(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.sqlite3", "pepper")
    for provider, username in (("local", "admin"), ("ldap", "alice"), ("pam", "root")):
        token = f"{provider}-token"
        store.create(
            token,
            username,
            "csrf",
            persistent=False,
            expires_at=9999999999,
            auth_provider=provider,
        )
        session = store.resolve(token)
        assert session is not None
        assert session.auth_provider == provider
