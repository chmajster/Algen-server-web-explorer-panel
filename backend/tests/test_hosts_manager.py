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
    AgentReportInput,
    ApmidInput,
    CredentialInput,
    CredentialType,
    EnrollmentTokenInput,
    EnvironmentInput,
    GroupInput,
    HostInput,
    HostnamePatternInput,
    HostsManagerSettingsUpdate,
    SshOnboardingProbeInput,
)
from app.modules.hosts_manager.service import (
    SCHEMA_VERSION,
    HostCapabilityProvider,
    HostRegistryService,
    ManagedGroupConflictError,
    ManagedGroupProtectedError,
)
from app.modules.hosts_manager import agent as hosts_agent
from app.modules.hosts_manager import router as hosts_router
from app.security import create_session


def service(tmp_path: Path) -> HostRegistryService:
    return HostRegistryService(tmp_path / "hosts-manager" / "hosts.sqlite3", tmp_path / "secrets" / "hosts-manager.key", tmp_path / "missing.sqlite3")


def ensure_apmid(store: HostRegistryService, code: str = "APP") -> dict:
    existing = next((item for item in store.apmids() if item["code"] == code), None)
    return existing or store.save_apmid(ApmidInput(code=code), "admin")


def enrollment_input(store: HostRegistryService, **values) -> EnrollmentTokenInput:
    apmid = ensure_apmid(store)
    if values.get("mode", "one_time") == "one_time":
        values.setdefault("expires_minutes", 15)
    return EnrollmentTokenInput(apmid_id=apmid["id"], environment_id="default", **values)


def enrollment_api(monkeypatch, store: HostRegistryService) -> tuple[TestClient, dict[str, str]]:
    store.save_settings(HostsManagerSettingsUpdate(server_url="https://webnas.example"), "admin")
    monkeypatch.setattr(hosts_router, "_service", lambda: store)
    monkeypatch.setattr(hosts_router, "_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.identity.permissions.has_permission", lambda username, permission: True)
    application = FastAPI()
    application.include_router(hosts_router.router)
    response = Response()
    csrf = create_session(response, "admin")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    return TestClient(application), {"cookie": cookie, "x-csrf-token": csrf}


def enrollment_payload(selected_apmid_id: str, **overrides) -> dict:
    payload = {
        "agent_port": 8443,
        "apmid_id": selected_apmid_id,
        "apply_hostname": True,
        "bootstrap_os": "linux",
        "bound_address": "",
        "environment_id": "default",
        "expires_minutes": None,
        "group_ids": [],
        "hostname_pattern_id": None,
        "location": "",
        "mode": "permanent",
        "onboard_ansible": False,
        "report_interval_seconds": 300,
        "require_approval": True,
        "tags": [],
    }
    payload.update(overrides)
    return payload


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



def test_generic_credentials_are_module_scoped_and_secret_preserving(tmp_path: Path):
    store = service(tmp_path)
    credential = store.save_credential(
        CredentialInput(
            name="PVE Login", type=CredentialType.username_password, username="automation@pve",
            secret="s3cret", shared_with=["proxmox-manager"],
        ),
        "admin",
    )
    assert credential["shared_with"] == ["proxmox-manager"]
    assert credential["secret_configured"] is True
    with pytest.raises(PermissionError, match="not shared"):
        store.verified_credential(credential["id"], module_id="ansible-controller", purpose="ssh")
    assert store.verified_credential(credential["id"], module_id="proxmox-manager", purpose="proxmox-api")["secret"] == "s3cret"

    updated = store.save_credential(
        CredentialInput(
            name="PVE Login", type=CredentialType.username_password, username="automation@pve",
            secret="", shared_with=["proxmox-manager", "dcst"],
        ),
        "admin", credential["id"],
    )
    assert updated["shared_with"] == ["proxmox-manager", "dcst"]
    assert store.verified_credential(credential["id"], module_id="proxmox-manager", purpose="proxmox-api")["secret"] == "s3cret"

