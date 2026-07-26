from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from app.modules.ansible_controller.models import CredentialInput as LegacyCredentialInput
from app.modules.ansible_controller.models import CredentialType as LegacyCredentialType
from app.modules.ansible_controller.models import GroupInput as LegacyGroupInput
from app.modules.ansible_controller.models import HostInput as LegacyHostInput
from app.modules.ansible_controller.repository import AnsibleRepository
from app.modules.hosts_manager.models import (
    CredentialInput, CredentialType, EnrollmentTokenInput, HostInput, HostsManagerSettingsUpdate,
)
from app.modules.hosts_manager.service import SCHEMA_VERSION, HostCapabilityProvider, HostRegistryService
from app.modules.hosts_manager import router as hosts_router
from app.security import create_session


def service(tmp_path: Path) -> HostRegistryService:
    return HostRegistryService(tmp_path / "hosts-manager" / "hosts.sqlite3", tmp_path / "secrets" / "hosts-manager.key", tmp_path / "missing.sqlite3")


def test_crud_validation_and_secret_free_connection_metadata(tmp_path: Path):
    store = service(tmp_path)
    credential = store.save_credential(CredentialInput(name="SSH", type=CredentialType.ssh_password, username="ops", secret="correct horse"), "admin")
    assert credential["secret_configured"] is True
    assert "secret" not in credential and "encrypted_secret" not in credential
    host = store.save_host(HostInput(name="node-01", address="192.168.20.10", credential_id=credential["id"]), "admin")
    assert host["id"] and host["approved"] is False
    assert store.connection_data(host["id"])["credential"]["secret_configured"] is True
    assert store.verified_credential(credential["id"], module_id="ansible-controller", purpose="ssh")["secret"] == "correct horse"
    with sqlite3.connect(store.path) as connection:
        envelope = connection.execute("SELECT encrypted_secret FROM credentials").fetchone()[0]
    assert "correct horse" not in envelope
    with pytest.raises(ValueError):
        HostInput(name="bad", address="127.0.0.1")
    with pytest.raises(ValueError):
        HostInput(name="bad", address="192.168.1.2", variables={"password": "secret"})


def test_enrollment_token_is_hashed_one_time_bounded_and_hostname_scoped(tmp_path: Path):
    store = service(tmp_path)
    created = store.create_enrollment_token(EnrollmentTokenInput(expires_minutes=1), "admin")
    token = created["token"]
    with sqlite3.connect(store.path) as connection:
        row = connection.execute("SELECT token_hash FROM enrollment_tokens WHERE id=?", (created["id"],)).fetchone()
    assert row and row[0] != token and token not in store.path.read_bytes().decode("latin-1")
    assert store.claim_enrollment_token(token, {"hostname": "wrong-01", "address": "192.168.1.8"}) is None
    host = store.claim_enrollment_token(token, {"hostname": created["assigned_hostname"], "address": "192.168.1.8"})
    assert host and host["approved"] is False and host["fingerprint_status"] == "unverified"
    assert store.claim_enrollment_token(token, {"hostname": "edge-01", "address": "192.168.1.8"}) is None


def test_hostname_settings_default_persistence_and_existing_high_number(tmp_path: Path):
    store = service(tmp_path)
    assert store.settings()["hostname_template"] == "SCL000XXX"
    assert store.settings()["next_hostname"] == "SCL000001"
    store.save_host(HostInput(name="SCL000007", hostname="SCL000007", address="192.168.1.7"), "admin")
    assert store.settings()["next_hostname"] == "SCL000008"
    _, updated = store.save_settings(
        HostsManagerSettingsUpdate(hostname_template="SRV-XXXX", bootstrap_default_os="windows"),
        "admin",
    )
    assert updated["next_hostname"] == "SRV-0001"
    restarted = service(tmp_path)
    assert restarted.settings()["hostname_template"] == "SRV-XXXX"
    assert restarted.settings()["bootstrap_default_os"] == "windows"


