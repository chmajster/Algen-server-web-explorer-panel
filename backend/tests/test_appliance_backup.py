from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.appliance_backup import ApplianceBackupService, BackupValidationError
from app.config import AppConfig, PathsConfig, SecurityConfig, ServerConfig


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ApplianceBackupService, Path, Path]:
    data = tmp_path / "data"
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  host: 127.0.0.1\n", encoding="utf-8")
    monkeypatch.setenv("WEBNAS_CONFIG", str(config))
    app_config = AppConfig(
        server=ServerConfig(host="127.0.0.1"),
        paths=PathsConfig(data_dir=str(data), log_dir=str(tmp_path / "logs"), temp_dir=str(tmp_path / "tmp")),
        security=SecurityConfig(session_secret="test-session-secret"),
    )
    return ApplianceBackupService(app_config), data, config


def _create_sqlite(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _sqlite_value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT value FROM sample").fetchone()
        assert row is not None
        return str(row[0])
    finally:
        connection.close()


def test_backup_mutate_restore_round_trip_preserves_sqlite_config_and_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, data, config = _service(tmp_path, monkeypatch)
    database = data / "hosts-manager" / "hosts.sqlite3"
    key = data / "secrets" / "hosts-manager.key"
    session_db = data / "sessions.sqlite3"
    settings = data / "settings" / "preferences.json"

    _create_sqlite(database, "before")
    _create_sqlite(session_db, "session-before")
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"theme":"dark"}', encoding="utf-8")

    backup = service.create(label="roundtrip")
    archive = service.backup_root / backup["name"]
    assert archive.stat().st_mode & 0o777 == 0o600
    assert backup["valid"] is True
    assert backup["sessions_included"] is False

    database.unlink()
    _create_sqlite(database, "after")
    config.write_text("server:\n  host: changed\n", encoding="utf-8")
    key.write_bytes(b"x" * 32)
    settings.write_text('{"theme":"light"}', encoding="utf-8")
    session_db.unlink()
    _create_sqlite(session_db, "session-after")

    dry_run = service.restore(backup["name"], apply=False)
    assert dry_run["dry_run"] is True
    assert _sqlite_value(database) == "after"

    restored = service.restore(backup["name"], apply=True)
    assert restored["dry_run"] is False
    assert restored["safety_backup"].endswith(".webnas-backup.zip")
    assert _sqlite_value(database) == "before"
    assert config.read_text(encoding="utf-8") == "server:\n  host: 127.0.0.1\n"
    assert key.read_bytes() == b"k" * 32
    assert key.stat().st_mode & 0o777 == 0o600
    assert settings.read_text(encoding="utf-8") == '{"theme":"dark"}'
    assert _sqlite_value(session_db) == "session-after"


def test_corrupted_member_is_rejected_before_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, data, _config = _service(tmp_path, monkeypatch)
    database = data / "identity" / "identity.sqlite3"
    _create_sqlite(database, "safe")
    backup = service.create(label="corrupt")
    original = service.backup_root / backup["name"]
    corrupt = service.backup_root / "corrupt-copy.webnas-backup.zip"

    with zipfile.ZipFile(original, "r") as source, zipfile.ZipFile(corrupt, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename.endswith("identity.sqlite3"):
                payload += b"tamper"
            target.writestr(info, payload)

    with pytest.raises(BackupValidationError, match="checksum mismatch|size is invalid"):
        service.validate(corrupt.name)


def test_path_traversal_manifest_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, _data, _config = _service(tmp_path, monkeypatch)
    archive = service.backup_root / "unsafe.webnas-backup.zip"
    payload = b"secret"
    manifest = {
        "format": "webnas-appliance-backup",
        "format_version": 1,
        "created_at": 1,
        "source_version": "0.1.23",
        "minimum_restore_version": "0.1.0",
        "resources": [
            {
                "member": "payload/data/../../outside",
                "scope": "data",
                "relative_path": "../../outside",
                "kind": "file",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mode": 0o600,
            }
        ],
    }
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("manifest.json", json.dumps(manifest))
        target.writestr("payload/data/../../outside", payload)

    with pytest.raises(BackupValidationError, match="unsafe backup member path"):
        service.validate(archive.name)


def test_undeclared_zip_member_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, data, _config = _service(tmp_path, monkeypatch)
    database = data / "package-center" / "packages.sqlite3"
    _create_sqlite(database, "safe")
    backup = service.create(label="extra")
    original = service.backup_root / backup["name"]
    rewritten = service.backup_root / "extra-copy.webnas-backup.zip"

    with zipfile.ZipFile(original, "r") as source, zipfile.ZipFile(rewritten, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info))
        target.writestr("payload/data/undeclared.txt", b"unexpected")

    with pytest.raises(BackupValidationError, match="undeclared"):
        service.validate(rewritten.name)