def test_enrollment_token_is_hashed_one_time_bounded_and_hostname_scoped(tmp_path: Path):
    store = service(tmp_path)
    created = store.create_enrollment_token(enrollment_input(store, expires_minutes=1), "admin")
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
    ensure_apmid(store)
    with ThreadPoolExecutor(max_workers=3) as pool:
        created = list(pool.map(lambda _: store.create_enrollment_token(enrollment_input(store), "admin"), range(3)))
    assert sorted(item["assigned_hostname"] for item in created) == ["SCL000001", "SCL000002", "SCL000003"]
    store.revoke_enrollment_token(created[0]["id"], "admin")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE enrollment_tokens SET expires_at=0 WHERE id=?", (created[1]["id"],))
    fourth = store.create_enrollment_token(enrollment_input(store), "admin")
    assert fourth["assigned_hostname"] == "SCL000004"


def test_environments_store_defaults_and_cannot_be_removed_with_assigned_hosts(tmp_path: Path):
    store = service(tmp_path)
    pattern = store.save_hostname_pattern(
        HostnamePatternInput(name="Production", prefix="PRD-", digits=4),
        "admin",
    )
    credential = store.save_credential(
        CredentialInput(
            name="Production SSH",
            type=CredentialType.ssh_private_key,
            username="ops",
            secret="-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----",
        ),
        "admin",
    )
    environment = store.save_environment(
        EnvironmentInput(
            name="Production",
            slug="production",
            color="#c2410c",
            default_hostname_pattern_id=pattern["id"],
            default_credential_id=credential["id"],
            default_agent_port=9443,
            report_interval_seconds=600,
        ),
        "admin",
    )
    host = store.save_host(
        HostInput(
            name="prd-existing",
            address="10.10.0.15",
            environment=environment["id"],
        ),
        "admin",
    )
    saved = next(item for item in store.environments() if item["id"] == environment["id"])
    assert saved["host_count"] == 1
    assert saved["default_agent_port"] == 9443
    with pytest.raises(ValueError, match="assigned hosts"):
        store.delete_environment(environment["id"])
    with pytest.raises(ValueError, match="assigned"):
        store.delete_credential(credential["id"])
    assert store.host(host["id"])["environment_details"]["name"] == "Production"


def test_apmid_normalization_managed_groups_renames_and_idempotent_sync(tmp_path: Path):
    store = service(tmp_path)
    apmid = store.save_apmid(ApmidInput(code="  xyz  ", description="Application"), "admin")
    assert apmid["code"] == "XYZ"
    assert [item["group_name"] for item in apmid["environment_groups"]] == ["XYZ.DEFAULT"]
    with pytest.raises(ValueError):
        ApmidInput(code="XYZ.PROD")
    first_sync = store.sync_apmid_environment_groups("admin")
    second_sync = store.sync_apmid_environment_groups("admin")
    assert first_sync["created"] == second_sync["created"] == 0
    environment = store.save_environment(EnvironmentInput(name="Development", slug="dev"), "admin")
    assert {item["name"] for item in store.list_groups() if item["managed"]} == {"XYZ.DEFAULT", "XYZ.DEV"}
    store.save_apmid(ApmidInput(code="platform"), "admin", apmid["id"])
    store.save_environment(EnvironmentInput(name="Staging", slug="stage"), "admin", environment["id"])
    assert {item["name"] for item in store.list_groups() if item["managed"]} == {"PLATFORM.DEFAULT", "PLATFORM.STAGE"}
    assert store.sync_apmid_environment_groups("admin")["created"] == 0


