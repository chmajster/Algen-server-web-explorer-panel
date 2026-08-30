from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from ldap3 import Connection, Server

from app.ldap_authentication import service as auth_service
from app.modules.ldap_manager import connection as manager_connection
from app.modules.ldap_manager.providers.openldap import OpenLdapProvider


HOST = os.environ.get("WEBNAS_LDAP_INTEGRATION_HOST", "")
PORT = int(os.environ.get("WEBNAS_LDAP_INTEGRATION_PORT", "389"))
BASE_DN = "dc=example,dc=org"
ADMIN_DN = f"cn=admin,{BASE_DN}"
ADMIN_PASSWORD = os.environ.get("WEBNAS_LDAP_ADMIN_PASSWORD", "admin")

pytestmark = pytest.mark.skipif(not HOST, reason="real OpenLDAP integration environment is not configured")


class FakeAuthRepository:
    def __init__(self, settings: dict) -> None:
        self._settings = settings
        self.identity = None

    def settings(self, *, include_secret_id: bool = False):
        return dict(self._settings)

    def access_policy(self):
        return {"mode": "mapped_groups", "allow_groups": [], "deny_groups": []}

    def mappings(self):
        return [
            {
                "id": "map-1",
                "group_dn": f"cn=WebNAS-Users,ou=Groups,{BASE_DN}",
                "role": "user",
                "allow": [],
                "deny": [],
                "priority": 100,
            }
        ]

    def identity_by_username(self, username):
        return self.identity if self.identity and self.identity["username"].casefold() == username.casefold() else None

    def remember_identity(self, immutable_id, username, dn, **kwargs):
        self.identity = {
            "immutable_id": immutable_id,
            "username": username,
            "dn": dn,
            **kwargs,
        }
        return self.identity


def _admin_connection() -> Connection:
    connection = Connection(Server(HOST, port=PORT), user=ADMIN_DN, password=ADMIN_PASSWORD, auto_bind=True)
    return connection


def _ensure_fixture() -> None:
    connection = _admin_connection()
    try:
        for dn, classes, attrs in [
            (f"ou=People,{BASE_DN}", ["organizationalUnit"], {"ou": "People"}),
            (f"ou=Groups,{BASE_DN}", ["organizationalUnit"], {"ou": "Groups"}),
        ]:
            if not connection.search(dn, "(objectClass=*)"):
                connection.add(dn, classes, attrs)
        alice_dn = f"uid=alice,ou=People,{BASE_DN}"
        connection.delete(alice_dn)
        assert connection.add(
            alice_dn,
            ["inetOrgPerson", "posixAccount"],
            {
                "uid": "alice",
                "cn": "Alice Example",
                "sn": "Example",
                "mail": "alice@example.org",
                "uidNumber": "12001",
                "gidNumber": "12000",
                "homeDirectory": "/home/alice",
                "userPassword": "alice-password",
            },
        ), connection.result
        group_dn = f"cn=WebNAS-Users,ou=Groups,{BASE_DN}"
        connection.delete(group_dn)
        assert connection.add(
            group_dn,
            ["groupOfNames"],
            {"cn": "WebNAS-Users", "member": alice_dn},
        ), connection.result
    finally:
        connection.unbind()


def test_real_openldap_authentication_and_manager_crud(monkeypatch):
    _ensure_fixture()
    auth_settings = {
        "enabled": True,
        "directory_type": "ldap",
        "servers": [{"host": HOST, "port": PORT, "priority": 10, "enabled": True}],
        "failover_strategy": "priority",
        "dns_srv_domain": "",
        "security_mode": "ldap",
        "verify_tls": True,
        "connect_timeout": 5,
        "operation_timeout": 10,
        "base_dn": BASE_DN,
        "user_search_base": f"ou=People,{BASE_DN}",
        "user_search_filter": "(uid={username})",
        "username_attribute": "uid",
        "immutable_id_attribute": "entryUUID",
        "bind_dn": ADMIN_DN,
        "bind_secret_id": "integration-auth-secret",
        "display_name_attribute": "cn",
        "email_attribute": "mail",
        "group_search_base": f"ou=Groups,{BASE_DN}",
        "group_search_filter": "(member={dn})",
        "group_membership_attribute": "memberOf",
        "group_cache_ttl_seconds": 60,
    }
    auth_repo = FakeAuthRepository(auth_settings)
    monkeypatch.setattr(auth_service, "repository", lambda: auth_repo)
    monkeypatch.setattr(auth_service, "_bind_password", lambda settings, purpose: ADMIN_PASSWORD)
    monkeypatch.setattr(auth_service, "_assert_namespace_available", lambda store, username, immutable_id: None)
    monkeypatch.setattr(auth_service, "_apply_rbac", lambda username, mappings: {"role": "user"})
    monkeypatch.setattr(
        auth_service,
        "_posix_identity",
        lambda username: SimpleNamespace(pw_uid=12001, pw_gid=12000, pw_dir="/home/alice"),
    )

    identity = auth_service.authenticate_ldap("alice", "alice-password")
    assert identity.provider == "ldap"
    assert identity.identity_id
    assert identity.home == "/home/alice"

    manager_config = {
        "servers": [{"host": HOST, "port": PORT, "priority": 10}],
        "security_mode": "ldap",
        "verify_tls": True,
        "base_dn": BASE_DN,
        "bind_dn": ADMIN_DN,
        "bind_secret_id": "integration-manager-secret",
        "connect_timeout": 5,
        "operation_timeout": 10,
    }
    monkeypatch.setattr(manager_connection, "_bind_password", lambda config, purpose: ADMIN_PASSWORD)
    provider = OpenLdapProvider(manager_config)

    bob_dn = f"uid=bob,ou=People,{BASE_DN}"
    group_dn = f"cn=Integration-Team,ou=Groups,{BASE_DN}"
    admin = _admin_connection()
    admin.delete(group_dn)
    admin.delete(bob_dn)
    admin.unbind()

    created = provider.create(
        bob_dn,
        ["inetOrgPerson", "posixAccount"],
        {
            "uid": "bob",
            "cn": "Bob Example",
            "sn": "Example",
            "mail": "bob@example.org",
            "uidNumber": "12002",
            "gidNumber": "12000",
            "homeDirectory": "/home/bob",
        },
    )
    assert created["dn"].casefold() == bob_dn.casefold()
    provider.update(bob_dn, {"displayName": "Bob Integration"}, [])
    provider.create(group_dn, ["groupOfNames"], {"cn": "Integration-Team", "member": bob_dn})
    provider.add_member(group_dn, f"uid=alice,ou=People,{BASE_DN}")
    group = provider.entry(group_dn)
    members = [str(value).casefold() for value in group["attributes"].get("member", [])]
    assert bob_dn.casefold() in members
    assert f"uid=alice,ou=people,{BASE_DN}".casefold() in members
    provider.remove_member(group_dn, f"uid=alice,ou=People,{BASE_DN}")
    provider.delete(group_dn)
    provider.delete(bob_dn)
