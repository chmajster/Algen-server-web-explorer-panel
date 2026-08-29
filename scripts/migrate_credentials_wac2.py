#!/usr/bin/env python3.14
"""Migrate Hosts Manager credential envelopes from WAC1 to WAC2 without exposing plaintext."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.ansible_controller.public_security import CredentialCipher  # noqa: E402


DEFAULT_DATABASE = Path("/var/lib/webnas/hosts-manager/hosts.sqlite3")
DEFAULT_KEY = Path("/var/lib/webnas/secrets/hosts-manager.key")


def _backup_database(database: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    backup = database.with_name(f"{database.name}.pre-wac2-{stamp}.bak")
    source = sqlite3.connect(database, timeout=30)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    os.chmod(backup, 0o600)
    return backup


def _pending_migrations(
    connection: sqlite3.Connection,
    cipher: CredentialCipher,
) -> tuple[int, list[tuple[str, str]]]:
    rows = connection.execute(
        "SELECT id,encrypted_secret FROM credentials "
        "WHERE active=1 AND encrypted_secret IS NOT NULL AND encrypted_secret<>'' "
        "ORDER BY id"
    ).fetchall()
    pending: list[tuple[str, str]] = []
    for row in rows:
        credential_id = str(row["id"])
        envelope = str(row["encrypted_secret"])
        if not cipher.needs_migration(envelope):
            continue
        pending.append((cipher.migrate(envelope, associated_data=credential_id), credential_id))
    return len(rows), pending


def migrate(database: Path, key_path: Path, *, apply: bool) -> tuple[int, int, Path | None]:
    if not database.is_file():
        raise FileNotFoundError(f"Hosts Manager database does not exist: {database}")
    if not key_path.is_file():
        raise FileNotFoundError(f"credential master key does not exist: {key_path}")

    cipher = CredentialCipher(key_path)
    if not apply:
        connection = sqlite3.connect(database, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            inspected, pending = _pending_migrations(connection, cipher)
            return inspected, len(pending), None
        finally:
            connection.close()

    # The apply path is intended for a stopped WebNAS service. Create the
    # recovery copy before taking a write transaction; sqlite3.Connection.backup
    # can wait indefinitely when invoked from the same connection after
    # BEGIN IMMEDIATE.
    backup = _backup_database(database)
    connection = sqlite3.connect(database, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        inspected, pending = _pending_migrations(connection, cipher)
        connection.executemany(
            "UPDATE credentials SET encrypted_secret=?,updated_at=? WHERE id=?",
            [(envelope, time.time(), credential_id) for envelope, credential_id in pending],
        )
        connection.commit()
        return inspected, len(pending), backup
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or migrate Hosts Manager credential envelopes from legacy WAC1 to AEAD WAC2."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the migration; stop WebNAS first; without this flag the command is read-only",
    )
    args = parser.parse_args()

    database = args.database.resolve(strict=False)
    key_path = args.key.resolve(strict=False)
    inspected, pending, backup = migrate(database, key_path, apply=args.apply)
    mode = "migrated" if args.apply else "would migrate"
    print(f"Inspected {inspected} encrypted credentials; {mode} {pending} WAC1 envelopes.")
    if backup is not None:
        print(f"Pre-migration SQLite backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
