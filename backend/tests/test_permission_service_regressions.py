from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.identity.permission_service import (
    PermissionRepository,
    PermissionService,
    Resource,
    normalize_permission_id,
)
from app.security import SessionUser


def principal(
    username: str = "jan",
    provider: str = "pam",
    identity_id: str = "",
) -> SessionUser:
    return SessionUser(
        username=username,
        csrf_token="csrf",
        auth_provider=provider,
        identity_id=identity_id or username,
    )


def repository(tmp_path: Path) -> PermissionRepository:
    return PermissionRepository(tmp_path / "identity.sqlite3")


def create_role(
    store: PermissionRepository,
    name: str,
    permissions: list[dict],
    *,
    active: bool = True,
) -> str:
    return store.create_role(
        {
            "name": name,
            "description": f"test role {name}",
            "active": active,
            "permissions": permissions,
        },
        "pytest",
        "127.0.0.1",
    )["id"]


def test_permission_alias_is_normalized_on_write_and_read(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Alias writer", [{"permission": "files.write"}])
    role = store.role(role_id)

    assert role["permissions"][0]["permission"] == "files.edit"
    assert normalize_permission_id("files.write") == "files.edit"

    subject = principal()
    store.assign_user_role(subject, role_id, "pytest")
    service = PermissionService(store, cache_ttl=0)

    assert service.can(subject, "files.write")
    assert service.can(subject, "files.edit")


def test_unknown_permission_rolls_back_role_creation(tmp_path: Path):
    store = repository(tmp_path)

    with pytest.raises(HTTPException) as error:
        create_role(store, "Broken role", [{"permission": "does.not.exist"}])

    assert error.value.status_code == 422
    assert all(role["name"] != "Broken role" for role in store.roles())


def test_role_names_are_case_insensitively_unique(tmp_path: Path):
    store = repository(tmp_path)
    create_role(store, "Storage Admin", [{"permission": "files.read"}])

    with pytest.raises(HTTPException) as error:
        create_role(store, "storage admin", [{"permission": "files.read"}])

    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("rename", {"name": "Renamed Administrator"}),
        ("delete", None),
    ],
)
def test_system_roles_are_protected(tmp_path: Path, operation: str, payload: dict | None):
    store = repository(tmp_path)
    role_id = "system:administrator"

    with pytest.raises(HTTPException) as error:
        if operation == "rename":
            store.update_role(role_id, payload or {}, "pytest")
        else:
            store.delete_role(role_id, "pytest")

    assert error.value.status_code == 409
    assert store.role(role_id)["name"] == "Administrator"


