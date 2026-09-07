from __future__ import annotations

from pathlib import Path

from app.identity.permission_service import PermissionRepository, PermissionService, Resource
from app.security import SessionUser


def user(name: str = "jan", provider: str = "pam", identity_id: str = "") -> SessionUser:
    return SessionUser(username=name, csrf_token="", auth_provider=provider, identity_id=identity_id or name)


def repo(tmp_path: Path) -> PermissionRepository:
    return PermissionRepository(tmp_path / "identity.sqlite3")


def custom_role(store: PermissionRepository, name: str, permissions: list[dict]) -> str:
    return store.create_role({"name": name, "description": "test", "permissions": permissions}, "tester")["id"]


def test_default_deny(tmp_path: Path):
    service = PermissionService(repo(tmp_path), cache_ttl=0)
    decision = service.explain(user(), "files.read")
    assert decision.allowed is False
    assert decision.reason.startswith("default deny")


def test_direct_user_role(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "DirectReader", [{"permission": "files.read", "effect": "allow"}])
    store.assign_user_role(user(), role_id, "tester")
    service = PermissionService(store, cache_ttl=0)
    decision = service.explain(user(), "files.read")
    assert decision.allowed is True
    assert decision.sources[0].source_type == "direct-role"


def test_local_group_role(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "GroupWriter", [{"permission": "files.write", "effect": "allow"}])
    group = store.create_group({"name": "Support", "role_ids": [role_id]}, "tester")
    store.set_group_members(group["id"], [{"username": "jan", "provider": "pam", "identity_id": "jan"}], "tester")
    service = PermissionService(store, cache_ttl=0)
    assert service.can(user(), "files.write")
    assert any(source.source_type == "local-group" for source in service.sources(user()))


def test_ldap_group_role(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "LdapOperator", [{"permission": "docker.manage", "effect": "allow"}])
    group_id = store.upsert_external_group("ldap", "guid-1", "CN=Linux-Admins,DC=example,DC=com", "Linux-Admins")
    store.map_external_group_role(group_id, role_id, "tester")
    store.replace_external_memberships("ldap", "guid-user", "jan", {group_id})
    subject = user("jan", "ldap", "guid-user")
    service = PermissionService(store, cache_ttl=0)
    decision = service.explain(subject, "docker.manage")
    assert decision.allowed
    assert decision.sources[0].source_type == "ldap-group"
    assert "CN=Linux-Admins" in decision.sources[0].reason


def test_multiple_groups_are_additive(tmp_path: Path):
    store = repo(tmp_path)
    r1 = custom_role(store, "Reader", [{"permission": "files.read"}])
    r2 = custom_role(store, "ServiceReader", [{"permission": "services.read"}])
    for name, role in (("g1", r1), ("g2", r2)):
        group = store.create_group({"name": name, "role_ids": [role]}, "tester")
        store.set_group_members(group["id"], [{"username": "jan", "identity_id": "jan", "provider": "pam"}], "tester")
    service = PermissionService(store, cache_ttl=0)
    assert service.can(user(), "files.read")
    assert service.can(user(), "services.read")


def test_explicit_deny_overrides_allow(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "Mixed", [
        {"permission": "docker.manage", "effect": "allow"},
        {"permission": "docker.manage", "effect": "deny", "resource_type": "container", "resource_id": "prod-nginx"},
    ])
    store.assign_user_role(user(), role_id, "tester")
    service = PermissionService(store, cache_ttl=0)
    assert service.can(user(), "docker.manage", Resource("container", "dev-nginx", "*"))
    decision = service.explain(user(), "docker.manage", Resource("container", "prod-nginx", "*"))
    assert not decision.allowed
    assert decision.reason == "explicit deny overrides allow"


def test_resource_scope(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "HomeWriter", [{"permission": "files.write", "resource_type": "files", "resource_id": "home", "scope": "/home/jan"}])
    store.assign_user_role(user(), role_id, "tester")
    service = PermissionService(store, cache_ttl=0)
    assert service.can(user(), "files.write", Resource("files", "home", "/home/jan/docs"))
    assert not service.can(user(), "files.write", Resource("files", "home", "/home/anna"))


def test_policy_deny_overrides_role(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "OperatorX", [{"permission": "docker.manage"}])
    store.assign_user_role(user(), role_id, "tester")
    store.create_policy({
        "name": "NoProd", "effect": "deny", "permission": "docker.manage",
        "resource_type": "container", "resource_id": "production", "scope": "*",
        "subjects": [{"subject_type": "user", "subject_id": "jan"}],
    }, "tester")
    service = PermissionService(store, cache_ttl=0)
    assert not service.can(user(), "docker.manage", Resource("container", "production", "*"))


def test_cache_invalidation_after_revocation(tmp_path: Path):
    store = repo(tmp_path)
    role_id = custom_role(store, "Cached", [{"permission": "files.read"}])
    subject = user()
    store.assign_user_role(subject, role_id, "tester")
    service = PermissionService(store, cache_ttl=60)
    assert service.can(subject, "files.read")
    store.revoke_user_role(subject, role_id, "tester")
    assert service.can(subject, "files.read")  # bounded cache before explicit invalidation
    service.invalidate()
    assert not service.can(subject, "files.read")


def test_managed_ldap_group_cannot_be_locally_edited(tmp_path: Path):
    store = repo(tmp_path)
    group = store.create_group({"name": "LDAP/Linux-Admins", "source": "ldap", "external_id": "1", "distinguished_name": "CN=Linux-Admins,DC=example"}, "tester")
    try:
        store.set_group_members(group["id"], [{"username": "jan"}], "tester")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("LDAP-managed membership must be read-only")
