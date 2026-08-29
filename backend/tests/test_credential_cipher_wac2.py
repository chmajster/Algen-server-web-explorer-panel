from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest

from app.modules.ansible_controller.security import CredentialCipher
from scripts.migrate_credentials_wac2 import migrate


def test_new_credential_envelopes_use_wac2_aead(tmp_path: Path) -> None:
    cipher = CredentialCipher(tmp_path / "secrets" / "credential.key")

    envelope = cipher.encrypt("correct horse battery staple", associated_data="credential-1")
    raw = base64.urlsafe_b64decode(envelope.encode("ascii"))

    assert raw.startswith(b"WAC2")
    assert cipher.envelope_version(envelope) == "WAC2"
    assert cipher.needs_migration(envelope) is False
    assert cipher.decrypt(envelope, associated_data="credential-1") == "correct horse battery staple"


def test_wac2_fails_closed_for_wrong_associated_data_and_tampering(tmp_path: Path) -> None:
    cipher = CredentialCipher(tmp_path / "secrets" / "credential.key")
    envelope = cipher.encrypt("top-secret", associated_data="credential-2")

    with pytest.raises(ValueError, match="credential authentication failed"):
        cipher.decrypt(envelope, associated_data="credential-other")

    raw = bytearray(base64.urlsafe_b64decode(envelope.encode("ascii")))
    for offset in (4, 4 + cipher.NONCE_SIZE, len(raw) - 1):
        tampered = bytearray(raw)
        tampered[offset] ^= 0x01
        encoded = base64.urlsafe_b64encode(bytes(tampered)).decode("ascii")
        with pytest.raises(ValueError, match="credential authentication failed"):
            cipher.decrypt(encoded, associated_data="credential-2")


def test_wac1_remains_readable_and_migrates_without_changing_plaintext(tmp_path: Path) -> None:
    cipher = CredentialCipher(tmp_path / "secrets" / "credential.key")
    legacy = cipher._encrypt_wac1("legacy-secret", associated_data="credential-3")

    assert cipher.envelope_version(legacy) == "WAC1"
    assert cipher.needs_migration(legacy) is True
    assert cipher.decrypt(legacy, associated_data="credential-3") == "legacy-secret"

    migrated = cipher.migrate(legacy, associated_data="credential-3")
    assert migrated != legacy
    assert cipher.envelope_version(migrated) == "WAC2"
    assert cipher.decrypt(migrated, associated_data="credential-3") == "legacy-secret"
    assert cipher.migrate(migrated, associated_data="credential-3") == migrated


def test_encrypted_backup_roundtrip_uses_wac2(tmp_path: Path) -> None:
    cipher = CredentialCipher(tmp_path / "secrets" / "credential.key")
    payload = {"credential": "opaque", "items": [1, 2, 3]}

    envelope = cipher.export_encrypted(payload)

    assert cipher.envelope_version(envelope) == "WAC2"
    assert cipher.import_encrypted(envelope) == payload

    legacy = cipher._encrypt_wac1(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        associated_data="backup",
    )
    assert cipher.import_encrypted(legacy) == payload


def _credential_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE credentials("
            "id TEXT PRIMARY KEY, encrypted_secret TEXT NOT NULL, active INTEGER NOT NULL, updated_at REAL)"
        )
        connection.commit()
    finally:
        connection.close()


def test_controlled_database_migration_is_dry_run_by_default_and_creates_backup_on_apply(tmp_path: Path) -> None:
    database = tmp_path / "hosts.sqlite3"
    key_path = tmp_path / "secrets" / "credential.key"
    _credential_database(database)
    cipher = CredentialCipher(key_path)
    legacy = cipher._encrypt_wac1("legacy-db-secret", associated_data="legacy-id")
    current = cipher.encrypt("current-db-secret", associated_data="current-id")

    connection = sqlite3.connect(database)
    try:
        connection.executemany(
            "INSERT INTO credentials(id,encrypted_secret,active,updated_at) VALUES(?,?,1,0)",
            [("legacy-id", legacy), ("current-id", current)],
        )
        connection.commit()
    finally:
        connection.close()

    inspected, pending, backup = migrate(database, key_path, apply=False)
    assert (inspected, pending, backup) == (2, 1, None)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT encrypted_secret FROM credentials WHERE id='legacy-id'"
        ).fetchone()[0] == legacy
    finally:
        connection.close()

    inspected, pending, backup = migrate(database, key_path, apply=True)
    assert inspected == 2
    assert pending == 1
    assert backup is not None and backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600

    connection = sqlite3.connect(database)
    try:
        rows = dict(connection.execute("SELECT id,encrypted_secret FROM credentials").fetchall())
    finally:
        connection.close()

    assert cipher.envelope_version(rows["legacy-id"]) == "WAC2"
    assert cipher.decrypt(rows["legacy-id"], associated_data="legacy-id") == "legacy-db-secret"
    assert rows["current-id"] == current

    backup_connection = sqlite3.connect(backup)
    try:
        backup_rows = dict(
            backup_connection.execute("SELECT id,encrypted_secret FROM credentials").fetchall()
        )
    finally:
        backup_connection.close()
    assert backup_rows["legacy-id"] == legacy