def test_hostname_reservations_are_monotonic_concurrent_and_never_reused(tmp_path: Path):
    store = service(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        created = list(pool.map(lambda _: store.create_enrollment_token(EnrollmentTokenInput(), "admin"), range(3)))
    assert sorted(item["assigned_hostname"] for item in created) == ["SCL000001", "SCL000002", "SCL000003"]
    store.revoke_enrollment_token(created[0]["id"], "admin")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE enrollment_tokens SET expires_at=0 WHERE id=?", (created[1]["id"],))
    fourth = store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    assert fourth["assigned_hostname"] == "SCL000004"


@pytest.mark.parametrize("template", ["SCL", "XX-XX", "-XXX", "XXX-", "A X", "A_XXX", "A-XXXXXXXXXX"])
def test_invalid_hostname_templates_are_rejected(template: str):
    with pytest.raises(ValueError):
        HostsManagerSettingsUpdate(hostname_template=template)


def test_sequence_exhaustion_and_legacy_glob_compatibility(tmp_path: Path):
    store = service(tmp_path)
    store.save_settings(HostsManagerSettingsUpdate(hostname_template="NODE-X"), "admin")
    for _ in range(9):
        store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    with pytest.raises(OverflowError):
        store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    now = 9_999_999_999
    raw = "legacy-token"
    with store.connect() as connection:
        connection.execute(
            """INSERT INTO enrollment_tokens(
                id,token_hash,hostname_pattern,ssh_user,port,expires_at,created_at,updated_at,created_by,updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("legacy", __import__("hashlib").sha256(raw.encode()).hexdigest(), "legacy-*", "root", 22, now, 1, 1, "old", "old"),
        )
    assert store.claim_enrollment_token(raw, {"hostname": "LEGACY-01", "address": "192.168.1.20"})


def test_schema_migration_and_linux_windows_bootstrap(tmp_path: Path):
    database = tmp_path / "hosts-manager" / "hosts.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE enrollment_tokens(
            id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, hostname_pattern TEXT NOT NULL,
            ssh_user TEXT NOT NULL, port INTEGER NOT NULL, credential_id TEXT, environment TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]', group_ids_json TEXT NOT NULL DEFAULT '[]',
            require_approval INTEGER NOT NULL DEFAULT 1, onboard_ansible INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL,
            used_at REAL, used_hostname TEXT NOT NULL DEFAULT '', revoked_at REAL, created_at REAL NOT NULL,
            updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    store = service(tmp_path)
    with sqlite3.connect(store.path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(enrollment_tokens)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"assigned_hostname", "bootstrap_os", "apply_hostname", "reported_hostname"} <= columns
    assert version == SCHEMA_VERSION
    linux = store.create_enrollment_token(EnrollmentTokenInput(bootstrap_os="linux"), "admin")
    linux_script, _ = store.enrollment_script(linux["token"], "https://webnas.example")
    assert linux_script.startswith("#!/usr/bin/env bash")
    assert "--tlsv1.2" in linux_script and "hostnamectl set-hostname" in linux_script and "eval" not in linux_script
    windows = store.create_enrollment_token(EnrollmentTokenInput(bootstrap_os="windows"), "admin")
    windows_script, _ = store.enrollment_script(windows["token"], "https://webnas.example")
    assert "#Requires -Version 5.1" in windows_script
    assert "Invoke-RestMethod" in windows_script and "ConvertTo-Json" in windows_script
    assert "Invoke-Expression" not in windows_script


def test_bootstrap_script_endpoint_uses_bearer_without_admin_session_and_rejects_inactive_tokens(monkeypatch, tmp_path: Path):
    store = service(tmp_path)
    monkeypatch.setattr(hosts_router, "_service", lambda: store)
    app = FastAPI()
    app.include_router(hosts_router.router)
    client = TestClient(app)

    active = store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    response = client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {active['token']}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("#!/usr/bin/env bash")
    assert client.get("/api/modules/hosts-manager/enrollment-script").status_code == 401

    revoked = store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    store.revoke_enrollment_token(revoked["id"], "admin")
    assert client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {revoked['token']}"},
    ).status_code == 401

    expired = store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE enrollment_tokens SET expires_at=0 WHERE id=?", (expired["id"],))
    assert client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {expired['token']}"},
    ).status_code == 401

    used = store.create_enrollment_token(EnrollmentTokenInput(), "admin")
    assert store.claim_enrollment_token(
        used["token"],
        {"hostname": used["assigned_hostname"], "address": "192.168.1.88"},
    )
    assert client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {used['token']}"},
    ).status_code == 401


def test_settings_update_route_requires_configure_permission_and_csrf(monkeypatch):
    route = next(
        item for item in hosts_router.router.routes
        if item.path.endswith("/settings") and "PUT" in item.methods
    )
    dependency = route.dependant.dependencies[0].call
    response = Response()
    csrf = create_session(response, "operator")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    request = Request({
        "type": "http",
        "method": "PUT",
        "path": route.path,
        "headers": [
            (b"cookie", cookie.encode("latin-1")),
            (b"x-csrf-token", csrf.encode("latin-1")),
        ],
    })
    monkeypatch.setattr("app.identity.permissions.has_permission", lambda username, permission: False)
    with pytest.raises(HTTPException) as error:
        dependency(request)
    assert error.value.status_code == 403
    monkeypatch.setattr(
        "app.identity.permissions.has_permission",
        lambda username, permission: permission == "hosts-manager.configure",
    )
    assert dependency(request).username == "operator"


def test_migration_is_idempotent_and_preserves_ids_groups_facts_keys_and_credentials(tmp_path: Path):
    legacy_path = tmp_path / "ansible-controller" / "controller.sqlite3"
    legacy = AnsibleRepository(legacy_path, tmp_path / "secrets" / "ansible-controller.key")
    credential = legacy.save_credential(LegacyCredentialInput(name="SSH", type=LegacyCredentialType.ssh_password, username="ops", secret="secret"), "admin")
    host = legacy.save_host(LegacyHostInput(name="node-01", address="10.20.30.40", credential_id=credential["id"]), "admin")
    group = legacy.save_group(LegacyGroupInput(name="production", host_ids=[host["id"]]), "admin")
    legacy.accept_known_key(host["id"], host["address"], 22, "ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIKnownKey", "SHA256:aaaaaaaaaaaaaaaaaaaaaa", "admin")
    legacy.save_facts(host["id"], "admin", {"system": "Linux", "machine_id": "machine-secret"})
    target = HostRegistryService(tmp_path / "hosts-manager" / "hosts.sqlite3", tmp_path / "secrets" / "hosts-manager.key", legacy_path)
    migrated = target.host(host["id"])
    assert migrated and migrated["id"] == host["id"]
    assert group["id"] in migrated["group_ids"]
    assert target.host_keys(host["id"])[0]["fingerprint"].startswith("SHA256:")
    assert target.verified_credential(credential["id"], module_id="test", purpose="migration")["secret"] == "secret"
    assert list((tmp_path / "hosts-manager" / "backups").glob("ansible-controller-pre-migration-*.sqlite3"))
    second = HostRegistryService(tmp_path / "hosts-manager" / "hosts.sqlite3", tmp_path / "secrets" / "hosts-manager.key", legacy_path)
    assert second.migrate_ansible_controller() == {}
    assert len(second.list_hosts()) == 1


def test_capabilities_are_real_registered_and_host_scoped(tmp_path: Path):
    store = service(tmp_path)
    pending = store.save_host(HostInput(name="pending", address="192.168.1.10"), "admin")
    active = store.save_host(HostInput(name="active", address="192.168.1.11", approved=True), "admin")
    store.register_capability(HostCapabilityProvider("sample.inspect", "Inspect", "info", "sample.view", "sample", lambda host: bool(host["approved"]), lambda host, params, actor: {"host_id": host["id"]}, lambda host, params, actor: {"ok": True}))
    assert store.capabilities(pending["id"]) == []
    assert store.capabilities(active["id"])[0]["id"] == "sample.inspect"


def test_facts_are_allowlisted_and_machine_id_is_hashed(tmp_path: Path):
    store = service(tmp_path)
    host = store.save_host(HostInput(name="node", address="192.168.1.12"), "admin")
    facts = store.save_facts(host["id"], {"system": "Linux", "machine_id": "raw-id", "password": "must-not-survive", "arbitrary": "drop"}, "admin")
    assert facts["system"] == "Linux"
    assert facts["machine_id_hash"] != "raw-id"
    assert "password" not in json.dumps(facts) and "arbitrary" not in facts
