from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.ansible_controller.public_security import CredentialCipher
from app.modules.secrets_manager.models import SecretInput
from app.modules.secrets_manager import service as secrets_module
from app.modules.secrets_manager.service import SecretsManagerService


def _legacy_database(path: Path, *, credential_id: str, envelope: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE credentials(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                encrypted_secret TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                environment_id TEXT,
                shared_with_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                created_by TEXT NOT NULL,
                updated_by TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO credentials(
                id,name,type,username,description,encrypted_secret,active,environment_id,
                shared_with_json,created_at,updated_at,created_by,updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                credential_id,
                "legacy-ssh",
                "ssh_password",
                "root",
                "migrated credential",
                envelope,
                1,
                None,
                json.dumps(["hosts-manager", "ansible-controller"]),
                10.0,
                20.0,
                "admin",
                "admin",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _service_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data = tmp_path / "data"
    return (
        data / "secrets-manager" / "secrets.sqlite3",
        data / "secrets" / "secrets-manager.key",
        data / "hosts-manager" / "hosts.sqlite3",
        data / "secrets" / "hosts-manager.key",
    )


def _patch_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        secrets_module,
        "get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=tmp_path / "data")),
    )


def test_migrates_legacy_credentials_preserving_id_and_reencrypting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _patch_config(monkeypatch, tmp_path)
    new_db, new_key, hosts_db, hosts_key = _service_paths(tmp_path)
    credential_id = "cred-fixed-id"
    old_cipher = CredentialCipher(hosts_key)
    old_envelope = old_cipher.encrypt(
        json.dumps({"secret": "correct horse", "passphrase": "key pass"}),
        associated_data=credential_id,
    )
    _legacy_database(hosts_db, credential_id=credential_id, envelope=old_envelope)

    service = SecretsManagerService(
        path=new_db,
        key_path=new_key,
        hosts_path=hosts_db,
        hosts_key_path=hosts_key,
    )

    assert service.migration_error == ""
    assert service.migration_completed is True
    item = service.secret(credential_id)
    assert item is not None
    assert item["id"] == credential_id
    assert item["name"] == "legacy-ssh"
    assert item["secret_configured"] is True
    assert "correct horse" not in json.dumps(item)
    assert "encrypted_secret" not in item
    assert service.verified_secret(
        credential_id,
        module_id="hosts-manager",
        purpose="ssh-connect",
    )["secret"] == "correct horse"
    with pytest.raises(PermissionError):
        service.verified_secret(credential_id, module_id="webhook-manager", purpose="delivery")

    with service.connect() as connection:
        migrated_envelope = str(connection.execute(
            "SELECT encrypted_secret FROM secrets WHERE id=?",
            (credential_id,),
        ).fetchone()[0])
    assert migrated_envelope.startswith("WAC2:")
    assert migrated_envelope != old_envelope

    legacy = sqlite3.connect(hosts_db)
    try:
        assert legacy.execute(
            "SELECT encrypted_secret FROM credentials WHERE id=?",
            (credential_id,),
        ).fetchone()[0] == old_envelope
    finally:
        legacy.close()

    assert new_db.stat().st_mode & 0o777 == 0o600
    assert new_key.stat().st_mode & 0o777 == 0o600
    assert list((new_db.parent / "backups").glob("hosts-credentials-pre-migration-*.sqlite3"))

    second = SecretsManagerService(
        path=new_db,
        key_path=new_key,
        hosts_path=hosts_db,
        hosts_key_path=hosts_key,
    )
    assert second.migration_error == ""
    assert [item["id"] for item in second.secrets()] == [credential_id]


def test_failed_migration_rolls_back_destination_and_keeps_legacy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _patch_config(monkeypatch, tmp_path)
    new_db, new_key, hosts_db, hosts_key = _service_paths(tmp_path)
    credential_id = "broken-credential"
    _legacy_database(hosts_db, credential_id=credential_id, envelope="WAC2:not-a-valid-envelope")

    service = SecretsManagerService(
        path=new_db,
        key_path=new_key,
        hosts_path=hosts_db,
        hosts_key_path=hosts_key,
    )

    assert service.migration_error
    assert service.secrets() == []
    source = sqlite3.connect(hosts_db)
    try:
        assert source.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 1
        assert source.execute("SELECT encrypted_secret FROM credentials").fetchone()[0] == "WAC2:not-a-valid-envelope"
    finally:
        source.close()


def test_secret_create_update_audit_and_metadata_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _patch_config(monkeypatch, tmp_path)
    new_db, new_key, hosts_db, hosts_key = _service_paths(tmp_path)
    hosts_db.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(hosts_db).close()
    service = SecretsManagerService(
        path=new_db,
        key_path=new_key,
        hosts_path=hosts_db,
        hosts_key_path=hosts_key,
    )

    created = service.save(
        SecretInput(
            name="webhook-token",
            type="api_token",
            secret="top-secret-token",
            description="delivery auth",
            shared_with=["webhook-manager"],
            confirm=True,
        ),
        "admin",
    )
    assert created["secret_configured"] is True
    assert "top-secret-token" not in json.dumps(created)
    assert service.verified_secret(
        created["id"], module_id="webhook-manager", purpose="webhook-auth:test"
    )["secret"] == "top-secret-token"

    updated = service.save(
        SecretInput(
            name="webhook-token-renamed",
            type="api_token",
            secret="",
            description="updated metadata",
            shared_with=["webhook-manager"],
            confirm=True,
        ),
        "admin",
        created["id"],
    )
    assert updated["id"] == created["id"]
    assert service.verified_secret(
        created["id"], module_id="webhook-manager", purpose="webhook-auth:test-2"
    )["secret"] == "top-secret-token"
    actions = [item["action"] for item in service.audit(secret_id=created["id"])]
    assert "created" in actions
    assert "updated" in actions
    assert "used" in actions
