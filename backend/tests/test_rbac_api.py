from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.rbac as rbac
from app.identity.permission_service import PermissionRepository, PermissionService, Resource
from app.identity.permissions import Permission
from app.security import SessionUser


def principal(
    username: str = "admin",
    provider: str = "pam",
    identity_id: str = "",
) -> SessionUser:
    return SessionUser(
        username=username,
        csrf_token="csrf-token",
        auth_provider=provider,
        identity_id=identity_id or username,
    )


def build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    user: SessionUser | None = None,
    role_permissions: list[dict] | None = None,
    csrf: Callable | None = None,
) -> tuple[TestClient, PermissionRepository, PermissionService, list[tuple[str, str]]]:
    subject = user or principal()
    store = PermissionRepository(tmp_path / "identity.sqlite3")
    if role_permissions is None:
        role_id = "system:administrator"
    else:
        role_id = store.create_role(
            {
                "name": "API test role",
                "permissions": role_permissions,
            },
            "pytest",
        )["id"]
    store.assign_user_role(subject, role_id, "pytest")
    service = PermissionService(store, cache_ttl=0)

    csrf_calls: list[tuple[str, str]] = []

    def csrf_recorder(request, session_user):
        csrf_calls.append((request.method, session_user.username))
        if csrf is not None:
            csrf(request, session_user)

    monkeypatch.setattr(rbac, "permission_service", lambda: service)
    monkeypatch.setattr(rbac, "get_session_user", lambda _request: subject)
    monkeypatch.setattr(rbac, "require_csrf", csrf_recorder)
    monkeypatch.setattr(rbac, "_migrate_legacy_assignment", lambda _user: False)

    app = FastAPI()
    app.include_router(rbac.router)
    return TestClient(app), store, service, csrf_calls


def test_read_endpoint_requires_permission_but_not_csrf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.get("/api/rbac/roles")

    assert response.status_code == 200
    assert any(item["id"] == "system:administrator" for item in response.json()["items"])
    assert csrf_calls == []