def test_inactive_direct_role_stops_granting_access(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Temporary reader", [{"permission": "files.read"}])
    subject = principal()
    store.assign_user_role(subject, role_id, "pytest")

    service = PermissionService(store, cache_ttl=0)
    assert service.can(subject, "files.read")

    store.update_role(role_id, {"active": False}, "pytest")
    assert not service.can(subject, "files.read")


def test_inactive_local_group_stops_granting_access(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Group reader", [{"permission": "files.read"}])
    group = store.create_group(
        {"name": "Helpdesk", "role_ids": [role_id]},
        "pytest",
    )
    subject = principal()
    store.set_group_members(
        group["id"],
        [{"username": subject.username, "provider": "pam", "identity_id": subject.identity_id}],
        "pytest",
    )

    service = PermissionService(store, cache_ttl=0)
    assert service.can(subject, "files.read")

    store.update_group(group["id"], {"active": False}, "pytest")
    assert not service.can(subject, "files.read")


def test_replacing_group_roles_revokes_old_and_grants_new_permissions(tmp_path: Path):
    store = repository(tmp_path)
    reader = create_role(store, "Reader", [{"permission": "files.read"}])
    services = create_role(store, "Services", [{"permission": "services.read"}])
    group = store.create_group(
        {"name": "Operators", "role_ids": [reader]},
        "pytest",
    )
    subject = principal()
    store.set_group_members(
        group["id"],
        [{"username": "jan", "provider": "pam", "identity_id": "jan"}],
        "pytest",
    )
    service = PermissionService(store, cache_ttl=0)

    assert service.can(subject, "files.read")
    assert not service.can(subject, "services.read")

    store.update_group(group["id"], {"role_ids": [services]}, "pytest")

    assert not service.can(subject, "files.read")
    assert service.can(subject, "services.read")


def test_deleting_custom_role_cascades_user_assignment(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Disposable", [{"permission": "files.read"}])
    subject = principal()
    store.assign_user_role(subject, role_id, "pytest")
    service = PermissionService(store, cache_ttl=0)

    assert service.can(subject, "files.read")
    store.delete_role(role_id, "pytest")

    assert not service.can(subject, "files.read")


def test_deleting_local_group_revokes_group_derived_access(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Group disposable", [{"permission": "files.read"}])
    group = store.create_group(
        {"name": "Disposable group", "role_ids": [role_id]},
        "pytest",
    )
    subject = principal()
    store.set_group_members(
        group["id"],
        [{"username": "jan", "provider": "pam", "identity_id": "jan"}],
        "pytest",
    )
    service = PermissionService(store, cache_ttl=0)

    assert service.can(subject, "files.read")
    store.delete_group(group["id"], "pytest")

    assert not service.can(subject, "files.read")


def test_inactive_policy_is_ignored(tmp_path: Path):
    store = repository(tmp_path)
    store.create_policy(
        {
            "name": "Disabled allow",
            "active": False,
            "effect": "allow",
            "permission": "files.read",
            "subjects": [{"subject_type": "user", "subject_id": "jan"}],
        },
        "pytest",
    )
    service = PermissionService(store, cache_ttl=0)

    assert not service.can(principal(), "files.read")


def test_policy_auth_provider_condition_isolated_between_pam_and_ldap(tmp_path: Path):
    store = repository(tmp_path)
    store.create_policy(
        {
            "name": "LDAP readers",
            "effect": "allow",
            "permission": "files.read",
            "conditions": {"auth_provider": "ldap"},
            "subjects": [],
        },
        "pytest",
    )
    service = PermissionService(store, cache_ttl=0)

    assert service.can(principal("jan", "ldap", "guid-jan"), "files.read")
    assert not service.can(principal("jan", "pam", "jan"), "files.read")


def test_provider_policy_subject_matches_only_requested_provider(tmp_path: Path):
    store = repository(tmp_path)
    store.create_policy(
        {
            "name": "PAM users",
            "effect": "allow",
            "permission": "services.read",
            "subjects": [{"subject_type": "provider", "subject_id": "pam"}],
        },
        "pytest",
    )
    service = PermissionService(store, cache_ttl=0)

    assert service.can(principal("jan", "pam", "jan"), "services.read")
    assert not service.can(principal("jan", "ldap", "guid-jan"), "services.read")


def test_group_policy_subject_matches_membership_not_username_only(tmp_path: Path):
    store = repository(tmp_path)
    group = store.create_group({"name": "Policy group"}, "pytest")
    member = principal("jan", "pam", "jan")
    same_name_other_provider = principal("jan", "ldap", "guid-jan")
    store.set_group_members(
        group["id"],
        [{"username": "jan", "provider": "pam", "identity_id": "jan"}],
        "pytest",
    )
    store.create_policy(
        {
            "name": "Group policy",
            "effect": "allow",
            "permission": "services.read",
            "subjects": [{"subject_type": "group", "subject_id": group["id"]}],
        },
        "pytest",
    )
    service = PermissionService(store, cache_ttl=0)

    assert service.can(member, "services.read")
    assert not service.can(same_name_other_provider, "services.read")


def test_external_group_status_inactive_removes_role_grant(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "LDAP reader", [{"permission": "files.read"}])
    group_id = store.upsert_external_group(
        "ldap",
        "group-guid",
        "CN=Readers,DC=example,DC=com",
        "Readers",
    )
    store.map_external_group_role(group_id, role_id, "pytest")
    subject = principal("jan", "ldap", "user-guid")
    store.replace_external_memberships("ldap", "user-guid", "jan", {group_id})
    service = PermissionService(store, cache_ttl=0)

    assert service.can(subject, "files.read")

    store.upsert_external_group(
        "ldap",
        "group-guid",
        "CN=Readers,DC=example,DC=com",
        "Readers",
        status="inactive",
    )

    assert not service.can(subject, "files.read")


def test_resource_scope_accepts_exact_path_and_descendants_only(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(
        store,
        "Scoped editor",
        [
            {
                "permission": "files.edit",
                "resource_type": "files",
                "resource_id": "home",
                "scope": "/home/jan",
            }
        ],
    )
    subject = principal()
    store.assign_user_role(subject, role_id, "pytest")
    service = PermissionService(store, cache_ttl=0)

    assert service.can(subject, "files.edit", Resource("files", "home", "/home/jan"))
    assert service.can(subject, "files.edit", Resource("files", "home", "/home/jan/docs"))
    assert not service.can(subject, "files.edit", Resource("files", "home", "/home/janna"))
    assert not service.can(subject, "files.edit", Resource("files", "other", "/home/jan"))


def test_resource_scoped_deny_does_not_deny_other_resource(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(
        store,
        "Container operator",
        [
            {"permission": "docker.manage", "effect": "allow"},
            {
                "permission": "docker.manage",
                "effect": "deny",
                "resource_type": "container",
                "resource_id": "production",
            },
        ],
    )
    subject = principal()
    store.assign_user_role(subject, role_id, "pytest")
    service = PermissionService(store, cache_ttl=0)

    assert not service.can(
        subject,
        "docker.manage",
        Resource("container", "production", "*"),
    )
    assert service.can(
        subject,
        "docker.manage",
        Resource("container", "development", "*"),
    )


def test_explain_orders_denies_before_allows(tmp_path: Path):
    store = repository(tmp_path)
    allow_role = create_role(store, "Allow docker", [{"permission": "docker.manage"}])
    deny_role = create_role(
        store,
        "Deny docker",
        [{"permission": "docker.manage", "effect": "deny"}],
    )
    subject = principal()
    store.assign_user_role(subject, allow_role, "pytest")
    store.assign_user_role(subject, deny_role, "pytest")
    decision = PermissionService(store, cache_ttl=0).explain(subject, "docker.manage")

    assert not decision.allowed
    assert decision.reason == "explicit deny overrides allow"
    assert [source.effect for source in decision.sources] == ["deny", "allow"]


def test_authorize_returns_machine_readable_denial(tmp_path: Path):
    service = PermissionService(repository(tmp_path), cache_ttl=0)

    with pytest.raises(HTTPException) as error:
        service.authorize(principal(), "files.read")

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "PERMISSION_REQUIRED"
    assert error.value.detail["result"] == "DENY"
    assert error.value.detail["permission"] == "files.read"
    assert error.value.detail["reason"].startswith("default deny")


def test_cache_key_isolated_by_auth_provider(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "LDAP-only", [{"permission": "files.read"}])
    ldap_user = principal("jan", "ldap", "shared-id")
    pam_user = principal("jan", "pam", "shared-id")
    store.assign_user_role(ldap_user, role_id, "pytest")
    service = PermissionService(store, cache_ttl=60)

    assert service.can(ldap_user, "files.read")
    assert not service.can(pam_user, "files.read")


def test_user_role_assignment_is_idempotent(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "One assignment", [{"permission": "files.read"}])
    subject = principal()

    store.assign_user_role(subject, role_id, "pytest")
    store.assign_user_role(subject, role_id, "pytest")

    sources = PermissionService(store, cache_ttl=0).sources(subject)
    grants = [
        source
        for source in sources
        if source.source_type == "direct-role" and source.permission == "files.read"
    ]
    assert len(grants) == 1


def test_external_group_mapping_is_idempotent(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Mapped once", [{"permission": "files.read"}])
    group_id = store.upsert_external_group(
        "ldap",
        "g1",
        "CN=Readers,DC=example",
        "Readers",
    )
    store.map_external_group_role(group_id, role_id, "pytest")
    store.map_external_group_role(group_id, role_id, "pytest")
    subject = principal("jan", "ldap", "u1")
    store.replace_external_memberships("ldap", "u1", "jan", {group_id})

    grants = [
        source
        for source in PermissionService(store, cache_ttl=0).sources(subject)
        if source.source_type == "ldap-group" and source.permission == "files.read"
    ]
    assert len(grants) == 1


def test_audit_records_actor_action_target_and_source_ip(tmp_path: Path):
    store = repository(tmp_path)
    role_id = create_role(store, "Audited role", [{"permission": "files.read"}])
    store.update_role(
        role_id,
        {"description": "changed"},
        "alice",
        "192.0.2.10",
    )

    entry = store.audit(1)[0]
    assert entry["actor"] == "alice"
    assert entry["action"] == "role.update"
    assert entry["target"] == role_id
    assert entry["source_ip"] == "192.0.2.10"
    assert json.loads(entry["after_json"])["description"] == "changed"


@pytest.mark.parametrize(("requested", "expected"), [(0, 1), (-50, 1), (5000, 1000)])
def test_audit_limit_is_clamped(tmp_path: Path, requested: int, expected: int):
    store = repository(tmp_path)
    for index in range(3):
        create_role(store, f"Audit {index}", [{"permission": "files.read"}])

    rows = store.audit(requested)
    assert len(rows) == min(3, expected)
