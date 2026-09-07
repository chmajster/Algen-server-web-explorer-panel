from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.identity.permission_service import PermissionRepository, PermissionService
from app.ldap_rbac import _safe_contains_filter, expand_nested_groups
from app.security import SessionUser


def test_nested_groups_include_all_ancestors_without_looping():
    parents = {
        "cn=linux-admins,dc=example": {"cn=webnas-admins,dc=example"},
        "cn=webnas-admins,dc=example": {"cn=top,dc=example"},
        "cn=top,dc=example": {"cn=linux-admins,dc=example"},
    }
    result = expand_nested_groups({"CN=Linux-Admins,DC=example"}, parents, max_depth=8, max_nodes=100)
    assert result == {
        "cn=linux-admins,dc=example",
        "cn=webnas-admins,dc=example",
        "cn=top,dc=example",
    }


def test_nested_group_depth_is_bounded():
    parents = {
        "cn=a": {"cn=b"},
        "cn=b": {"cn=c"},
        "cn=c": {"cn=d"},
    }
    assert expand_nested_groups({"cn=a"}, parents, max_depth=1, max_nodes=100) == {"cn=a", "cn=b"}


def test_nested_group_tree_limit_rejects_directory_bomb():
    parents = {"cn=a": {f"cn={index}" for index in range(20)}}
    with pytest.raises(HTTPException) as error:
        expand_nested_groups({"cn=a"}, parents, max_depth=8, max_nodes=5)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "LDAP_NESTED_GROUP_LIMIT"


def test_ldap_search_input_is_escaped():
    result = _safe_contains_filter("cn", "*)(|(objectClass=*))")
    assert "(|(objectClass=*))" not in result
    assert "\\2a" in result
    assert result.startswith("(cn=*")


def test_ldap_search_attribute_cannot_inject_filter():
    with pytest.raises(HTTPException) as error:
        _safe_contains_filter("cn)(objectClass=*", "admins")
    assert error.value.status_code == 422


def test_same_username_in_pam_and_ldap_are_different_principals(tmp_path):
    store = PermissionRepository(tmp_path / "identity.sqlite3")
    role = store.create_role({"name": "LDAP only", "permissions": [{"permission": "files.read"}]}, "test")
    ldap = SessionUser(username="jan", csrf_token="", auth_provider="ldap", identity_id="guid-jan")
    pam = SessionUser(username="jan", csrf_token="", auth_provider="pam", identity_id="jan")
    store.assign_user_role(ldap, role["id"], "test")
    service = PermissionService(store, cache_ttl=0)
    assert service.can(ldap, "files.read")
    assert not service.can(pam, "files.read")


def test_mapping_change_requires_invalidation_and_removes_old_access(tmp_path):
    store = PermissionRepository(tmp_path / "identity.sqlite3")
    role = store.create_role({"name": "Mapped", "permissions": [{"permission": "files.read"}]}, "test")
    group_id = store.upsert_external_group("ldap", "g1", "CN=Admins,DC=example", "Admins")
    store.map_external_group_role(group_id, role["id"], "test")
    subject = SessionUser(username="jan", csrf_token="", auth_provider="ldap", identity_id="u1")
    store.replace_external_memberships("ldap", "u1", "jan", {group_id})
    service = PermissionService(store, cache_ttl=60)
    assert service.can(subject, "files.read")
    with store._lock, store._connect() as db:
        db.execute("DELETE FROM rbac_external_group_roles WHERE external_group_id=?", (group_id,))
    service.invalidate()
    assert not service.can(subject, "files.read")


def test_removing_local_group_membership_revokes_access(tmp_path):
    store = PermissionRepository(tmp_path / "identity.sqlite3")
    role = store.create_role({"name": "Group reader", "permissions": [{"permission": "files.read"}]}, "test")
    group = store.create_group({"name": "Readers", "role_ids": [role["id"]]}, "test")
    subject = SessionUser(username="jan", csrf_token="", auth_provider="pam", identity_id="jan")
    store.set_group_members(group["id"], [{"username": "jan", "provider": "pam", "identity_id": "jan"}], "test")
    service = PermissionService(store, cache_ttl=0)
    assert service.can(subject, "files.read")
    store.set_group_members(group["id"], [], "test")
    service.invalidate()
    assert not service.can(subject, "files.read")
