from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from ...config import get_config
from ..ansible_controller.security import CredentialCipher, redact
from .models import CredentialInput, EnrollmentTokenInput, GroupInput, HostInput, PowerProfileInput, RepositoryInput


SCHEMA_VERSION = 1
JSON_COLUMNS = {
    "tags_json": "tags", "variables_json": "variables", "group_ids_json": "group_ids",
    "host_ids_json": "host_ids", "facts_json": "facts", "details_json": "details",
}


def stable_id() -> str:
    return secrets.token_hex(16)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


@dataclass(frozen=True)
class HostCapabilityProvider:
    id: str
    name: str
    icon: str
    permission: str
    module_id: str
    supports: Callable[[dict[str, Any]], bool]
    plan: Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]
    execute: Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]
    deep_link: str = ""


class HostRegistryService:
    """The sole supported gateway to the Hosts Manager private database."""

    def __init__(self, path: Path | None = None, key_path: Path | None = None, legacy_path: Path | None = None) -> None:
        root = (path.parent if path else Path(get_config().paths.data_dir) / "hosts-manager").resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.root = root
        self.path = path or root / "hosts.sqlite3"
        self.repositories_root = root / "repositories"
        self.backups_root = root / "backups"
        for directory in (self.repositories_root, self.backups_root):
            directory.mkdir(exist_ok=True)
            os.chmod(directory, 0o700)
        self.cipher = CredentialCipher(key_path or root.parent / "secrets" / "hosts-manager.key")
        self.legacy_path = legacy_path or root.parent / "ansible-controller" / "controller.sqlite3"
        self._lock = threading.RLock()
        self._capabilities: dict[str, HostCapabilityProvider] = {}
        self._initialize()
        self.migrate_ansible_controller()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS migrations(source TEXT PRIMARY KEY, source_fingerprint TEXT NOT NULL, backup_path TEXT NOT NULL, migrated_at REAL NOT NULL, counts_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS credentials(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, type TEXT NOT NULL, username TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '', encrypted_secret TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hosts(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, hostname TEXT NOT NULL DEFAULT '', fqdn TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL, management_address TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL DEFAULT 22,
                    connection_type TEXT NOT NULL DEFAULT 'ssh', ssh_user TEXT NOT NULL, credential_id TEXT,
                    python_interpreter TEXT NOT NULL DEFAULT 'auto_silent', environment TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    variables_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 0,
                    enrollment_source TEXT NOT NULL DEFAULT 'manual', registration_status TEXT NOT NULL DEFAULT 'registered',
                    connection_status TEXT NOT NULL DEFAULT 'unknown', power_status TEXT NOT NULL DEFAULT 'unknown',
                    fingerprint_status TEXT NOT NULL DEFAULT 'unverified', power_profile_id TEXT,
                    last_seen_at REAL, last_test_at REAL, last_facts_at REAL, last_power_action_at REAL,
                    last_error TEXT NOT NULL DEFAULT '', managed_user_created INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(credential_id) REFERENCES credentials(id) ON DELETE SET NULL);
                CREATE INDEX IF NOT EXISTS idx_hm_hosts_address ON hosts(address,port);
                CREATE INDEX IF NOT EXISTS idx_hm_hosts_filter ON hosts(active,approved,connection_status,environment,location);
                CREATE TABLE IF NOT EXISTS groups(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', parent_id TEXT,
                    variables_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memberships(
                    host_id TEXT NOT NULL, group_id TEXT NOT NULL, created_at REAL NOT NULL, created_by TEXT NOT NULL,
                    PRIMARY KEY(host_id,group_id), FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE,
                    FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS host_keys(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, key_type TEXT NOT NULL, public_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, previous_fingerprint TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    UNIQUE(host_id,key_type), FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS facts(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, facts_json TEXT NOT NULL, checksum TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS idx_hm_facts_host ON facts(host_id,updated_at DESC);
                CREATE TABLE IF NOT EXISTS enrollment_tokens(
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, hostname_pattern TEXT NOT NULL, ssh_user TEXT NOT NULL,
                    port INTEGER NOT NULL, credential_id TEXT, environment TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]', group_ids_json TEXT NOT NULL DEFAULT '[]', require_approval INTEGER NOT NULL DEFAULT 1,
                    onboard_ansible INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL, used_at REAL, used_hostname TEXT NOT NULL DEFAULT '',
                    revoked_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS repositories(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', url TEXT NOT NULL,
                    revision TEXT NOT NULL, credential_id TEXT, host_ids_json TEXT NOT NULL DEFAULT '[]',
                    group_ids_json TEXT NOT NULL DEFAULT '[]', sync_before_use INTEGER NOT NULL DEFAULT 1,
                    last_commit TEXT NOT NULL DEFAULT '', last_sync_at REAL, last_sync_status TEXT NOT NULL DEFAULT '',
                    checksum TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS repository_syncs(
                    id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, status TEXT NOT NULL, commit_hash TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, created_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS power_profiles(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, provider TEXT NOT NULL, credential_id TEXT,
                    address TEXT NOT NULL DEFAULT '', mac_address TEXT NOT NULL DEFAULT '', broadcast_address TEXT NOT NULL DEFAULT '',
                    node TEXT NOT NULL DEFAULT '', resource_id INTEGER, verify_tls INTEGER NOT NULL DEFAULT 1,
                    ca_certificate TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations(
                    id TEXT PRIMARY KEY, host_id TEXT, capability_id TEXT NOT NULL, module_id TEXT NOT NULL DEFAULT 'hosts-manager',
                    status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, package_job_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scans(
                    id TEXT PRIMARY KEY, request_json TEXT NOT NULL, status TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                """
            )
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)", (SCHEMA_VERSION, now))
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        os.chmod(self.path, 0o600)

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for column, target in JSON_COLUMNS.items():
            if column in result:
                try:
                    result[target] = json.loads(result.pop(column) or "[]")
                except (ValueError, TypeError):
                    result[target] = [] if target.endswith("ids") or target == "tags" else {}
        for key in ("active", "approved", "require_approval", "onboard_ansible", "sync_before_use", "verify_tls", "managed_user_created"):
            if key in result:
                result[key] = bool(result[key])
        return result

    def _list(self, table: str, *, where: str = "", values: tuple[Any, ...] = (), order: str = "updated_at DESC", limit: int = 5000) -> list[dict[str, Any]]:
        allowed = {"hosts", "groups", "credentials", "host_keys", "facts", "enrollment_tokens", "repositories", "repository_syncs", "power_profiles", "operations", "scans", "memberships"}
        if table not in allowed:
            raise ValueError("unsupported registry table")
        clause = f" WHERE {where}" if where else ""
        with self._lock, self.connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table}{clause} ORDER BY {order} LIMIT ?", (*values, min(max(limit, 1), 5000))).fetchall()
        return [self._decode(row) or {} for row in rows]

    def _get(self, table: str, item_id: str) -> dict[str, Any] | None:
        items = self._list(table, where="id=?", values=(item_id,), limit=1)
        return items[0] if items else None

    def migrate_ansible_controller(self) -> dict[str, int]:
        """Copy legacy registry records once, transactionally, preserving every logical ID."""
        if not self.legacy_path.is_file() or self.legacy_path.resolve() == self.path.resolve():
            return {}
        stat = self.legacy_path.stat()
        fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
        with self.connect() as target:
            done = target.execute("SELECT 1 FROM migrations WHERE source=?", ("ansible-controller",)).fetchone()
            if done:
                return {}
        backup = self.backups_root / f"ansible-controller-pre-migration-{int(time.time())}.sqlite3"
        source = sqlite3.connect(self.legacy_path)
        try:
            with sqlite3.connect(backup) as destination:
                source.backup(destination)
            os.chmod(backup, 0o600)
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {"credentials": 0, "hosts": 0, "groups": 0, "memberships": 0, "host_keys": 0, "facts": 0, "enrollment_tokens": 0}
            now = time.time()
            with self._lock, self.connect() as target:
                if "credentials" in tables:
                    for row in source.execute("SELECT * FROM credentials"):
                        item = dict(zip([c[0] for c in source.execute("SELECT * FROM credentials LIMIT 0").description or []], row))
                        encrypted = str(item.get("encrypted_secret") or "")
                        if encrypted:
                            try:
                                legacy_cipher = CredentialCipher(self.legacy_path.parent.parent / "secrets" / "ansible-controller.key")
                                plain = legacy_cipher.decrypt(encrypted, associated_data=str(item["id"]))
                                encrypted = self.cipher.encrypt(plain, associated_data=str(item["id"]))
                            except Exception:
                                encrypted = ""
                        target.execute("""INSERT OR IGNORE INTO credentials(id,name,type,username,description,encrypted_secret,active,created_at,updated_at,created_by,updated_by)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (item["id"], item["name"], item["type"], item.get("username", ""), item.get("description", ""), encrypted, item.get("active", 1), item["created_at"], item["updated_at"], item["created_by"], item["updated_by"]))
                        counts["credentials"] += 1
                if "hosts" in tables:
                    source.row_factory = sqlite3.Row
                    for row in source.execute("SELECT * FROM hosts"):
                        item = dict(row)
                        target.execute("""INSERT OR IGNORE INTO hosts(id,name,hostname,fqdn,address,management_address,port,connection_type,ssh_user,credential_id,python_interpreter,environment,location,description,tags_json,variables_json,active,approved,enrollment_source,registration_status,connection_status,power_status,fingerprint_status,last_test_at,last_facts_at,last_error,managed_user_created,created_at,updated_at,created_by,updated_by)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (item["id"], item["name"], item["name"], "", item["address"], "", item["port"], item["connection_type"], item["ssh_user"], item.get("credential_id"), item["python_interpreter"], item["environment"], item["location"], "", item["tags_json"], item["variables_json"], item["active"], 1, "ansible-migration", "migrated", "unknown", "unknown", item.get("fingerprint_status", "unverified"), item.get("last_test_at"), item.get("last_facts_at"), item.get("last_error", ""), item.get("managed_user_created", 0), item["created_at"], item["updated_at"], item["created_by"], item["updated_by"]))
                        counts["hosts"] += 1
                mapping = (("inventory_groups", "groups"), ("host_group_memberships", "memberships"))
                for old, new in mapping:
                    if old not in tables:
                        continue
                    source.row_factory = sqlite3.Row
                    for row in source.execute(f"SELECT * FROM {old}"):
                        item = dict(row)
                        if new == "groups":
                            target.execute("""INSERT OR IGNORE INTO groups(id,name,description,parent_id,variables_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                                (item["id"], item["name"], item.get("description", ""), item.get("parent_id"), item.get("variables_json", "{}"), item.get("active", 1), item["created_at"], item["updated_at"], item["created_by"], item["updated_by"]))
                        else:
                            target.execute("INSERT OR IGNORE INTO memberships(host_id,group_id,created_at,created_by) VALUES(?,?,?,?)", (item["host_id"], item["group_id"], item["created_at"], item["created_by"]))
                        counts[new] += 1
                if "known_host_keys" in tables:
                    for row in source.execute("SELECT * FROM known_host_keys WHERE host_id IS NOT NULL"):
                        item = dict(row)
                        target.execute("""INSERT OR IGNORE INTO host_keys(id,host_id,key_type,public_key,fingerprint,previous_fingerprint,status,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (item["id"], item["host_id"], item["key_type"], item["public_key"], item["fingerprint"], item.get("previous_fingerprint", ""), item["status"], item["created_at"], item["updated_at"], item["created_by"], item["updated_by"]))
                        counts["host_keys"] += 1
                if "saved_facts" in tables:
                    for row in source.execute("SELECT * FROM saved_facts"):
                        item = dict(row)
                        target.execute("INSERT OR IGNORE INTO facts(id,host_id,facts_json,checksum,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?)",
                            (item["id"], item["host_id"], item["facts_json"], item["checksum"], item["created_at"], item["updated_at"], item["created_by"], item["updated_by"]))
                        counts["facts"] += 1
                target.execute("INSERT INTO migrations(source,source_fingerprint,backup_path,migrated_at,counts_json) VALUES(?,?,?,?,?)",
                    ("ansible-controller", fingerprint, str(backup), now, json.dumps(counts)))
            return counts
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        finally:
            source.close()

    def list_hosts(self, *, active_only: bool = False, search: str = "", status: str = "", tag: str = "", group_id: str = "", environment: str = "", location: str = "", limit: int = 5000, offset: int = 0) -> list[dict[str, Any]]:
        clauses, values = [], []
        if active_only:
            clauses.append("active=1")
        for column, value in (("connection_status", status), ("environment", environment), ("location", location)):
            if value:
                clauses.append(f"{column}=?")
                values.append(value)
        if search:
            clauses.append("(name LIKE ? OR address LIKE ? OR hostname LIKE ? OR fqdn LIKE ?)")
            values.extend([f"%{search}%"] * 4)
        items = self._list("hosts", where=" AND ".join(clauses), values=tuple(values), order="name", limit=min(limit + offset, 5000))[offset:]
        if tag:
            items = [item for item in items if tag in item.get("tags", [])]
        if group_id:
            members = {item["host_id"] for item in self._list("memberships", where="group_id=?", values=(group_id,))}
            items = [item for item in items if item["id"] in members]
        return [self._enrich_host(item) for item in items]

    def active_hosts(self) -> list[dict[str, Any]]:
        return self.list_hosts(active_only=True)

    def host(self, host_id: str) -> dict[str, Any] | None:
        item = self._get("hosts", host_id)
        return self._enrich_host(item) if item else None

    def _enrich_host(self, item: dict[str, Any]) -> dict[str, Any]:
        host_id = str(item["id"])
        item["groups"] = [{"id": group["id"], "name": group["name"]} for group in self.list_groups() if host_id in group["host_ids"]]
        item["group_ids"] = [group["id"] for group in item["groups"]]
        facts = self._list("facts", where="host_id=?", values=(host_id,), limit=1)
        item["facts"] = facts[0].get("facts", {}) if facts else {}
        item["credential"] = self.connection_data(host_id).get("credential")
        return item

    def save_host(self, payload: HostInput, actor: str, host_id: str | None = None, *, source: str = "manual") -> dict[str, Any]:
        now, item_id, value = time.time(), host_id or stable_id(), payload.model_dump(mode="json")
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at,created_by,fingerprint_status,enrollment_source,registration_status FROM hosts WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            fingerprint = existing["fingerprint_status"] if existing else "unverified"
            enrollment_source = existing["enrollment_source"] if existing else source
            registration_status = existing["registration_status"] if existing else ("pending_approval" if not value["approved"] else "registered")
            connection.execute("""INSERT INTO hosts(id,name,hostname,fqdn,address,management_address,port,connection_type,ssh_user,credential_id,python_interpreter,environment,location,description,tags_json,variables_json,active,approved,power_profile_id,fingerprint_status,enrollment_source,registration_status,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,hostname=excluded.hostname,fqdn=excluded.fqdn,address=excluded.address,management_address=excluded.management_address,port=excluded.port,connection_type=excluded.connection_type,ssh_user=excluded.ssh_user,credential_id=excluded.credential_id,python_interpreter=excluded.python_interpreter,environment=excluded.environment,location=excluded.location,description=excluded.description,tags_json=excluded.tags_json,variables_json=excluded.variables_json,active=excluded.active,approved=excluded.approved,power_profile_id=excluded.power_profile_id,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, value["name"], value["hostname"], value["fqdn"], value["address"], value["management_address"], value["port"], value["connection_type"], value["ssh_user"], value["credential_id"], value["python_interpreter"], value["environment"], value["location"], value["description"], json.dumps(value["tags"]), json.dumps(value["variables"]), int(value["active"]), int(value["approved"]), value["power_profile_id"], fingerprint, enrollment_source, registration_status, created_at, now, created_by, actor))
            connection.execute("DELETE FROM memberships WHERE host_id=?", (item_id,))
            connection.executemany("INSERT INTO memberships(host_id,group_id,created_at,created_by) VALUES(?,?,?,?)", [(item_id, group_id, now, actor) for group_id in value["group_ids"]])
        self.operation(item_id, "host.update" if host_id else "host.create", actor, status="completed", details={"source": source})
        return self.host(item_id) or {}

    def approve_host(self, host_id: str, actor: str) -> dict[str, Any]:
        self._update_host(host_id, actor, approved=1, registration_status="registered")
        return self.host(host_id) or {}

    def disable_host(self, host_id: str, actor: str) -> dict[str, Any]:
        self._update_host(host_id, actor, active=0)
        return self.host(host_id) or {}

    def delete_host(self, host_id: str, actor: str) -> bool:
        with self.connect() as connection:
            changed = connection.execute("DELETE FROM hosts WHERE id=?", (host_id,)).rowcount
        if changed:
            self.operation(host_id, "host.delete", actor, status="completed")
        return bool(changed)

    def _update_host(self, host_id: str, actor: str, **changes: Any) -> None:
        allowed = {"approved", "registration_status", "active", "fingerprint_status", "connection_status", "power_status", "last_seen_at", "last_test_at", "last_facts_at", "last_power_action_at", "last_error", "managed_user_created"}
        if not changes or not set(changes) <= allowed:
            raise ValueError("unsupported host update")
        assignments = ",".join(f"{key}=?" for key in changes)
        with self.connect() as connection:
            changed = connection.execute(f"UPDATE hosts SET {assignments},updated_at=?,updated_by=? WHERE id=?", (*changes.values(), time.time(), actor, host_id)).rowcount
        if not changed:
            raise KeyError("host not found")

    def list_groups(self) -> list[dict[str, Any]]:
        groups = self._list("groups", order="name")
        memberships = self._list("memberships", order="created_at")
        for group in groups:
            group["host_ids"] = [item["host_id"] for item in memberships if item["group_id"] == group["id"]]
        return groups

    def save_group(self, payload: GroupInput, actor: str, group_id: str | None = None) -> dict[str, Any]:
        now, item_id = time.time(), group_id or stable_id()
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM groups WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            connection.execute("""INSERT INTO groups(id,name,description,parent_id,variables_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,parent_id=excluded.parent_id,variables_json=excluded.variables_json,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, payload.name, payload.description, payload.parent_id, json.dumps(payload.variables), int(payload.active), created_at, now, created_by, actor))
            connection.execute("DELETE FROM memberships WHERE group_id=?", (item_id,))
            connection.executemany("INSERT INTO memberships(host_id,group_id,created_at,created_by) VALUES(?,?,?,?)", [(host_id, item_id, now, actor) for host_id in payload.host_ids])
        return next(item for item in self.list_groups() if item["id"] == item_id)

    def delete_group(self, group_id: str) -> bool:
        with self.connect() as connection:
            return bool(connection.execute("DELETE FROM groups WHERE id=?", (group_id,)).rowcount)

    def credentials(self) -> list[dict[str, Any]]:
        return [self._credential_metadata(item) for item in self._list("credentials", order="name")]

    @staticmethod
    def _credential_metadata(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "encrypted_secret"} | {"secret_configured": bool(item.get("encrypted_secret"))}

    def save_credential(self, payload: CredentialInput, actor: str, credential_id: str | None = None) -> dict[str, Any]:
        now, item_id = time.time(), credential_id or stable_id()
        envelope = self.cipher.encrypt(json.dumps({"secret": payload.secret, "passphrase": payload.passphrase}), associated_data=item_id) if payload.secret else ""
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM credentials WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            connection.execute("""INSERT INTO credentials(id,name,type,username,description,encrypted_secret,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,type=excluded.type,username=excluded.username,description=excluded.description,encrypted_secret=excluded.encrypted_secret,active=1,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, payload.name, payload.type.value, payload.username, payload.description, envelope, created_at, now, created_by, actor))
        return self._credential_metadata(self._get("credentials", item_id) or {})

    def verified_credential(self, credential_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
        if not module_id or not purpose:
            raise PermissionError("a controlled backend credential context is required")
        item = self._get("credentials", credential_id)
        if not item or not item.get("active") or not item.get("encrypted_secret"):
            raise KeyError("credential not found")
        value = json.loads(self.cipher.decrypt(str(item["encrypted_secret"]), associated_data=credential_id))
        return {"id": credential_id, "type": str(item["type"]), "username": str(item["username"]), "secret": str(value.get("secret", "")), "passphrase": str(value.get("passphrase", ""))}

    def delete_credential(self, credential_id: str) -> bool:
        with self.connect() as connection:
            return bool(connection.execute("UPDATE credentials SET active=0,encrypted_secret='' WHERE id=?", (credential_id,)).rowcount)

    def connection_data(self, host_id: str) -> dict[str, Any]:
        host = self._get("hosts", host_id)
        if not host:
            raise KeyError("host not found")
        credential = self._get("credentials", str(host.get("credential_id") or "")) if host.get("credential_id") else None
        return {
            "address": host["address"], "port": host["port"], "connection_type": host["connection_type"],
            "ssh_user": host["ssh_user"], "python_interpreter": host["python_interpreter"],
            "fingerprint_status": host["fingerprint_status"],
            "credential": self._credential_metadata(credential) if credential else None,
        }

    def create_enrollment_token(self, payload: EnrollmentTokenInput, actor: str) -> dict[str, Any]:
        now, item_id, token = time.time(), stable_id(), secrets.token_urlsafe(32)
        value = payload.model_dump(mode="json")
        expires = now + value["expires_minutes"] * 60
        with self.connect() as connection:
            connection.execute("""INSERT INTO enrollment_tokens(id,token_hash,hostname_pattern,ssh_user,port,credential_id,environment,location,tags_json,group_ids_json,require_approval,onboard_ansible,expires_at,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (item_id, hashlib.sha256(token.encode()).hexdigest(), value["hostname_pattern"], value["ssh_user"], value["port"], value["credential_id"], value["environment"], value["location"], json.dumps(value["tags"]), json.dumps(value["group_ids"]), int(value["require_approval"]), int(value["onboard_ansible"]), expires, now, now, actor, actor))
        return {"id": item_id, "token": token, "hostname_pattern": value["hostname_pattern"], "expires_at": expires, "used": False}

    def enrollment_tokens(self) -> list[dict[str, Any]]:
        return [{key: value for key, value in item.items() if key != "token_hash"} | {"used": item.get("used_at") is not None, "expired": item["expires_at"] < time.time(), "revoked": item.get("revoked_at") is not None} for item in self._list("enrollment_tokens")]

    def revoke_enrollment_token(self, token_id: str, actor: str) -> bool:
        with self.connect() as connection:
            return bool(connection.execute("UPDATE enrollment_tokens SET revoked_at=?,updated_at=?,updated_by=? WHERE id=? AND revoked_at IS NULL", (time.time(), time.time(), actor, token_id)).rowcount)

    def claim_enrollment_token(self, token: str, claim: dict[str, Any]) -> dict[str, Any] | None:
        now, token_hash, hostname = time.time(), hashlib.sha256(token.encode()).hexdigest(), str(claim["hostname"])
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM enrollment_tokens WHERE token_hash=? AND used_at IS NULL AND revoked_at IS NULL AND expires_at>=?", (token_hash, now)).fetchone()
            if not row or not fnmatch.fnmatchcase(hostname.casefold(), str(row["hostname_pattern"]).casefold()):
                return None
            changed = connection.execute("UPDATE enrollment_tokens SET used_at=?,used_hostname=?,updated_at=?,updated_by=? WHERE id=? AND used_at IS NULL", (now, hostname, now, f"enrollment:{hostname}", row["id"])).rowcount
            if not changed:
                return None
            token_data = self._decode(row) or {}
        host_payload = HostInput(
            name=hostname, hostname=hostname, fqdn=str(claim.get("fqdn") or ""), address=str(claim["address"]),
            port=int(token_data["port"]), ssh_user=str(token_data["ssh_user"]), credential_id=token_data.get("credential_id"),
            environment=str(token_data["environment"]), location=str(token_data["location"]), tags=token_data["tags"],
            group_ids=token_data["group_ids"], approved=not bool(token_data["require_approval"]),
            variables={"enrollment_os": claim.get("os", ""), "enrollment_architecture": claim.get("architecture", ""), "enrollment_python": claim.get("python", "")},
        )
        return self.save_host(host_payload, f"enrollment:{hostname}", source="script")

    def enrollment_script(self, token_id: str, token: str, endpoint: str) -> str:
        token_item = self._get("enrollment_tokens", token_id)
        if not token_item or token_item.get("used_at") or token_item.get("revoked_at") or token_item["expires_at"] < time.time():
            raise KeyError("enrollment token is not active")
        endpoint = endpoint.rstrip("/")
        return f"""#!/bin/sh
set -euo pipefail
die() {{ printf '%s\\n' "Hosts Manager enrollment failed: $1" >&2; exit 1; }}
command -v curl >/dev/null 2>&1 || die "curl is required"
HOSTNAME_VALUE="$(hostname 2>/dev/null || true)"
FQDN_VALUE="$(hostname -f 2>/dev/null || printf '%s' "$HOSTNAME_VALUE")"
ADDRESS_VALUE="${{WEBNAS_ENROLL_ADDRESS:-$(hostname -I 2>/dev/null | awk '{{print $1}}')}}"
OS_VALUE="$(. /etc/os-release 2>/dev/null && printf '%s' "${{ID:-unknown}} ${{VERSION_ID:-}}" || uname -s)"
ARCH_VALUE="$(uname -m)"
PYTHON_VALUE="$(command -v python3 2>/dev/null || true)"
[ -n "$HOSTNAME_VALUE" ] && [ -n "$ADDRESS_VALUE" ] || die "hostname or primary address unavailable"
json_escape() {{ printf '%s' "$1" | sed 's/\\\\/\\\\\\\\/g; s/"/\\\\"/g'; }}
BODY="$(printf '{{"hostname":"%s","fqdn":"%s","address":"%s","os":"%s","architecture":"%s","python":"%s"}}' "$(json_escape "$HOSTNAME_VALUE")" "$(json_escape "$FQDN_VALUE")" "$(json_escape "$ADDRESS_VALUE")" "$(json_escape "$OS_VALUE")" "$(json_escape "$ARCH_VALUE")" "$(json_escape "$PYTHON_VALUE")")"
curl --fail --silent --show-error --proto '=https' --tlsv1.2 -X POST -H 'Content-Type: application/json' -H 'Authorization: Bearer {token}' --data "$BODY" '{endpoint}/api/modules/hosts-manager/enroll' >/dev/null || die "server rejected enrollment"
printf '%s\\n' 'Enrollment submitted; administrator approval and SSH fingerprint verification are required.'
"""

    @staticmethod
    def sanitize_facts(raw: dict[str, Any]) -> dict[str, Any]:
        allowed = {"system", "distribution", "distribution_version", "kernel", "architecture", "cpu_count", "memory_mb", "addresses", "python", "uptime_seconds", "capabilities"}
        result = {key: raw[key] for key in allowed if key in raw}
        machine_id = str(raw.get("machine_id") or "")
        if machine_id:
            result["machine_id_hash"] = hashlib.sha256(machine_id.encode()).hexdigest()
        return redact(result)

    def save_facts(self, host_id: str, raw: dict[str, Any], actor: str) -> dict[str, Any]:
        facts, now = self.sanitize_facts(raw), time.time()
        encoded = json.dumps(facts, sort_keys=True)
        with self.connect() as connection:
            connection.execute("INSERT INTO facts(id,host_id,facts_json,checksum,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?)", (stable_id(), host_id, encoded, hashlib.sha256(encoded.encode()).hexdigest(), now, now, actor, actor))
        self._update_host(host_id, actor, last_facts_at=now, last_seen_at=now)
        return facts

    def host_keys(self, host_id: str) -> list[dict[str, Any]]:
        return self._list("host_keys", where="host_id=?", values=(host_id,))

    def accept_host_key(self, host_id: str, key_type: str, public_key: str, fingerprint: str, actor: str, replace: bool = False) -> dict[str, Any]:
        now = time.time()
        with self.connect() as connection:
            old = connection.execute("SELECT * FROM host_keys WHERE host_id=? AND key_type=?", (host_id, key_type)).fetchone()
            if old and old["fingerprint"] != fingerprint and not replace:
                raise PermissionError("host key changed; explicit replacement confirmation is required")
            previous = old["fingerprint"] if old and old["fingerprint"] != fingerprint else (old["previous_fingerprint"] if old else "")
            connection.execute("""INSERT INTO host_keys(id,host_id,key_type,public_key,fingerprint,previous_fingerprint,status,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?, 'accepted',?,?,?,?) ON CONFLICT(host_id,key_type) DO UPDATE SET public_key=excluded.public_key,fingerprint=excluded.fingerprint,previous_fingerprint=excluded.previous_fingerprint,status='accepted',updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (stable_id(), host_id, key_type, public_key, fingerprint, previous, old["created_at"] if old else now, now, old["created_by"] if old else actor, actor))
        self._update_host(host_id, actor, fingerprint_status="accepted")
        return self.host_keys(host_id)[0]

    def mark_scanned_key(self, host_id: str, fingerprint: str, actor: str) -> bool:
        keys = self.host_keys(host_id)
        changed = bool(keys and all(item["fingerprint"] != fingerprint for item in keys))
        self._update_host(host_id, actor, fingerprint_status="changed" if changed else ("accepted" if keys else "scanned"))
        return changed

    def register_capability(self, provider: HostCapabilityProvider) -> None:
        if not provider.id.startswith(f"{provider.module_id}."):
            raise ValueError("capability id must be namespaced by module")
        self._capabilities[provider.id] = provider

    def capabilities(self, host_id: str) -> list[dict[str, Any]]:
        host = self.host(host_id)
        if not host:
            raise KeyError("host not found")
        return [{"id": item.id, "name": item.name, "icon": item.icon, "permission": item.permission, "module_id": item.module_id, "deep_link": item.deep_link} for item in self._capabilities.values() if item.supports(host)]

    def capability(self, host_id: str, capability_id: str) -> HostCapabilityProvider:
        host = self.host(host_id)
        provider = self._capabilities.get(capability_id)
        if not host or not provider or not provider.supports(host):
            raise KeyError("capability is unavailable")
        return provider

    def repositories(self) -> list[dict[str, Any]]:
        return self._list("repositories", order="name")

    def save_repository(self, payload: RepositoryInput, actor: str, repository_id: str | None = None) -> dict[str, Any]:
        now, item_id, value = time.time(), repository_id or stable_id(), payload.model_dump(mode="json")
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM repositories WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            connection.execute("""INSERT INTO repositories(id,name,description,url,revision,credential_id,host_ids_json,group_ids_json,sync_before_use,active,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,url=excluded.url,revision=excluded.revision,credential_id=excluded.credential_id,host_ids_json=excluded.host_ids_json,group_ids_json=excluded.group_ids_json,sync_before_use=excluded.sync_before_use,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, value["name"], value["description"], value["url"], value["revision"], value["credential_id"], json.dumps(value["host_ids"]), json.dumps(value["group_ids"]), int(value["sync_before_use"]), int(value["active"]), created_at, now, created_by, actor))
        return self._get("repositories", item_id) or {}

    def delete_repository(self, repository_id: str) -> bool:
        with self.connect() as connection:
            changed = connection.execute("UPDATE repositories SET active=0 WHERE id=?", (repository_id,)).rowcount
        return bool(changed)

    def power_profiles(self) -> list[dict[str, Any]]:
        return self._list("power_profiles", order="name")

    def save_power_profile(self, payload: PowerProfileInput, actor: str, profile_id: str | None = None) -> dict[str, Any]:
        now, item_id, value = time.time(), profile_id or stable_id(), payload.model_dump(mode="json")
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM power_profiles WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            connection.execute("""INSERT INTO power_profiles(id,name,provider,credential_id,address,mac_address,broadcast_address,node,resource_id,verify_tls,ca_certificate,active,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,provider=excluded.provider,credential_id=excluded.credential_id,address=excluded.address,mac_address=excluded.mac_address,broadcast_address=excluded.broadcast_address,node=excluded.node,resource_id=excluded.resource_id,verify_tls=excluded.verify_tls,ca_certificate=excluded.ca_certificate,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, value["name"], value["provider"], value["credential_id"], value["address"], value["mac_address"], value["broadcast_address"], value["node"], value["resource_id"], int(value["verify_tls"]), value["ca_certificate"], int(value["active"]), created_at, now, created_by, actor))
        return self._get("power_profiles", item_id) or {}

    def delete_power_profile(self, profile_id: str) -> bool:
        with self.connect() as connection:
            return bool(connection.execute("UPDATE power_profiles SET active=0 WHERE id=?", (profile_id,)).rowcount)

    def operation(self, host_id: str | None, capability_id: str, actor: str, *, module_id: str = "hosts-manager", status: str = "queued", stage: str = "queued", progress: int = 0, details: dict[str, Any] | None = None, error: str = "", package_job_id: str | None = None) -> dict[str, Any]:
        now, item_id = time.time(), stable_id()
        safe_details = redact(details or {})
        with self.connect() as connection:
            connection.execute("INSERT INTO operations(id,host_id,capability_id,module_id,status,stage,progress,package_job_id,details_json,error,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, host_id, capability_id, module_id, status, stage, progress, package_job_id, json.dumps(safe_details), error[:2000], now, now, actor, actor))
        return self._get("operations", item_id) or {}

    def operations(self, host_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        return self._list("operations", where="host_id=?" if host_id else "", values=(host_id,) if host_id else (), limit=limit)

    def dashboard(self) -> dict[str, Any]:
        hosts = self.list_hosts()
        return {
            "total": len(hosts), "online": sum(item["connection_status"] == "online" for item in hosts),
            "offline": sum(item["connection_status"] == "offline" for item in hosts),
            "unverified": sum(item["fingerprint_status"] in {"unverified", "scanned"} for item in hosts),
            "fingerprint_errors": sum(item["fingerprint_status"] == "changed" for item in hosts),
            "pending_approval": sum(not item["approved"] for item in hosts),
            "ansible_available": sum(any(c["id"].startswith("ansible.") for c in self.capabilities(item["id"])) for item in hosts),
            "power_managed": sum(bool(item.get("power_profile_id")) for item in hosts),
            "recent_operations": self.operations(limit=10),
            "recent_errors": [item for item in hosts if item.get("last_error")][:10],
        }


@lru_cache
def registry() -> HostRegistryService:
    return HostRegistryService()
