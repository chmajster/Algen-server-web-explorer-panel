from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.modules.ansible_controller.models import CredentialInput as LegacyCredentialInput
from app.modules.ansible_controller.models import CredentialType as LegacyCredentialType
from app.modules.ansible_controller.models import GroupInput as LegacyGroupInput
from app.modules.ansible_controller.models import HostInput as LegacyHostInput
from app.modules.ansible_controller.repository import AnsibleRepository
from app.modules.hosts_manager.models import CredentialInput, CredentialType, EnrollmentTokenInput, HostInput
from app.modules.hosts_manager.service import HostCapabilityProvider, HostRegistryService


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
    created = store.create_enrollment_token(EnrollmentTokenInput(hostname_pattern="edge-*", expires_minutes=1), "admin")
    token = created["token"]
    with sqlite3.connect(store.path) as connection:
        row = connection.execute("SELECT token_hash FROM enrollment_tokens WHERE id=?", (created["id"],)).fetchone()
    assert row and row[0] != token and token not in store.path.read_bytes().decode("latin-1")
    assert store.claim_enrollment_token(token, {"hostname": "wrong-01", "address": "192.168.1.8"}) is None
    host = store.claim_enrollment_token(token, {"hostname": "edge-01", "address": "192.168.1.8"})
    assert host and host["approved"] is False and host["fingerprint_status"] == "unverified"
    assert store.claim_enrollment_token(token, {"hostname": "edge-01", "address": "192.168.1.8"}) is None


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