def test_mutating_endpoint_requires_csrf_and_invalidates_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, service, csrf_calls = build_client(monkeypatch, tmp_path)
    service.sources(principal())
    assert service._cache

    response = client.post(
        "/api/rbac/roles",
        json={
            "name": "Created through API",
            "permissions": [{"permission": "files.read"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Created through API"
    assert csrf_calls == [("POST", "admin")]
    assert service._cache == {}


def test_invalid_csrf_rejects_mutation_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    def reject_csrf(_request, _user):
        raise HTTPException(403, detail={"code": "INVALID_CSRF_TOKEN"})

    client, store, _service, csrf_calls = build_client(
        monkeypatch,
        tmp_path,
        csrf=reject_csrf,
    )

    response = client.post(
        "/api/rbac/roles",
        json={"name": "Must not exist", "permissions": []},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INVALID_CSRF_TOKEN"
    assert csrf_calls == [("POST", "admin")]
    assert all(role["name"] != "Must not exist" for role in store.roles())


def test_read_only_principal_can_read_but_cannot_mutate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, csrf_calls = build_client(
        monkeypatch,
        tmp_path,
        user=principal("reader"),
        role_permissions=[{"permission": "access.view"}],
    )

    assert client.get("/api/rbac/roles").status_code == 200

    response = client.post(
        "/api/rbac/roles",
        json={"name": "Forbidden", "permissions": []},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_REQUIRED"
    assert csrf_calls == [("POST", "reader")]


def test_me_endpoint_works_without_rbac_admin_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    subject = principal("plain-user")
    store = PermissionRepository(tmp_path / "identity.sqlite3")
    service = PermissionService(store, cache_ttl=0)
    monkeypatch.setattr(rbac, "permission_service", lambda: service)
    monkeypatch.setattr(rbac, "get_session_user", lambda _request: subject)
    monkeypatch.setattr(rbac, "_migrate_legacy_assignment", lambda _user: False)

    app = FastAPI()
    app.include_router(rbac.router)
    response = TestClient(app).get("/api/rbac/me")

    assert response.status_code == 200
    assert response.json()["user"] == {
        "username": "plain-user",
        "provider": "pam",
        "identity_id": "plain-user",
    }
    assert response.json()["allowed"] == []
    assert response.json()["denied"] == []


def test_assign_user_role_rejects_username_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/rbac/users/jan/roles",
        json={
            "username": "anna",
            "auth_provider": "pam",
            "identity_id": "anna",
            "role_id": "system:user",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Username does not match route"


def test_role_payload_validation_rejects_empty_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/rbac/roles",
        json={"name": "", "permissions": []},
    )

    assert response.status_code == 422


def test_group_payload_validation_rejects_unknown_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/rbac/groups",
        json={"name": "Invalid source", "source": "saml"},
    )

    assert response.status_code == 422


def test_policy_payload_validation_rejects_unknown_subject_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/rbac/policies",
        json={
            "name": "Invalid subject",
            "permission": "files.read",
            "subjects": [{"subject_type": "role", "subject_id": "x"}],
        },
    )

    assert response.status_code == 422


def test_api_cannot_delete_protected_system_role(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.delete("/api/rbac/roles/system:administrator")

    assert response.status_code == 409
    assert response.json()["detail"] == "System role is protected"


def test_duplicate_system_role_creates_editable_custom_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.post("/api/rbac/roles/system:auditor/duplicate", json={})

    assert response.status_code == 200
    copied = response.json()
    assert copied["name"] == "Auditor Copy"
    assert copied["role_type"] == "custom"
    assert copied["protected"] == 0
    assert copied["permissions"]


def test_simulate_returns_deny_precedence_for_resource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, store, _service, csrf_calls = build_client(monkeypatch, tmp_path)
    target = principal("jan")
    role = store.create_role(
        {
            "name": "Target docker role",
            "permissions": [
                {"permission": "docker.manage", "effect": "allow"},
                {
                    "permission": "docker.manage",
                    "effect": "deny",
                    "resource_type": "container",
                    "resource_id": "prod",
                },
            ],
        },
        "pytest",
    )
    store.assign_user_role(target, role["id"], "pytest")

    response = client.post(
        "/api/rbac/simulate",
        json={
            "username": "jan",
            "auth_provider": "pam",
            "identity_id": "jan",
            "permission": "docker.manage",
            "resource_type": "container",
            "resource_id": "prod",
            "scope": "*",
        },
    )

    assert response.status_code == 200
    assert response.json()["result"] == "DENY"
    assert response.json()["reason"] == "explicit deny overrides allow"
    assert csrf_calls == []


def test_simulate_rejects_unknown_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, _store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/rbac/simulate",
        json={
            "username": "jan",
            "permission": "unknown.permission",
        },
    )

    assert response.status_code == 422


def test_effective_permissions_keep_provider_identity_isolated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    client, store, _service, _csrf_calls = build_client(monkeypatch, tmp_path)
    role = store.create_role(
        {"name": "LDAP files", "permissions": [{"permission": "files.read"}]},
        "pytest",
    )
    store.assign_user_role(principal("jan", "ldap", "guid-jan"), role["id"], "pytest")

    ldap_response = client.get(
        "/api/rbac/users/jan/effective-permissions",
        params={"auth_provider": "ldap", "identity_id": "guid-jan"},
    )
    pam_response = client.get(
        "/api/rbac/users/jan/effective-permissions",
        params={"auth_provider": "pam", "identity_id": "jan"},
    )

    assert ldap_response.status_code == 200
    assert "files.read" in ldap_response.json()["allowed"]
    assert pam_response.status_code == 200
    assert "files.read" not in pam_response.json()["allowed"]


@pytest.mark.parametrize(
    ("module_id", "operation", "expected"),
    [
        ("ansible-controller", "view", Permission.ANSIBLE_VIEW.value),
        ("ansible-controller", "install", Permission.ANSIBLE_INSTALL.value),
        ("ansible-controller", "backup", Permission.ANSIBLE_BACKUP.value),
        ("ansible-controller", "restore", Permission.ANSIBLE_RESTORE.value),
        ("ansible-controller", "configure", Permission.ANSIBLE_CONFIGURE.value),
        ("linux-updates", "view", Permission.UPDATES_VIEW.value),
        ("linux-updates", "operate", Permission.UPDATES_APPLY.value),
        ("docker", "view", Permission.DOCKER_VIEW.value),
        ("docker", "configure", Permission.DOCKER_COMPOSE.value),
        ("docker", "operate", Permission.DOCKER_CONTAINERS.value),
        ("pihole", "view", Permission.DNS_VIEW.value),
        ("adguard-home", "operate", Permission.DNS_CONFIGURE.value),
        ("postgresql", "backup", Permission.DATABASES_BACKUP.value),
        ("mariadb", "restore", Permission.DATABASES_RESTORE.value),
        ("redis", "configure", Permission.DATABASES_CONFIGURE.value),
        ("home-assistant", "view", Permission.HOMEASSISTANT_VIEW.value),
        ("home-assistant", "operate", Permission.HOMEASSISTANT_OPERATE.value),
        ("custom-module", "install", Permission.MODULES_INSTALL.value),
        ("custom-module", "reinstall", Permission.MODULES_UPDATE.value),
        ("custom-module", "backup_delete", Permission.MODULES_BACKUP_DELETE.value),
        ("custom-module", "logs", Permission.MODULES_LOGS.value),
        ("custom-module", "diagnostics", Permission.MODULES_DIAGNOSTICS.value),
    ],
)
def test_module_permission_mapping(
    module_id: str,
    operation: str,
    expected: str,
):
    assert rbac.module_permission(module_id, operation) == expected


def test_resource_object_is_forwarded_by_authorization_service(tmp_path: Path):
    store = PermissionRepository(tmp_path / "identity.sqlite3")
    role = store.create_role(
        {
            "name": "Scoped",
            "permissions": [
                {
                    "permission": "files.edit",
                    "resource_type": "files",
                    "resource_id": "home",
                    "scope": "/home/admin",
                }
            ],
        },
        "pytest",
    )
    subject = principal()
    store.assign_user_role(subject, role["id"], "pytest")
    service = PermissionService(store, cache_ttl=0)

    service.authorize(subject, "files.edit", Resource("files", "home", "/home/admin/docs"))

    with pytest.raises(HTTPException):
        service.authorize(subject, "files.edit", Resource("files", "home", "/home/other"))
