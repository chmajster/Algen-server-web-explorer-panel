from collections import UserDict
from pathlib import Path

import pytest

from app.modules.ldap_manager.models import ConnectionInput, DirectoryUpdateRequest
from app.modules.ldap_manager.providers.base import LdapDirectoryProvider, ProviderOperationError
from app.modules.ldap_manager.repository import LdapManagerRepository
from app.modules.ldap_manager.service import LdapManagerService
from app.modules.ldap_manager.security import (
    escaped_filter_value,
    rdn,
    sanitize_attributes,
    validate_dn,
)


class FakeSecretsService:
    def __init__(self) -> None:
        self.saved: dict[str, str] = {}
        self.deleted: list[str] = []

    def save(self, payload, actor, secret_id=None):
        identifier = secret_id or f"manager-secret-{len(self.saved) + 1}"
        if payload.secret:
            self.saved[identifier] = payload.secret
        return {"id": identifier}

    def delete(self, secret_id, actor):
        self.deleted.append(secret_id)
        self.saved.pop(secret_id, None)


def connection_payload(**overrides) -> ConnectionInput:
    values = {
        "name": "Corporate LDAP",
        "directory_type": "ldap",
        "servers": [{"host": "ldap.example.test", "port": 636, "priority": 10}],
        "security_mode": "ldaps",
        "verify_tls": True,
        "base_dn": "dc=example,dc=test",
        "bind_dn": "cn=webnas-admin,ou=Services,dc=example,dc=test",
        "bind_password": "manager-password",
    }
    values.update(overrides)
    return ConnectionInput(**values)


def test_manager_connection_owns_separate_secret(monkeypatch, tmp_path: Path):
    fake = FakeSecretsService()
    monkeypatch.setattr("app.modules.ldap_manager.repository.secrets_service", lambda: fake)
    repo = LdapManagerRepository(tmp_path / "ldap-manager.sqlite3")
    saved = repo.save(connection_payload(), "admin")

    assert saved["bind_password_configured"] is True
    assert "bind_password" not in saved
    assert "bind_secret_id" not in saved
    internal = repo.get(saved["id"], include_secret_id=True)
    assert internal["bind_secret_id"].startswith("manager-secret-")
    assert internal["bind_secret_id"] != "auth-secret"


def test_manager_requires_its_own_bind_password(monkeypatch, tmp_path: Path):
    fake = FakeSecretsService()
    monkeypatch.setattr("app.modules.ldap_manager.repository.secrets_service", lambda: fake)
    repo = LdapManagerRepository(tmp_path / "ldap-manager.sqlite3")
    with pytest.raises(ValueError, match="requires its own bind password"):
        repo.save(connection_payload(bind_password=""), "admin")


def test_delete_connection_removes_manager_secret(monkeypatch, tmp_path: Path):
    fake = FakeSecretsService()
    monkeypatch.setattr("app.modules.ldap_manager.repository.secrets_service", lambda: fake)
    repo = LdapManagerRepository(tmp_path / "ldap-manager.sqlite3")
    saved = repo.save(connection_payload(), "admin")
    secret_id = repo.get(saved["id"], include_secret_id=True)["bind_secret_id"]
    repo.delete(saved["id"], "admin")
    assert secret_id in fake.deleted


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [("*", r"\2a"), ("alice)(uid=*)", r"alice\29\28uid=\2a\29")],
)
def test_search_values_are_rfc4515_escaped(raw: str, escaped: str):
    assert escaped_filter_value(raw) == escaped


def test_rdn_escaping_and_dn_validation():
    assert rdn("cn", "Doe, John") == r"cn=Doe\, John"
    assert validate_dn(r"cn=Doe\, John,ou=People,dc=example,dc=test")
    with pytest.raises(ValueError):
        validate_dn("not-a-dn")


def test_generic_attribute_update_blocks_sensitive_fields():
    with pytest.raises(ValueError):
        sanitize_attributes({"unicodePwd": "secret"})
    with pytest.raises(ValueError):
        sanitize_attributes({"userAccountControl": 512})
    assert sanitize_attributes({"displayName": "Alice"}) == {"displayName": "Alice"}


def test_posix_group_memberuid_uses_username_instead_of_dn(monkeypatch):
    provider = LdapDirectoryProvider({})
    monkeypatch.setattr(
        provider,
        "entry",
        lambda dn: {"dn": dn, "attributes": {"uid": ["alice"]}},
    )
    member_dn = "uid=alice,ou=People,dc=example,dc=test"
    assert provider._membership_value("memberUid", member_dn) == "alice"
    assert provider._membership_value("member", member_dn) == member_dn


def test_posix_group_memberuid_rejects_entry_without_uid(monkeypatch):
    provider = LdapDirectoryProvider({})
    monkeypatch.setattr(provider, "entry", lambda dn: {"dn": dn, "attributes": {}})
    with pytest.raises(ProviderOperationError, match="requires the member uid"):
        provider._membership_value("memberUid", "cn=NoUid,ou=People,dc=example,dc=test")


class FakeTypedProvider:
    def __init__(self, classes: list[str]) -> None:
        self.classes = classes
        self.updated = False

    def entry(self, dn: str):
        return {"dn": dn, "attributes": {"objectClass": self.classes}}

    def update(self, dn: str, attributes, delete_attributes):
        self.updated = True
        return self.entry(dn)


def test_ou_scope_rejects_user_entry(monkeypatch):
    manager = LdapManagerService(object())  # type: ignore[arg-type]
    provider = FakeTypedProvider(["top", "person", "inetOrgPerson"])
    monkeypatch.setattr(manager, "_provider", lambda connection_id: provider)
    with pytest.raises(ValueError, match="not a ou object"):
        manager.update_entry(
            "connection",
            "uid=alice,ou=People,dc=example,dc=test",
            DirectoryUpdateRequest(attributes={"description": "x"}),
            kind="ou",
        )
    assert provider.updated is False


def test_export_csv_follows_all_paging_cookies(monkeypatch):
    manager = LdapManagerService(object())  # type: ignore[arg-type]

    class PagedProvider:
        def users(self, *, page_size=100, cookie="", search=""):
            if not cookie:
                return {"items": [{"dn": "uid=a", "attributes": {"uid": "a"}}], "cookie": "next"}
            return {"items": [{"dn": "uid=b", "attributes": {"uid": "b"}}], "cookie": ""}

    monkeypatch.setattr(manager, "_provider", lambda connection_id: PagedProvider())
    exported = manager.export_csv("connection", "users")
    assert "uid=a" in exported
    assert "uid=b" in exported


def test_provider_entry_accepts_mapping_backed_attributes():
    from app.modules.ldap_manager.providers import base as provider_base

    member_dn = "uid=bob,ou=People,dc=example,dc=test"
    normalized = provider_base._entry(
        {
            "dn": "cn=Integration-Team,ou=Groups,dc=example,dc=test",
            "attributes": UserDict({"member": [member_dn], "cn": ["Integration-Team"]}),
        }
    )
    assert normalized["attributes"]["member"] == [member_dn]