def test_apmid_group_conflicts_are_transactional_and_managed_groups_are_protected(tmp_path: Path):
    store = service(tmp_path)
    apmid = store.save_apmid(ApmidInput(code="APP"), "admin")
    managed = next(item for item in store.list_groups() if item["managed"])
    with pytest.raises(ManagedGroupProtectedError):
        store.save_group(GroupInput(name="RENAMED"), "admin", managed["id"])
    with pytest.raises(ManagedGroupProtectedError):
        store.delete_group(managed["id"])
    with store.connect() as connection:
        connection.execute(
            """INSERT INTO groups(
                id,name,description,parent_id,variables_json,active,created_at,updated_at,created_by,updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("legacy-collision", "COLLISION.DEFAULT", "", None, "{}", 1, 1, 1, "old", "old"),
        )
    with pytest.raises(ManagedGroupConflictError):
        store.save_apmid(ApmidInput(code="collision"), "admin", apmid["id"])
    assert store.apmids()[0]["code"] == "APP"
    assert next(item for item in store.list_groups() if item["managed"])["name"] == "APP.DEFAULT"


def test_enrollment_requires_apmid_environment_and_assigns_managed_and_manual_groups(tmp_path: Path):
    store = service(tmp_path)
    apmid = ensure_apmid(store, "APP")
    other = ensure_apmid(store, "OTHER")
    manual = store.save_group(GroupInput(name="MANUAL"), "admin")
    groups = store.list_groups()
    managed = next(item for item in groups if (item.get("managed_by") or {}).get("apmid_id") == apmid["id"])
    other_managed = next(item for item in groups if (item.get("managed_by") or {}).get("apmid_id") == other["id"])
    created = store.create_enrollment_token(
        enrollment_input(store, group_ids=[manual["id"]]),
        "admin",
    )
    assert created["apmid_id"] == apmid["id"]
    assert created["environment_id"] == "default"
    assert created["managed_group_id"] == managed["id"]
    assert created["group_ids"] == [managed["id"], manual["id"]]
    listed = next(item for item in store.enrollment_tokens() if item["id"] == created["id"])
    assert listed["apmid_code"] == "APP"
    assert listed["environment_slug"] == "default"
    assert listed["managed_group_name"] == "APP.DEFAULT"
    with pytest.raises(ValueError, match="enrollment tokens"):
        store.delete_environment("default")
    with pytest.raises(ManagedGroupProtectedError):
        store.create_enrollment_token(enrollment_input(store, group_ids=[other_managed["id"]]), "admin")
    host = store.claim_enrollment_token(
        created["token"],
        {"hostname": created["assigned_hostname"], "address": "192.168.70.10"},
    )
    assert host and host["environment"] == "default"
    assert set(host["group_ids"]) == {managed["id"], manual["id"]}


def test_enrollment_rejects_inactive_entities_and_validates_token_expiration(tmp_path: Path):
    store = service(tmp_path)
    apmid = ensure_apmid(store)
    with pytest.raises(ValueError):
        EnrollmentTokenInput(apmid_id=apmid["id"], environment_id="default")
    permanent = EnrollmentTokenInput(
        mode="permanent",
        expires_minutes=60,
        apmid_id=apmid["id"],
        environment_id="default",
    )
    assert permanent.expires_minutes is None
    assert store.create_enrollment_token(permanent, "admin")["expires_at"] == 0
    store.save_apmid(ApmidInput(code=apmid["code"], active=False), "admin", apmid["id"])
    with pytest.raises(KeyError, match="APMID"):
        store.create_enrollment_token(
            EnrollmentTokenInput(
                expires_minutes=15,
                apmid_id=apmid["id"],
                environment_id="default",
            ),
            "admin",
        )
    active_apmid = store.save_apmid(ApmidInput(code=apmid["code"], active=True), "admin", apmid["id"])
    store.save_environment(EnvironmentInput(name="Default", slug="default", active=False), "admin", "default")
    with pytest.raises(KeyError, match="environment"):
        store.create_enrollment_token(
            EnrollmentTokenInput(
                expires_minutes=15,
                apmid_id=active_apmid["id"],
                environment_id="default",
            ),
            "admin",
        )


def test_enrollment_token_endpoint_accepts_canonical_permanent_and_one_time_payloads(monkeypatch, tmp_path: Path):
    store = service(tmp_path)
    apmid = ensure_apmid(store)
    client, headers = enrollment_api(monkeypatch, store)

    permanent = client.post(
        "/api/modules/hosts-manager/enrollment-tokens",
        json=enrollment_payload(apmid["id"]),
        headers=headers,
    )
    assert permanent.status_code == 200
    assert permanent.json()["apmid_id"] == apmid["id"]
    assert permanent.json()["expires_at"] == 0

    one_time = client.post(
        "/api/modules/hosts-manager/enrollment-tokens",
        json=enrollment_payload(apmid["id"], mode="one_time", expires_minutes=15),
        headers=headers,
    )
    assert one_time.status_code == 200
    assert one_time.json()["expires_at"] > one_time.json()["created_at"]


def test_enrollment_token_endpoint_rejects_legacy_app_id(monkeypatch, tmp_path: Path):
    store = service(tmp_path)
    apmid = ensure_apmid(store)
    client, headers = enrollment_api(monkeypatch, store)
    payload = enrollment_payload(apmid["id"])
    payload["app_id"] = payload.pop("apmid_id")

    response = client.post("/api/modules/hosts-manager/enrollment-tokens", json=payload, headers=headers)

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"][-1] == "apmid_id" and error["type"] == "missing" for error in errors)
    assert any(error["loc"][-1] == "app_id" and error["type"] == "extra_forbidden" for error in errors)


@pytest.mark.parametrize(
    ("overrides", "code", "field", "message"),
    [
        ({"apmid_id": "missing-apmid"}, "APMID_INACTIVE", "apmid_id", "The selected APMID does not exist or is inactive"),
        ({"environment_id": "missing-environment"}, "ENVIRONMENT_INACTIVE", "environment_id", "The selected environment does not exist or is inactive"),
        ({"hostname_pattern_id": "missing-pattern"}, "HOSTNAME_PATTERN_INACTIVE", "hostname_pattern_id", "The selected hostname pattern does not exist or is inactive"),
    ],
)
def test_enrollment_token_endpoint_returns_controlled_identifier_errors(monkeypatch, tmp_path: Path, overrides, code, field, message):
    store = service(tmp_path)
    apmid = ensure_apmid(store)
    client, headers = enrollment_api(monkeypatch, store)

    response = client.post(
        "/api/modules/hosts-manager/enrollment-tokens",
        json=enrollment_payload(apmid["id"], **overrides),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": code,
        "message": message,
        "field": field,
    }


def test_hostname_patterns_preview_skip_and_token_assignment_are_monotonic(tmp_path: Path):
    store = service(tmp_path)
    pattern = store.save_hostname_pattern(
        HostnamePatternInput(
            name="Edge",
            prefix="EDGE-",
            suffix="-PL",
            digits=3,
            start_value=7,
            step=2,
        ),
        "admin",
    )
    assert pattern["preview_hostnames"] == ["EDGE-007-PL", "EDGE-009-PL", "EDGE-011-PL"]
    skipped = store.skip_hostname_pattern(pattern["id"], 2, "reserved rack slots", "admin")
    assert skipped["skipped"] == ["EDGE-007-PL", "EDGE-009-PL"]
    created = store.create_enrollment_token(
        enrollment_input(store, hostname_pattern_id=pattern["id"]),
        "admin",
    )
    assert created["assigned_hostname"] == "EDGE-011-PL"
    current = next(item for item in store.hostname_patterns() if item["id"] == pattern["id"])
    assert current["last_value"] == 11


def test_registration_network_policy_and_ssh_onboarding_input_are_private(tmp_path: Path):
    store = service(tmp_path)
    store.save_settings(
        HostsManagerSettingsUpdate(allowed_registration_networks=["10.0.0.0/8"]),
        "admin",
    )
    blocked = store.create_enrollment_token(enrollment_input(store), "admin")
    assert store.claim_enrollment_token(
        blocked["token"],
        {"hostname": blocked["assigned_hostname"], "address": "192.168.50.10"},
    ) is None
    allowed = store.create_enrollment_token(enrollment_input(store), "admin")
    assert store.claim_enrollment_token(
        allowed["token"],
        {"hostname": allowed["assigned_hostname"], "address": "10.50.0.10"},
    )
    with pytest.raises(KeyError):
        store.save_settings(
            HostsManagerSettingsUpdate(default_hostname_pattern_id="missing"),
            "admin",
        )
    with pytest.raises(ValueError):
        SshOnboardingProbeInput(
            address="127.0.0.1",
            ssh_user="root",
            credential_id="a" * 32,
        )


def test_permanent_enrollment_token_is_reusable_and_honors_address_binding(tmp_path: Path):
    store = service(tmp_path)
    bound = store.create_enrollment_token(
        enrollment_input(
            store,
            mode="permanent",
            bound_address="192.168.40.20",
            agent_port=9443,
            report_interval_seconds=900,
        ),
        "admin",
    )
    assert bound["expires_at"] == 0
    assert store.claim_enrollment_token(
        bound["token"],
        {"hostname": "edge-wrong-address", "address": "192.168.40.21"},
    ) is None
    created = store.create_enrollment_token(
        enrollment_input(store, mode="permanent", agent_port=9443, report_interval_seconds=900),
        "admin",
    )
    first = store.claim_enrollment_token(
        created["token"],
        {
            "hostname": "edge-one",
            "address": "192.168.40.20",
            "installation_id": "install-edge-one",
            "agent_version": "1.2.0",
        },
    )
    second = store.claim_enrollment_token(
        created["token"],
        {"hostname": "edge-two", "address": "192.168.40.21"},
    )
    repeated = store.claim_enrollment_token(
        created["token"],
        {
            "hostname": "edge-one",
            "address": "192.168.40.20",
            "installation_id": "install-edge-one",
            "agent_version": "1.2.1",
        },
    )
    assert first and second and first["id"] != second["id"]
    assert repeated and repeated["id"] == first["id"]
    assert first["agent_credentials"]["token"]
    token_row = next(item for item in store.enrollment_tokens() if item["id"] == created["id"])
    assert token_row["mode"] == "permanent"
    assert token_row["use_count"] == 3
    assert token_row["used"] is False


def test_agent_identity_rotation_heartbeat_reports_and_invalidation(tmp_path: Path):
    store = service(tmp_path)
    store.save_settings(HostsManagerSettingsUpdate(max_auth_failures=2), "admin")
    host = store.save_host(
        HostInput(name="agent-node", address="10.20.30.40", approved=True),
        "admin",
    )
    paired = store.register_agent(host["id"], "install-123", "1.0.0", 8443, 300, "admin")
    heartbeat = store.agent_heartbeat(
        paired["agent_id"],
        paired["token"],
        {"agent_version": "1.0.1", "status": "online", "error": ""},
    )
    assert heartbeat and heartbeat["ok"] is True
    report = AgentReportInput(
        agent_id=paired["agent_id"],
        basic={"hostname": "agent-node", "uptime_seconds": 7200},
        hardware={"cpu": {"model": "Test CPU"}, "memory_bytes": 8_000_000_000},
        system={"cpu_percent": 12.5, "memory_percent": 40.0},
        packages={"manager": "apt", "available_updates_count": 3},
    )
    received = store.save_agent_report(
        paired["agent_id"],
        paired["token"],
        report.model_dump(exclude={"agent_id"}),
    )
    assert received and len(received["checksum"]) == 64
    assert store.host(host["id"])["latest_report"]["packages"]["manager"] == "apt"
    for _ in range(2):
        assert store.agent_heartbeat(
            paired["agent_id"],
            "invalid-agent-token",
            {"agent_version": "1.0.1", "status": "online", "error": ""},
        ) is None
    assert store.agent_heartbeat(
        paired["agent_id"],
        paired["token"],
        {"agent_version": "1.0.1", "status": "online", "error": ""},
    ) is None
    rotated = store.rotate_agent_identity(host["id"], "admin")
    assert store.agent_heartbeat(
        paired["agent_id"],
        paired["token"],
        {"agent_version": "1.0.1", "status": "online", "error": ""},
    ) is None
    assert store.agent_heartbeat(
        rotated["agent_id"],
        rotated["token"],
        {"agent_version": "1.0.2", "status": "online", "error": ""},
    )
    assert store.invalidate_agent_identity(host["id"], "admin") is True
    assert store.agent_heartbeat(
        rotated["agent_id"],
        rotated["token"],
        {"agent_version": "1.0.2", "status": "online", "error": ""},
    ) is None
    history = store.agent_history(host["id"])
    assert history["reports"] and all("salt" not in item for item in history["identities"])
    assert history["versions"] and history["versions"][0]["version"] == "1.0.2"
    with pytest.raises(ValueError):
        AgentReportInput(
            agent_id=paired["agent_id"],
            basic={"api_token": "must-never-be-reported"},
        )


@pytest.mark.parametrize("template", ["SCL", "XX-XX", "-XXX", "XXX-", "A X", "A_XXX", "A-XXXXXXXXXX"])
def test_invalid_hostname_templates_are_rejected(template: str):
    with pytest.raises(ValueError):
        HostsManagerSettingsUpdate(hostname_template=template)


def test_sequence_exhaustion_and_legacy_glob_compatibility(tmp_path: Path):
    store = service(tmp_path)
    store.save_settings(HostsManagerSettingsUpdate(hostname_template="NODE-X"), "admin")
    store.save_environment(
        EnvironmentInput(name="Default", slug="default", default_hostname_pattern_id=None),
        "admin",
        "default",
    )
    for _ in range(9):
        store.create_enrollment_token(enrollment_input(store), "admin")
    with pytest.raises(OverflowError):
        store.create_enrollment_token(enrollment_input(store), "admin")
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
        connection.execute(
            """INSERT INTO enrollment_tokens(
                id,token_hash,hostname_pattern,ssh_user,port,expires_at,created_at,updated_at,created_by,updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "pre-migration",
                __import__("hashlib").sha256(b"pre-migration-token").hexdigest(),
                "legacy-*",
                "root",
                22,
                9_999_999_999,
                1,
                1,
                "old",
                "old",
            ),
        )
    store = service(tmp_path)
    with sqlite3.connect(store.path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(enrollment_tokens)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        preserved = connection.execute("SELECT id FROM enrollment_tokens WHERE id='pre-migration'").fetchone()
    assert {"assigned_hostname", "bootstrap_os", "apply_hostname", "reported_hostname", "apmid_id", "environment_id", "managed_group_id"} <= columns
    assert {"apmids", "apmid_environment_groups"} <= tables
    assert preserved
    assert version == SCHEMA_VERSION
    assert store.claim_enrollment_token(
        "pre-migration-token",
        {"hostname": "LEGACY-MIGRATION", "address": "192.168.90.10"},
    )
    linux = store.create_enrollment_token(enrollment_input(store, bootstrap_os="linux"), "admin")
    linux_script, _ = store.enrollment_script(linux["token"], "https://webnas.example")
    assert linux_script.startswith("#!/usr/bin/env bash")
    assert "--tlsv1.2" in linux_script and "hostnamectl set-hostname" in linux_script and "eval" not in linux_script
    assert all(manager in linux_script for manager in ("apt-get", "dnf", "yum", "zypper", "pacman", "apk"))
    assert "hosts-manager-agent.service" in linux_script and "rc-update add hosts-manager-agent" in linux_script
    assert '"enrollment_token"' not in linux_script
    windows = store.create_enrollment_token(enrollment_input(store, bootstrap_os="windows"), "admin")
    windows_script, _ = store.enrollment_script(windows["token"], "https://webnas.example")
    assert "#Requires -Version 5.1" in windows_script
    assert "Invoke-RestMethod" in windows_script and "ConvertTo-Json" in windows_script
    assert "Invoke-Expression" not in windows_script


def test_ssh_onboarding_probe_parser_only_accepts_bounded_markers():
    parsed = hosts_router._parse_onboarding_probe(
        "\n".join(
            (
                "noise=ignored",
                "__HM_DISTRIBUTION__=ubuntu",
                "__HM_VERSION__=24.04",
                "__HM_PACKAGE_MANAGER__=apt",
                "__HM_INIT__=systemd",
                "__HM_PRIVILEGE__=sudo",
            )
        )
    )
    assert parsed == {
        "distribution": "ubuntu",
        "version": "24.04",
        "package_manager": "apt",
        "init": "systemd",
        "privilege": "sudo",
    }
    with pytest.raises(ValueError):
        SshOnboardingProbeInput(
            address="127.0.0.1",
            ssh_user="root",
            credential_id="ssh",
        )
    assert HostsManagerSettingsUpdate(server_url="http://webnas.example/").server_url == "http://webnas.example"
    with pytest.raises(ValueError):
        HostsManagerSettingsUpdate(server_url="ftp://webnas.example")


def test_installer_generation_requires_configured_public_http_endpoint(monkeypatch, tmp_path: Path):
    store = service(tmp_path)
    monkeypatch.setattr(hosts_router, "_service", lambda: store)
    with pytest.raises(HTTPException) as error:
        hosts_router._public_hosts_manager_endpoint()
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "PUBLIC_ENDPOINT_REQUIRED"
    assert store.enrollment_tokens() == []


@pytest.mark.parametrize("endpoint", ["http://webnas.example", "https://webnas.example"])
def test_installer_generation_supports_http_and_https(monkeypatch, tmp_path: Path, endpoint: str):
    store = service(tmp_path)
    store.save_settings(HostsManagerSettingsUpdate(server_url=endpoint), "admin")
    monkeypatch.setattr(hosts_router, "_service", lambda: store)

    assert hosts_router._public_hosts_manager_endpoint() == endpoint
    token = store.create_enrollment_token(enrollment_input(store), "admin")
    script, _ = store.enrollment_script(token["token"], endpoint)

    assert f"'{endpoint}/api/modules/hosts-manager/enroll'" in script
    if endpoint.startswith("http://"):
        assert "--proto '=http'" in script
        assert 'die "HTTPS is required"' not in script
    else:
        assert "--proto '=https' --tlsv1.2" in script


def test_http_installer_supports_windows_and_agent_requests(monkeypatch, tmp_path: Path):
    store = service(tmp_path)
    token = store.create_enrollment_token(enrollment_input(store, bootstrap_os="windows"), "admin")
    script, _ = store.enrollment_script(token["token"], "http://webnas.example")
    assert "StartsWith('http://')" in script
    assert "throw 'HTTPS is required.'" not in script

    config_path = tmp_path / "agent-config.json"
    state_path = tmp_path / "agent-state.json"
    config_path.write_text(json.dumps({"server": {"url": "http://webnas.example"}}), encoding="utf-8")
    state_path.write_text("{}", encoding="utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok": true}'

    requests = []
    monkeypatch.setattr(hosts_agent, "urlopen", lambda request, **kwargs: requests.append(request) or FakeResponse())
    result = hosts_agent.AgentClient(config_path, state_path)._request("/heartbeat", {}, "token")

    assert result == {"ok": True}
    assert requests[0].full_url == "http://webnas.example/heartbeat"


def test_bootstrap_script_endpoint_uses_bearer_without_admin_session_and_rejects_inactive_tokens(monkeypatch, tmp_path: Path):
    store = service(tmp_path)
    store.save_settings(
        HostsManagerSettingsUpdate(server_url="https://webnas.example"),
        "admin",
    )
    monkeypatch.setattr(hosts_router, "_service", lambda: store)
    app = FastAPI()
    app.include_router(hosts_router.router)
    client = TestClient(app)

    active = store.create_enrollment_token(enrollment_input(store), "admin")
    response = client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {active['token']}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("#!/usr/bin/env bash")
    assert client.get("/api/modules/hosts-manager/enrollment-script").status_code == 401

    revoked = store.create_enrollment_token(enrollment_input(store), "admin")
    store.revoke_enrollment_token(revoked["id"], "admin")
    assert client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {revoked['token']}"},
    ).status_code == 401

    expired = store.create_enrollment_token(enrollment_input(store), "admin")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE enrollment_tokens SET expires_at=0 WHERE id=?", (expired["id"],))
    assert client.get(
        "/api/modules/hosts-manager/enrollment-script",
        headers={"Authorization": f"Bearer {expired['token']}"},
    ).status_code == 401

    used = store.create_enrollment_token(enrollment_input(store), "admin")
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
    migrated_credential = next(item for item in target.credentials() if item["id"] == credential["id"])
    assert migrated_credential["shared_with"] == ["hosts-manager", "ansible-controller"]
    assert target.verified_credential(credential["id"], module_id="ansible-controller", purpose="migration")["secret"] == "secret"
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
