from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from ...config import get_config
from ...core.events import bus
from ..ansible_controller.public_security import CredentialCipher
from .models import SECRET_TYPES, SecretInput

SCHEMA_VERSION = 1


class ClosingConnection(sqlite3.Connection):
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
        return False


def _stable_id() -> str:
    return secrets.token_hex(16)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


class SecretsManagerService:
    """Authoritative encrypted secret store for WebNAS.

    Secret values are encrypted with the existing WAC2 CredentialCipher and are
    never returned by browser-facing metadata methods. The legacy Hosts Manager
    credential table remains untouched as a rollback artifact after migration.
    """

    def __init__(
        self,
        path: Path | None = None,
        key_path: Path | None = None,
        hosts_path: Path | None = None,
        hosts_key_path: Path | None = None,
        webhooks_path: Path | None = None,
    ) -> None:
        data_root = Path(get_config().paths.data_dir).resolve(strict=False)
        self.root = (path.parent if path else data_root / "secrets-manager").resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.path = path or self.root / "secrets.sqlite3"
        self.backups_root = self.root / "backups"
        self.backups_root.mkdir(exist_ok=True)
        os.chmod(self.backups_root, 0o700)
        self.key_path = key_path or data_root / "secrets" / "secrets-manager.key"
        self.hosts_path = hosts_path or data_root / "hosts-manager" / "hosts.sqlite3"
        self.hosts_key_path = hosts_key_path or data_root / "secrets" / "hosts-manager.key"
        self.webhooks_path = webhooks_path or data_root / "webhook-manager" / "webhooks.sqlite3"
        self.cipher = CredentialCipher(self.key_path)
        self._lock = threading.RLock()
        self.migration_error = ""
        self.migration_completed = False
        self._initialize()
        try:
            self.migration_completed = self.migrate_from_hosts_manager()
        except Exception as error:  # keep legacy runtime available on migration failure
            self.migration_error = f"{type(error).__name__}: {error}"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migrations(
                    source TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    migrated_at REAL NOT NULL,
                    counts_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secrets(
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
                );
                CREATE INDEX IF NOT EXISTS idx_sm_secrets_active_name ON secrets(active,name);
                CREATE INDEX IF NOT EXISTS idx_sm_secrets_environment ON secrets(environment_id,active);
                CREATE TABLE IF NOT EXISTS secret_audit(
                    id TEXT PRIMARY KEY,
                    secret_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    consumer_module TEXT NOT NULL DEFAULT '',
                    purpose TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(secret_id) REFERENCES secrets(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_sm_audit_secret_time ON secret_audit(secret_id,created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sm_audit_time ON secret_audit(created_at DESC);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)",
                (SCHEMA_VERSION, time.time()),
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _source_fingerprint(self) -> str:
        if not self.hosts_path.exists():
            return "missing"
        stat = self.hosts_path.stat()
        return hashlib.sha256(f"{self.hosts_path}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()

    def _backup_hosts_database(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        backup = self.backups_root / f"hosts-credentials-pre-migration-{stamp}.sqlite3"
        source = sqlite3.connect(self.hosts_path, timeout=15)
        try:
            target = sqlite3.connect(backup)
            try:
                source.backup(target)
                target.execute("PRAGMA integrity_check")
            finally:
                target.close()
        finally:
            source.close()
        os.chmod(backup, 0o600)
        return backup

    def migrate_from_hosts_manager(self) -> bool:
        """Copy legacy credential rows once, preserving IDs and re-encrypting WAC2.

        The legacy database is not modified. A verified SQLite backup is created
        before the destination transaction. If any envelope cannot authenticate,
        the destination transaction rolls back and the legacy runtime remains the
        recovery source.
        """
        if not self.hosts_path.exists():
            return True
        with self._lock, self.connect() as destination:
            marker = destination.execute(
                "SELECT source FROM migrations WHERE source=?",
                ("hosts-manager.credentials",),
            ).fetchone()
            if marker:
                return True

        source = sqlite3.connect(self.hosts_path, timeout=15)
        source.row_factory = sqlite3.Row
        try:
            exists = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='credentials'"
            ).fetchone()
            if not exists:
                return True
            rows = source.execute("SELECT * FROM credentials ORDER BY id").fetchall()
        finally:
            source.close()

        backup = self._backup_hosts_database()
        fingerprint = self._source_fingerprint()
        legacy_cipher = CredentialCipher(self.hosts_key_path)
        migrated = 0
        with self._lock, self.connect() as destination:
            destination.execute("BEGIN IMMEDIATE")
            for row in rows:
                item = dict(row)
                secret_id = str(item["id"])
                legacy_envelope = str(item.get("encrypted_secret") or "")
                if legacy_envelope:
                    plaintext = legacy_cipher.decrypt(legacy_envelope, associated_data=secret_id)
                    decoded = json.loads(plaintext)
                    if not isinstance(decoded, dict):
                        raise ValueError(f"invalid credential payload for {secret_id}")
                    new_envelope = self.cipher.encrypt(
                        _json(
                            {
                                "secret": str(decoded.get("secret", "")),
                                "passphrase": str(decoded.get("passphrase", "")),
                            }
                        ),
                        associated_data=secret_id,
                    )
                    self.cipher.decrypt(new_envelope, associated_data=secret_id)
                else:
                    new_envelope = ""
                destination.execute(
                    """
                    INSERT INTO secrets(
                        id,name,type,username,description,encrypted_secret,active,
                        environment_id,shared_with_json,created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        secret_id,
                        str(item.get("name") or secret_id),
                        str(item.get("type") or "generic_secret"),
                        str(item.get("username") or ""),
                        str(item.get("description") or ""),
                        new_envelope,
                        int(item.get("active", 1)),
                        item.get("environment_id"),
                        str(item.get("shared_with_json") or "[]"),
                        float(item.get("created_at") or time.time()),
                        float(item.get("updated_at") or time.time()),
                        str(item.get("created_by") or "migration"),
                        str(item.get("updated_by") or "migration"),
                    ),
                )
                migrated += 1
            destination.execute(
                "INSERT INTO migrations(source,source_fingerprint,backup_path,migrated_at,counts_json) VALUES(?,?,?,?,?)",
                (
                    "hosts-manager.credentials",
                    fingerprint,
                    str(backup),
                    time.time(),
                    _json({"credentials": migrated}),
                ),
            )
        return True

    @staticmethod
    def _payload_dict(payload: Any) -> dict[str, Any]:
        if hasattr(payload, "model_dump"):
            value = payload.model_dump(mode="python")
        elif isinstance(payload, dict):
            value = dict(payload)
        else:
            value = {
                name: getattr(payload, name)
                for name in (
                    "name",
                    "type",
                    "username",
                    "secret",
                    "passphrase",
                    "description",
                    "environment_id",
                    "shared_with",
                )
                if hasattr(payload, name)
            }
        kind = value.get("type")
        value["type"] = str(getattr(kind, "value", kind or "generic_secret"))
        return value

    def _usage_details(self) -> dict[str, list[dict[str, Any]]]:
        details: dict[str, list[dict[str, Any]]] = {}

        if self.hosts_path.exists():
            connection = sqlite3.connect(self.hosts_path, timeout=5)
            try:
                for table, column, predicate in (
                    ("hosts", "credential_id", "active=1"),
                    ("repositories", "credential_id", "active=1"),
                    ("power_profiles", "credential_id", "active=1"),
                    ("environments", "default_credential_id", "active=1"),
                ):
                    try:
                        rows = connection.execute(
                            f"SELECT {column},COUNT(*) FROM {table} "
                            f"WHERE {column} IS NOT NULL AND {predicate} GROUP BY {column}"  # noqa: S608 - fixed constants
                        ).fetchall()
                    except sqlite3.Error:
                        continue
                    for secret_id, amount in rows:
                        key = str(secret_id)
                        details.setdefault(key, []).append(
                            {
                                "module": "hosts-manager",
                                "resource": table,
                                "count": int(amount),
                            }
                        )
            finally:
                connection.close()

        if self.webhooks_path.exists():
            connection = sqlite3.connect(self.webhooks_path, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='webhooks'"
                ).fetchone()
                if exists:
                    rows = connection.execute(
                        "SELECT id,name,secret_id,signing_secret_id FROM webhooks"
                    ).fetchall()
                    for row in rows:
                        for column, role in (
                            ("secret_id", "authentication"),
                            ("signing_secret_id", "signing"),
                        ):
                            secret_id = row[column]
                            if not secret_id:
                                continue
                            details.setdefault(str(secret_id), []).append(
                                {
                                    "module": "webhook-manager",
                                    "resource": "webhook",
                                    "resource_id": str(row["id"]),
                                    "name": str(row["name"]),
                                    "role": role,
                                    "count": 1,
                                }
                            )
            finally:
                connection.close()
        return details

    def _usage_counts(self) -> dict[str, int]:
        return {
            secret_id: sum(int(item.get("count", 1)) for item in items)
            for secret_id, items in self._usage_details().items()
        }

    def _metadata(
        self,
        row: sqlite3.Row | dict[str, Any],
        usage: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        item = dict(row)
        usage_items = list(usage or [])
        usage_count = sum(int(entry.get("count", 1)) for entry in usage_items)
        return {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "type": str(item["type"]),
            "username": str(item.get("username") or ""),
            "description": str(item.get("description") or ""),
            "environment_id": item.get("environment_id"),
            "shared_with": _decode_list(item.get("shared_with_json")),
            "secret_configured": bool(item.get("encrypted_secret")),
            "passphrase_configured": self._passphrase_configured(item),
            "active": bool(item.get("active", 1)),
            "created_at": float(item.get("created_at") or 0),
            "updated_at": float(item.get("updated_at") or 0),
            "usage_count": usage_count,
            "usage": usage_items,
            "host_count": usage_count,
        }

    def _passphrase_configured(self, item: dict[str, Any]) -> bool:
        envelope = str(item.get("encrypted_secret") or "")
        if not envelope:
            return False
        try:
            decoded = json.loads(self.cipher.decrypt(envelope, associated_data=str(item["id"])))
            return bool(isinstance(decoded, dict) and decoded.get("passphrase"))
        except Exception:
            return False

    def secrets(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        usage = self._usage_details()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM secrets "
                + ("" if include_inactive else "WHERE active=1 ")
                + "ORDER BY name COLLATE NOCASE,id"
            ).fetchall()
        return [self._metadata(row, usage.get(str(row["id"]), [])) for row in rows]

    def credentials(self) -> list[dict[str, Any]]:
        return self.secrets()

    def secret(self, secret_id: str) -> dict[str, Any] | None:
        usage = self._usage_details()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM secrets WHERE id=? AND active=1", (secret_id,)).fetchone()
        return self._metadata(row, usage.get(secret_id, [])) if row else None

    def _audit(
        self,
        secret_id: str,
        action: str,
        *,
        actor: str = "",
        consumer_module: str = "",
        purpose: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = dict(details or {})
        for key in list(safe_details):
            if any(
                token in key.lower()
                for token in ("secret", "password", "token", "key", "passphrase", "authorization")
            ):
                safe_details[key] = "[REDACTED]"
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO secret_audit(id,secret_id,action,consumer_module,purpose,actor,details_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    _stable_id(),
                    secret_id,
                    action,
                    consumer_module,
                    purpose,
                    actor,
                    _json(safe_details),
                    time.time(),
                ),
            )

    def audit(self, *, secret_id: str = "", limit: int = 250) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self.connect() as connection:
            if secret_id:
                rows = connection.execute(
                    "SELECT * FROM secret_audit WHERE secret_id=? ORDER BY created_at DESC LIMIT ?",
                    (secret_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM secret_audit ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(str(item.pop("details_json") or "{}"))
            result.append(item)
        return result

    def _sync_reference_shadow(self, metadata: dict[str, Any], *, actor: str) -> None:
        """Maintain an empty legacy row solely for existing Hosts Manager FKs.

        Existing migrated rows are never overwritten, preserving the rollback
        artifact byte-for-byte. New rows contain no encrypted secret material.
        """
        if not self.hosts_path.exists():
            return
        connection = sqlite3.connect(self.hosts_path, timeout=10)
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='credentials'"
            ).fetchone()
            if not exists:
                return
            now = time.time()
            connection.execute(
                """
                INSERT OR IGNORE INTO credentials(
                    id,name,type,username,description,encrypted_secret,active,environment_id,
                    shared_with_json,created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,'',1,?,?,?,?,?,?)
                """,
                (
                    metadata["id"],
                    metadata["name"],
                    metadata["type"],
                    metadata.get("username", ""),
                    metadata.get("description", ""),
                    metadata.get("environment_id"),
                    _json(metadata.get("shared_with", [])),
                    now,
                    now,
                    actor,
                    actor,
                ),
            )
            connection.execute(
                """
                UPDATE credentials SET name=?,type=?,username=?,description=?,environment_id=?,shared_with_json=?,
                    active=1,updated_at=?,updated_by=?
                WHERE id=? AND encrypted_secret=''
                """,
                (
                    metadata["name"],
                    metadata["type"],
                    metadata.get("username", ""),
                    metadata.get("description", ""),
                    metadata.get("environment_id"),
                    _json(metadata.get("shared_with", [])),
                    now,
                    actor,
                    metadata["id"],
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def save(self, payload: SecretInput | Any, actor: str, secret_id: str | None = None) -> dict[str, Any]:
        values = self._payload_dict(payload)
        kind = str(values.get("type") or "")
        if kind not in SECRET_TYPES:
            raise ValueError("unsupported secret type")
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValueError("secret name is required")
        username = str(values.get("username") or "")
        description = str(values.get("description") or "")
        environment_id = values.get("environment_id") or None
        shares = [str(value) for value in values.get("shared_with") or []]
        raw_secret = str(values.get("secret") or "")
        raw_passphrase = str(values.get("passphrase") or "")
        item_id = secret_id or _stable_id()
        now = time.time()
        with self._lock, self.connect() as connection:
            old = connection.execute("SELECT * FROM secrets WHERE id=?", (item_id,)).fetchone()
            if raw_secret:
                envelope = self.cipher.encrypt(
                    _json({"secret": raw_secret, "passphrase": raw_passphrase}),
                    associated_data=item_id,
                )
            elif old:
                envelope = str(old["encrypted_secret"] or "")
            elif kind != "wol":
                raise ValueError("secret value is required")
            else:
                envelope = ""
            created_at = float(old["created_at"]) if old else now
            created_by = str(old["created_by"]) if old else actor
            try:
                connection.execute(
                    """
                    INSERT INTO secrets(
                        id,name,type,username,description,encrypted_secret,active,environment_id,
                        shared_with_json,created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,type=excluded.type,username=excluded.username,
                        description=excluded.description,encrypted_secret=excluded.encrypted_secret,
                        active=1,environment_id=excluded.environment_id,shared_with_json=excluded.shared_with_json,
                        updated_at=excluded.updated_at,updated_by=excluded.updated_by
                    """,
                    (
                        item_id,
                        name,
                        kind,
                        username,
                        description,
                        envelope,
                        environment_id,
                        _json(shares),
                        created_at,
                        now,
                        created_by,
                        actor,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("a secret with this name already exists") from error
        item = self.secret(item_id)
        if not item:
            raise RuntimeError("saved secret is unavailable")
        self._sync_reference_shadow(item, actor=actor)
        self._audit(item_id, "updated" if old else "created", actor=actor)
        bus.publish(
            "secret.updated" if old else "secret.created",
            {
                "secret_id": item_id,
                "name": item["name"],
                "type": item["type"],
                "actor": actor,
            },
        )
        return item

    def save_credential(
        self,
        payload: Any,
        actor: str,
        credential_id: str | None = None,
    ) -> dict[str, Any]:
        return self.save(payload, actor, credential_id)

    def verified_secret(self, secret_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
        if not module_id or not purpose:
            raise PermissionError("a controlled backend secret context is required")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM secrets WHERE id=? AND active=1", (secret_id,)
            ).fetchone()
        if not row or not row["encrypted_secret"]:
            raise KeyError("secret not found")
        shares = _decode_list(row["shared_with_json"])
        if module_id not in shares:
            raise PermissionError(f"secret is not shared with {module_id}")
        decoded = json.loads(
            self.cipher.decrypt(str(row["encrypted_secret"]), associated_data=secret_id)
        )
        if not isinstance(decoded, dict):
            raise ValueError("invalid encrypted secret payload")
        self._audit(secret_id, "used", consumer_module=module_id, purpose=purpose)
        return {
            "id": secret_id,
            "type": str(row["type"]),
            "username": str(row["username"] or ""),
            "secret": str(decoded.get("secret", "")),
            "passphrase": str(decoded.get("passphrase", "")),
        }

    def verified_credential(
        self,
        credential_id: str,
        *,
        module_id: str,
        purpose: str,
    ) -> dict[str, str]:
        return self.verified_secret(credential_id, module_id=module_id, purpose=purpose)

    def delete(self, secret_id: str, actor: str) -> bool:
        usage = self._usage_details().get(secret_id, [])
        if usage:
            raise ValueError("secret is still referenced by infrastructure resources")
        item = self.secret(secret_id)
        if not item:
            return False
        deleted_name = f"{item['name']}#deleted-{secret_id}"
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE secrets
                SET active=0,name=?,encrypted_secret='',shared_with_json='[]',updated_at=?,updated_by=?
                WHERE id=?
                """,
                (deleted_name, time.time(), actor, secret_id),
            )
        self._audit(secret_id, "deleted", actor=actor)
        bus.publish(
            "secret.deleted",
            {"secret_id": secret_id, "name": item["name"], "actor": actor},
        )
        return True

    def delete_credential(self, credential_id: str, actor: str = "compatibility") -> bool:
        return self.delete(credential_id, actor)

    def encrypted_backup(self, actor: str) -> dict[str, Any]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute("SELECT * FROM secrets ORDER BY id")]
        payload = {
            "format": "webnas-secrets-manager-backup-v1",
            "created_at": time.time(),
            "schema_version": SCHEMA_VERSION,
            "secrets": rows,
        }
        envelope = self.cipher.export_encrypted(payload)
        return {
            "format": payload["format"],
            "created_at": payload["created_at"],
            "payload": envelope,
            "count": len(rows),
        }

    def restore_encrypted_backup(self, envelope: str, actor: str) -> dict[str, Any]:
        payload = self.cipher.import_encrypted(envelope)
        if payload.get("format") != "webnas-secrets-manager-backup-v1" or not isinstance(
            payload.get("secrets"), list
        ):
            raise ValueError("unsupported Secrets Manager backup")
        safety = self.root / f"pre-restore-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}.sqlite3"
        source = sqlite3.connect(self.path, timeout=15)
        try:
            target = sqlite3.connect(safety)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        os.chmod(safety, 0o600)
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM secrets")
            for item in payload["secrets"]:
                if not isinstance(item, dict):
                    raise ValueError("invalid backup secret record")
                secret_id = str(item.get("id") or "")
                encrypted = str(item.get("encrypted_secret") or "")
                if encrypted:
                    self.cipher.decrypt(encrypted, associated_data=secret_id)
                connection.execute(
                    """
                    INSERT INTO secrets(
                        id,name,type,username,description,encrypted_secret,active,environment_id,
                        shared_with_json,created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        secret_id,
                        str(item.get("name") or secret_id),
                        str(item.get("type") or "generic_secret"),
                        str(item.get("username") or ""),
                        str(item.get("description") or ""),
                        encrypted,
                        int(item.get("active", 1)),
                        item.get("environment_id"),
                        str(item.get("shared_with_json") or "[]"),
                        float(item.get("created_at") or time.time()),
                        float(item.get("updated_at") or time.time()),
                        str(item.get("created_by") or actor),
                        actor,
                    ),
                )
        return {
            "ok": True,
            "restored": len(payload["secrets"]),
            "safety_backup": str(safety),
        }

    def rotation_plan(self) -> dict[str, Any]:
        return {
            "online_rotation_supported": False,
            "reason": "Database and master-key replacement cannot be made crash-atomic while WebNAS is serving requests.",
            "steps": [
                "stop all webnas services",
                "back up secrets.sqlite3 and secrets-manager.key as one recovery unit",
                "generate a new 32-byte mode-0600 key in a temporary file",
                "re-encrypt and authenticate every envelope in one SQLite transaction",
                "atomically replace the key only after database verification",
                "start WebNAS and verify secret-backed operations before removing the recovery set",
            ],
        }

    def status(self) -> dict[str, Any]:
        with self.connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM secrets WHERE active=1").fetchone()[0])
            migrations = [
                dict(row)
                for row in connection.execute("SELECT * FROM migrations ORDER BY migrated_at")
            ]
        return {
            "status": "degraded" if self.migration_error else "ok",
            "authoritative": not bool(self.migration_error),
            "secrets": total,
            "schema_version": SCHEMA_VERSION,
            "key_path": str(self.key_path),
            "migration_completed": self.migration_completed,
            "migration_error": self.migration_error,
            "migrations": migrations,
        }


@lru_cache(maxsize=1)
def service() -> SecretsManagerService:
    return SecretsManagerService()
