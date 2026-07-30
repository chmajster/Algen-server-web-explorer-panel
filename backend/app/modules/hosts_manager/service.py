from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from ...config import get_config
from ..ansible_controller.security import CredentialCipher, redact
from ..apmid.models import ApmidInput as DomainApmidInput
from ..apmid.service import (
    ApmidService,
    ApmidConflictError as DomainApmidConflictError,
    ApmidInUseError as DomainApmidInUseError,
    ApmidNotFoundError as DomainApmidNotFoundError,
)
from .models import (
    ApmidInput, CredentialInput, EnrollmentTokenInput, EnvironmentInput, GroupInput, HostInput, HostnamePatternInput,
    HostsManagerSettingsUpdate, PowerProfileInput, RepositoryInput, hostname_template_parts, render_hostname,
)


SCHEMA_VERSION = 5
JSON_COLUMNS = {
    "tags_json": "tags", "variables_json": "variables", "group_ids_json": "group_ids",
    "host_ids_json": "host_ids", "facts_json": "facts", "details_json": "details",
    "report_json": "report",
}


def stable_id() -> str:
    return secrets.token_hex(16)


class ManagedGroupConflictError(ValueError):
    pass


class ManagedGroupProtectedError(ValueError):
    pass


class ApmidInUseError(ValueError):
    pass


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> bool | None:  # type: ignore[override]
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
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
        self.apmid_service = ApmidService(path=root.parent / "apmid" / "apmid.sqlite3", legacy_path=self.path)
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
                    environment_id TEXT, last_used_at REAL,
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
                CREATE TABLE IF NOT EXISTS apmids(
                    id TEXT PRIMARY KEY, code TEXT NOT NULL COLLATE NOCASE UNIQUE, description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
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
                    revoked_at REAL, assigned_hostname TEXT NOT NULL DEFAULT '', bootstrap_os TEXT NOT NULL DEFAULT 'linux',
                    apply_hostname INTEGER NOT NULL DEFAULT 1, reported_hostname TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'one_time', hostname_pattern_id TEXT, bound_address TEXT NOT NULL DEFAULT '',
                    agent_port INTEGER NOT NULL DEFAULT 8443, report_interval_seconds INTEGER NOT NULL DEFAULT 300,
                    use_count INTEGER NOT NULL DEFAULT 0, apmid_id TEXT, environment_id TEXT, managed_group_id TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hosts_manager_settings(
                    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hostname_sequences(
                    hostname_template TEXT PRIMARY KEY COLLATE NOCASE, next_value INTEGER NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS hostname_reservations(
                    hostname TEXT PRIMARY KEY COLLATE NOCASE, hostname_template TEXT NOT NULL, sequence_value INTEGER NOT NULL,
                    token_id TEXT NOT NULL, pattern_id TEXT,
                    reserved_at REAL NOT NULL, reserved_by TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_hm_reservation_token_hostname ON hostname_reservations(token_id,hostname);
                CREATE TABLE IF NOT EXISTS hostname_patterns(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL DEFAULT '', suffix TEXT NOT NULL DEFAULT '',
                    digits INTEGER NOT NULL, start_value INTEGER NOT NULL, step INTEGER NOT NULL, next_value INTEGER NOT NULL,
                    last_value INTEGER, description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hostname_skips(
                    id TEXT PRIMARY KEY, pattern_id TEXT NOT NULL, sequence_value INTEGER NOT NULL, hostname TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, created_by TEXT NOT NULL,
                    FOREIGN KEY(pattern_id) REFERENCES hostname_patterns(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS environments(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT '#187eb1', default_hostname_pattern_id TEXT, default_credential_id TEXT,
                    default_agent_port INTEGER NOT NULL DEFAULT 8443, report_interval_seconds INTEGER NOT NULL DEFAULT 300,
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS apmid_environment_groups(
                    apmid_id TEXT NOT NULL, environment_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    PRIMARY KEY(apmid_id,environment_id),
                    FOREIGN KEY(apmid_id) REFERENCES apmids(id) ON DELETE RESTRICT,
                    FOREIGN KEY(environment_id) REFERENCES environments(id) ON DELETE RESTRICT,
                    FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE RESTRICT);
                CREATE INDEX IF NOT EXISTS idx_hm_apmid_environment_group ON apmid_environment_groups(group_id);
                CREATE TABLE IF NOT EXISTS host_agents(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL UNIQUE, installation_id TEXT NOT NULL UNIQUE,
                    token_hash TEXT NOT NULL, agent_version TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
                    communication_port INTEGER NOT NULL DEFAULT 8443, report_interval_seconds INTEGER NOT NULL DEFAULT 300,
                    installed_at REAL NOT NULL, last_heartbeat_at REAL, last_report_at REAL, last_error TEXT NOT NULL DEFAULT '',
                    certificate_status TEXT NOT NULL DEFAULT 'token', auth_failures INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS host_identity_salts(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, agent_id TEXT NOT NULL, salt TEXT NOT NULL,
                    identity_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'valid', generated_at REAL NOT NULL,
                    regenerated_at REAL, invalidated_at REAL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE,
                    FOREIGN KEY(agent_id) REFERENCES host_agents(id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS idx_hm_identity_host ON host_identity_salts(host_id,generated_at DESC);
                CREATE TABLE IF NOT EXISTS host_reports(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, agent_id TEXT NOT NULL, report_json TEXT NOT NULL,
                    checksum TEXT NOT NULL, created_at REAL NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE,
                    FOREIGN KEY(agent_id) REFERENCES host_agents(id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS idx_hm_reports_host ON host_reports(host_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS agent_versions(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, agent_id TEXT NOT NULL, version TEXT NOT NULL,
                    source TEXT NOT NULL, reported_at REAL NOT NULL, reported_by TEXT NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE,
                    FOREIGN KEY(agent_id) REFERENCES host_agents(id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS idx_hm_agent_versions_host ON agent_versions(host_id,reported_at DESC);
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
            token_columns = {row[1] for row in connection.execute("PRAGMA table_info(enrollment_tokens)")}
            for name, definition in (
                ("assigned_hostname", "TEXT NOT NULL DEFAULT ''"),
                ("bootstrap_os", "TEXT NOT NULL DEFAULT 'linux'"),
                ("apply_hostname", "INTEGER NOT NULL DEFAULT 1"),
                ("reported_hostname", "TEXT NOT NULL DEFAULT ''"),
                ("mode", "TEXT NOT NULL DEFAULT 'one_time'"),
                ("hostname_pattern_id", "TEXT"),
                ("bound_address", "TEXT NOT NULL DEFAULT ''"),
                ("agent_port", "INTEGER NOT NULL DEFAULT 8443"),
                ("report_interval_seconds", "INTEGER NOT NULL DEFAULT 300"),
                ("use_count", "INTEGER NOT NULL DEFAULT 0"),
                ("apmid_id", "TEXT"),
                ("environment_id", "TEXT"),
                ("managed_group_id", "TEXT"),
            ):
                if name not in token_columns:
                    connection.execute(f"ALTER TABLE enrollment_tokens ADD COLUMN {name} {definition}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_hm_enrollment_apmid_environment ON enrollment_tokens(apmid_id,environment_id)"
            )
            credential_columns = {row[1] for row in connection.execute("PRAGMA table_info(credentials)")}
            for name, definition in (("environment_id", "TEXT"), ("last_used_at", "REAL")):
                if name not in credential_columns:
                    connection.execute(f"ALTER TABLE credentials ADD COLUMN {name} {definition}")
            reservation_columns = {row[1] for row in connection.execute("PRAGMA table_info(hostname_reservations)")}
            if "pattern_id" not in reservation_columns:
                connection.execute("ALTER TABLE hostname_reservations ADD COLUMN pattern_id TEXT")
            defaults = HostsManagerSettingsUpdate().model_dump(mode="json")
            for key, value in defaults.items():
                connection.execute(
                    "INSERT OR IGNORE INTO hosts_manager_settings(key,value_json,updated_at,updated_by) VALUES(?,?,?,?)",
                    (key, json.dumps(value), now, ""),
                )
            connection.execute(
                """INSERT OR IGNORE INTO hostname_patterns(
                    id,name,prefix,suffix,digits,start_value,step,next_value,description,active,
                    created_at,updated_at,created_by,updated_by
                ) VALUES('default','Default SCL','SCL000','',3,1,1,1,'Migrated default hostname pattern',1,?,?,?,?)""",
                (now, now, "system", "system"),
            )
            connection.execute(
                """INSERT OR IGNORE INTO environments(
                    id,name,slug,description,color,default_hostname_pattern_id,default_agent_port,report_interval_seconds,
                    active,created_at,updated_at,created_by,updated_by
                ) VALUES('default','Default','default','Default environment','#187eb1','default',8443,300,1,?,?,?,?)""",
                (now, now, "system", "system"),
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
        for key in ("active", "approved", "require_approval", "onboard_ansible", "sync_before_use", "verify_tls", "managed_user_created", "apply_hostname"):
            if key in result:
                result[key] = bool(result[key])
        return result

    def _list(self, table: str, *, where: str = "", values: tuple[Any, ...] = (), order: str = "updated_at DESC", limit: int = 5000) -> list[dict[str, Any]]:
        allowed = {
            "hosts", "groups", "credentials", "host_keys", "facts", "enrollment_tokens", "repositories",
            "repository_syncs", "power_profiles", "operations", "scans", "memberships", "environments",
            "hostname_patterns", "hostname_skips", "host_agents", "host_identity_salts", "host_reports", "agent_versions",
            "apmids",
        }
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
        agents = self._list("host_agents", where="host_id=?", values=(host_id,), order="updated_at DESC", limit=1)
        agent = agents[0] if agents else None
        reports = self._list("host_reports", where="host_id=?", values=(host_id,), order="created_at DESC", limit=1)
        report = reports[0].get("report", {}) if reports else {}
        identities = self._list(
            "host_identity_salts", where="host_id=?", values=(host_id,), order="generated_at DESC", limit=1
        )
        if agent:
            agent = {key: value for key, value in agent.items() if key != "token_hash"}
            heartbeat_interval = int(self._settings_value("heartbeat_interval_seconds", 30))
            last_heartbeat = float(agent.get("last_heartbeat_at") or 0)
            if last_heartbeat and time.time() - last_heartbeat > max(heartbeat_interval * 3, 60):
                agent["status"] = "offline"
                item["connection_status"] = "offline"
            elif agent.get("status") in {"online", "warning", "error"}:
                item["connection_status"] = str(agent["status"])
        item["agent"] = agent
        item["agent_status"] = str(agent["status"]) if agent else "not_installed"
        item["latest_report"] = report
        item["identity"] = (
            {key: value for key, value in identities[0].items() if key != "salt"}
            if identities else None
        )
        environment = None
        if item.get("environment"):
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM environments WHERE id=? OR slug=? LIMIT 1",
                    (item["environment"], item["environment"]),
                ).fetchone()
            environment = self._decode(row)
        item["environment_details"] = environment
        basic = report.get("basic", {}) if isinstance(report, dict) else {}
        packages = report.get("packages", {}) if isinstance(report, dict) else {}
        item["distribution"] = basic.get("distribution") or item["facts"].get("distribution", "")
        item["system_version"] = basic.get("system_version") or item["facts"].get("distribution_version", "")
        item["agent_version"] = (agent or {}).get("agent_version", "")
        item["available_updates"] = int(packages.get("available_updates_count") or 0)
        item["security_updates"] = int(packages.get("security_updates_count") or 0)
        if not item.get("active"):
            item["status"] = "disabled"
        elif not item.get("approved"):
            item["status"] = "pending"
        elif item["agent_status"] == "not_installed":
            item["status"] = "unregistered"
        elif item["agent_status"] in {"warning", "error", "offline", "online"}:
            item["status"] = item["agent_status"]
        else:
            item["status"] = str(item.get("registration_status") or "pending")
        item["credential"] = self.connection_data(host_id).get("credential")
        return item

    def _settings_value(self, key: str, default: Any) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT value_json FROM hosts_manager_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

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
        with self.connect() as connection:
            managed = {
                str(row["group_id"]): {
                    "apmid_id": str(row["apmid_id"]),
                    "environment_id": str(row["environment_id"]),
                }
                for row in connection.execute(
                    "SELECT apmid_id,environment_id,group_id FROM apmid_environment_groups"
                ).fetchall()
            }
        for group in groups:
            group["host_ids"] = [item["host_id"] for item in memberships if item["group_id"] == group["id"]]
            group["managed"] = group["id"] in managed
            group["managed_by"] = managed.get(group["id"])
        return groups

    def save_group(self, payload: GroupInput, actor: str, group_id: str | None = None) -> dict[str, Any]:
        now, item_id = time.time(), group_id or stable_id()
        with self.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM apmid_environment_groups WHERE group_id=?", (item_id,)
            ).fetchone():
                raise ManagedGroupProtectedError("APMID environment groups can be changed only through APMID or environment settings")
            conflict = connection.execute(
                "SELECT id FROM groups WHERE name=? COLLATE NOCASE AND id<>?",
                (payload.name, item_id),
            ).fetchone()
            if conflict:
                raise ManagedGroupConflictError("group name already exists")
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
            if connection.execute(
                "SELECT 1 FROM apmid_environment_groups WHERE group_id=?", (group_id,)
            ).fetchone():
                raise ManagedGroupProtectedError("APMID environment groups cannot be deleted manually")
            return bool(connection.execute("DELETE FROM groups WHERE id=?", (group_id,)).rowcount)

    @staticmethod
    def _managed_group_name(apmid_code: str, environment_slug: str) -> str:
        return f"{apmid_code}.{environment_slug}".upper()

    def _sync_apmid_environment_groups_locked(self, connection: sqlite3.Connection, actor: str) -> dict[str, int]:
        now = time.time()
        apmids = self.apmid_service.all_for_hosts()
        # Compatibility rows only satisfy the legacy relation foreign key and
        # remain a rollback snapshot. Reads and writes use ApmidService.
        for apmid in apmids:
            connection.execute(
                """INSERT INTO apmids(id,code,description,active,created_at,updated_at,created_by,updated_by)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET code=excluded.code,description=excluded.description,
                     active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (
                    apmid["id"], apmid["code"], apmid["description"], int(apmid["active"]),
                    apmid["created_at"], apmid["updated_at"], apmid["created_by"], apmid["updated_by"],
                ),
            )
        environments = connection.execute("SELECT id,slug,active FROM environments ORDER BY slug").fetchall()
        relations = {
            (str(row["apmid_id"]), str(row["environment_id"])): str(row["group_id"])
            for row in connection.execute(
                "SELECT apmid_id,environment_id,group_id FROM apmid_environment_groups"
            ).fetchall()
        }
        planned: list[tuple[dict[str, Any], sqlite3.Row, str, str | None]] = []
        for apmid in apmids:
            for environment in environments:
                key = (str(apmid["id"]), str(environment["id"]))
                group_id = relations.get(key)
                enabled = bool(apmid["active"]) and bool(environment["active"])
                if not enabled and not group_id:
                    continue
                name = self._managed_group_name(str(apmid["code"]), str(environment["slug"]))
                collision = connection.execute(
                    "SELECT id FROM groups WHERE name=? COLLATE NOCASE AND id<>?",
                    (name, group_id or ""),
                ).fetchone()
                if collision:
                    raise ManagedGroupConflictError(f"managed group name conflicts with existing group: {name}")
                planned.append((apmid, environment, name, group_id))

        created = 0
        updated = 0
        for apmid, environment, name, group_id in planned:
            enabled_value = int(bool(apmid["active"]) and bool(environment["active"]))
            description = f"Managed group for APMID {apmid['code']} and environment {environment['slug']}"
            if group_id:
                group = connection.execute("SELECT name,description,active FROM groups WHERE id=?", (group_id,)).fetchone()
                if not group:
                    raise ManagedGroupProtectedError("managed APMID group relation is damaged")
                if str(group["name"]) != name or str(group["description"]) != description or int(group["active"]) != enabled_value:
                    connection.execute(
                        "UPDATE groups SET name=?,description=?,active=?,updated_at=?,updated_by=? WHERE id=?",
                        (name, description, enabled_value, now, actor, group_id),
                    )
                    connection.execute(
                        "UPDATE apmid_environment_groups SET updated_at=?,updated_by=? WHERE apmid_id=? AND environment_id=?",
                        (now, actor, apmid["id"], environment["id"]),
                    )
                    updated += 1
                continue
            group_id = stable_id()
            connection.execute(
                """INSERT INTO groups(
                    id,name,description,parent_id,variables_json,active,created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (group_id, name, description, None, "{}", enabled_value, now, now, actor, actor),
            )
            connection.execute(
                """INSERT INTO apmid_environment_groups(
                    apmid_id,environment_id,group_id,created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?)""",
                (apmid["id"], environment["id"], group_id, now, now, actor, actor),
            )
            created += 1
        return {"created": created, "updated": updated, "total": len(planned)}

    def sync_apmid_environment_groups(self, actor: str) -> dict[str, int]:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._sync_apmid_environment_groups_locked(connection, actor)

    def apmids(self) -> list[dict[str, Any]]:
        items = self.apmid_service.all_for_hosts()
        with self.connect() as connection:
            relations = connection.execute(
                """SELECT relation.apmid_id,relation.environment_id,relation.group_id,
                          environments.name AS environment_name,environments.slug AS environment_slug,
                          groups.name AS group_name,groups.active AS group_active
                   FROM apmid_environment_groups relation
                   JOIN environments ON environments.id=relation.environment_id
                   JOIN groups ON groups.id=relation.group_id
                   ORDER BY environments.name"""
            ).fetchall()
        for item in items:
            item["environment_groups"] = [
                {
                    "environment_id": str(row["environment_id"]),
                    "environment_name": str(row["environment_name"]),
                    "environment_slug": str(row["environment_slug"]),
                    "group_id": str(row["group_id"]),
                    "group_name": str(row["group_name"]),
                    "active": bool(row["group_active"]),
                }
                for row in relations if str(row["apmid_id"]) == str(item["id"])
            ]
        return items

    def save_apmid(self, payload: ApmidInput, actor: str, apmid_id: str | None = None) -> dict[str, Any]:
        previous = self.apmid_service.get(apmid_id) if apmid_id else None
        domain_payload = DomainApmidInput(
            code=payload.code, name=payload.code, description=payload.description, active=payload.active,
        )
        try:
            item = self.apmid_service.update(apmid_id, domain_payload, actor) if apmid_id else self.apmid_service.create(domain_payload, actor)
        except DomainApmidConflictError as error:
            raise ManagedGroupConflictError(str(error)) from error
        except DomainApmidNotFoundError as error:
            raise KeyError("APMID not found") from error
        try:
            with self._lock, self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._sync_apmid_environment_groups_locked(connection, actor)
        except Exception:
            if previous:
                self.apmid_service.update(
                    str(previous["id"]),
                    DomainApmidInput(
                        code=str(previous["code"]), name=str(previous["name"]), description=str(previous["description"]),
                        active=bool(previous["active"]), business_owner=previous.get("business_owner"),
                    ),
                    actor,
                )
            else:
                self.apmid_service.delete(str(item["id"]), actor)
            raise
        return next(value for value in self.apmids() if value["id"] == item["id"])

    def delete_apmid(self, apmid_id: str, actor: str = "hosts-manager") -> bool:
        if not self.apmid_service.get(apmid_id):
            return False
        usages = self.apmid_service.usages(apmid_id)
        if usages:
            raise ApmidInUseError("APMID is referenced by Hosts Manager")
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            relations = connection.execute(
                "SELECT group_id FROM apmid_environment_groups WHERE apmid_id=?", (apmid_id,)
            ).fetchall()
            connection.execute("DELETE FROM apmid_environment_groups WHERE apmid_id=?", (apmid_id,))
            connection.executemany("DELETE FROM groups WHERE id=?", [(row["group_id"],) for row in relations])
        try:
            self.apmid_service.delete(apmid_id, actor)
        except DomainApmidInUseError as error:
            raise ApmidInUseError("APMID is referenced by Hosts Manager") from error
        return True

    def environments(self) -> list[dict[str, Any]]:
        items = self._list("environments", order="name")
        with self.connect() as connection:
            counts = {
                str(row["environment"]): int(row["count"])
                for row in connection.execute(
                    "SELECT environment,COUNT(*) AS count FROM hosts WHERE active=1 GROUP BY environment"
                ).fetchall()
            }
        return [item | {"host_count": counts.get(item["id"], counts.get(item["slug"], 0))} for item in items]

    def save_environment(self, payload: EnvironmentInput, actor: str, environment_id: str | None = None) -> dict[str, Any]:
        now, item_id, value = time.time(), environment_id or stable_id(), payload.model_dump(mode="json")
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT created_at,created_by FROM environments WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            if value["default_hostname_pattern_id"] and not connection.execute(
                "SELECT 1 FROM hostname_patterns WHERE id=? AND active=1", (value["default_hostname_pattern_id"],)
            ).fetchone():
                raise KeyError("hostname pattern not found")
            if value["default_credential_id"] and not connection.execute(
                "SELECT 1 FROM credentials WHERE id=? AND active=1 AND type IN ('ssh_password','ssh_private_key')",
                (value["default_credential_id"],),
            ).fetchone():
                raise KeyError("credential not found")
            connection.execute(
                """INSERT INTO environments(
                    id,name,slug,description,color,default_hostname_pattern_id,default_credential_id,
                    default_agent_port,report_interval_seconds,active,created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,slug=excluded.slug,description=excluded.description,
                    color=excluded.color,default_hostname_pattern_id=excluded.default_hostname_pattern_id,
                    default_credential_id=excluded.default_credential_id,default_agent_port=excluded.default_agent_port,
                    report_interval_seconds=excluded.report_interval_seconds,active=excluded.active,
                    updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (
                    item_id, value["name"], value["slug"], value["description"], value["color"],
                    value["default_hostname_pattern_id"], value["default_credential_id"], value["default_agent_port"],
                    value["report_interval_seconds"], int(value["active"]), created_at, now, created_by, actor,
                ),
            )
            self._sync_apmid_environment_groups_locked(connection, actor)
        return next(item for item in self.environments() if item["id"] == item_id)

    def delete_environment(self, environment_id: str) -> bool:
        environment = self._get("environments", environment_id)
        if not environment:
            return False
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM enrollment_tokens WHERE environment_id=? LIMIT 1", (environment_id,)
            ).fetchone():
                raise ValueError("environment is referenced by enrollment tokens")
            assigned = connection.execute(
                "SELECT COUNT(*) FROM hosts WHERE active=1 AND environment IN (?,?)",
                (environment_id, environment["slug"]),
            ).fetchone()[0]
            if assigned:
                raise ValueError("environment has assigned hosts")
            relations = connection.execute(
                "SELECT group_id FROM apmid_environment_groups WHERE environment_id=?", (environment_id,)
            ).fetchall()
            if any(connection.execute(
                "SELECT 1 FROM memberships WHERE group_id=? LIMIT 1", (row["group_id"],)
            ).fetchone() for row in relations):
                raise ValueError("environment managed group contains hosts")
            connection.execute("DELETE FROM apmid_environment_groups WHERE environment_id=?", (environment_id,))
            connection.executemany("DELETE FROM groups WHERE id=?", [(row["group_id"],) for row in relations])
            return bool(connection.execute("DELETE FROM environments WHERE id=?", (environment_id,)).rowcount)

    @staticmethod
    def _pattern_template(item: dict[str, Any]) -> str:
        return f"{item['prefix']}{'X' * int(item['digits'])}{item['suffix']}"

    @staticmethod
    def _render_pattern(item: dict[str, Any], sequence: int) -> str:
        width = int(item["digits"])
        if sequence < 1 or sequence > (10**width) - 1:
            raise OverflowError("hostname sequence is exhausted")
        return f"{item['prefix']}{sequence:0{width}d}{item['suffix']}"

    def _next_pattern_value_locked(self, connection: sqlite3.Connection, item: dict[str, Any]) -> int:
        candidate = max(int(item["start_value"]), int(item["next_value"]))
        step = int(item["step"])
        while candidate <= (10 ** int(item["digits"])) - 1:
            hostname = self._render_pattern(item, candidate)
            collision = connection.execute(
                "SELECT 1 FROM hosts WHERE name=? COLLATE NOCASE OR hostname=? COLLATE NOCASE "
                "UNION ALL SELECT 1 FROM hostname_reservations WHERE hostname=? COLLATE NOCASE LIMIT 1",
                (hostname, hostname, hostname),
            ).fetchone()
            if not collision:
                return candidate
            candidate += step
        raise OverflowError("hostname sequence is exhausted")

    def hostname_patterns(self) -> list[dict[str, Any]]:
        items = self._list("hostname_patterns", order="name")
        with self.connect() as connection:
            result = []
            for item in items:
                sequence = self._next_pattern_value_locked(connection, item)
                maximum = (10 ** int(item["digits"])) - 1
                preview = [
                    self._render_pattern(item, value)
                    for value in (sequence + offset * int(item["step"]) for offset in range(3))
                    if value <= maximum
                ]
                result.append(item | {
                    "template": self._pattern_template(item),
                    "next_hostname": self._render_pattern(item, sequence),
                    "preview_hostnames": preview,
                })
        return result

    def save_hostname_pattern(self, payload: HostnamePatternInput, actor: str, pattern_id: str | None = None) -> dict[str, Any]:
        now, item_id, value = time.time(), pattern_id or stable_id(), payload.model_dump(mode="json")
        with self.connect() as connection:
            old = connection.execute(
                "SELECT created_at,created_by,next_value,last_value FROM hostname_patterns WHERE id=?", (item_id,)
            ).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            next_value = max(value["start_value"], int(old["next_value"])) if old else value["start_value"]
            last_value = old["last_value"] if old else None
            connection.execute(
                """INSERT INTO hostname_patterns(
                    id,name,prefix,suffix,digits,start_value,step,next_value,last_value,description,active,
                    created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,prefix=excluded.prefix,suffix=excluded.suffix,
                    digits=excluded.digits,start_value=excluded.start_value,step=excluded.step,next_value=excluded.next_value,
                    description=excluded.description,active=excluded.active,updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by""",
                (
                    item_id, value["name"], value["prefix"], value["suffix"], value["digits"], value["start_value"],
                    value["step"], next_value, last_value, value["description"], int(value["active"]),
                    created_at, now, created_by, actor,
                ),
            )
        return next(item for item in self.hostname_patterns() if item["id"] == item_id)

    def delete_hostname_pattern(self, pattern_id: str) -> bool:
        with self.connect() as connection:
            referenced = connection.execute(
                "SELECT 1 FROM environments WHERE default_hostname_pattern_id=? AND active=1 LIMIT 1", (pattern_id,)
            ).fetchone()
            if referenced:
                raise ValueError("hostname pattern is assigned to an environment")
            return bool(connection.execute("UPDATE hostname_patterns SET active=0 WHERE id=?", (pattern_id,)).rowcount)

    def skip_hostname_pattern(self, pattern_id: str, count: int, reason: str, actor: str) -> dict[str, Any]:
        now = time.time()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM hostname_patterns WHERE id=? AND active=1", (pattern_id,)).fetchone()
            if not row:
                raise KeyError("hostname pattern not found")
            item = self._decode(row) or {}
            sequence = self._next_pattern_value_locked(connection, item)
            skipped: list[str] = []
            for _ in range(count):
                hostname = self._render_pattern(item, sequence)
                skipped.append(hostname)
                connection.execute(
                    "INSERT INTO hostname_skips(id,pattern_id,sequence_value,hostname,reason,created_at,created_by) VALUES(?,?,?,?,?,?,?)",
                    (stable_id(), pattern_id, sequence, hostname, reason, now, actor),
                )
                sequence += int(item["step"])
            connection.execute(
                "UPDATE hostname_patterns SET next_value=?,updated_at=?,updated_by=? WHERE id=?",
                (sequence, now, actor, pattern_id),
            )
        pattern = next(item for item in self.hostname_patterns() if item["id"] == pattern_id)
        return {"skipped": skipped, "pattern": pattern}

    def credentials(self) -> list[dict[str, Any]]:
        items = self._list("credentials", order="name")
        with self.connect() as connection:
            counts = {
                str(row["credential_id"]): int(row["count"])
                for row in connection.execute(
                    "SELECT credential_id,COUNT(*) AS count FROM hosts WHERE credential_id IS NOT NULL GROUP BY credential_id"
                ).fetchall()
            }
        return [self._credential_metadata(item) | {"host_count": counts.get(item["id"], 0)} for item in items]

    @staticmethod
    def _credential_metadata(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "encrypted_secret"} | {"secret_configured": bool(item.get("encrypted_secret"))}

    def save_credential(self, payload: CredentialInput, actor: str, credential_id: str | None = None) -> dict[str, Any]:
        now, item_id = time.time(), credential_id or stable_id()
        envelope = self.cipher.encrypt(json.dumps({"secret": payload.secret, "passphrase": payload.passphrase}), associated_data=item_id) if payload.secret else ""
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM credentials WHERE id=?", (item_id,)).fetchone()
            created_at, created_by = (old["created_at"], old["created_by"]) if old else (now, actor)
            connection.execute("""INSERT INTO credentials(id,name,type,username,description,encrypted_secret,active,environment_id,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,1,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,type=excluded.type,username=excluded.username,description=excluded.description,encrypted_secret=excluded.encrypted_secret,active=1,environment_id=excluded.environment_id,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, payload.name, payload.type.value, payload.username, payload.description, envelope, payload.environment_id, created_at, now, created_by, actor))
        return self._credential_metadata(self._get("credentials", item_id) or {})

    def verified_credential(self, credential_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
        if not module_id or not purpose:
            raise PermissionError("a controlled backend credential context is required")
        item = self._get("credentials", credential_id)
        if not item or not item.get("active") or not item.get("encrypted_secret"):
            raise KeyError("credential not found")
        value = json.loads(self.cipher.decrypt(str(item["encrypted_secret"]), associated_data=credential_id))
        with self.connect() as connection:
            connection.execute("UPDATE credentials SET last_used_at=? WHERE id=?", (time.time(), credential_id))
        self.operation(
            None,
            "credential.use",
            module_id,
            status="completed",
            stage="audit",
            progress=100,
            details={"credential_id": credential_id, "module_id": module_id, "purpose": purpose},
        )
        return {"id": credential_id, "type": str(item["type"]), "username": str(item["username"]), "secret": str(value.get("secret", "")), "passphrase": str(value.get("passphrase", ""))}

    def delete_credential(self, credential_id: str) -> bool:
        with self.connect() as connection:
            referenced = connection.execute(
                "SELECT 1 FROM hosts WHERE credential_id=? AND active=1 "
                "UNION ALL SELECT 1 FROM environments WHERE default_credential_id=? AND active=1 LIMIT 1",
                (credential_id, credential_id),
            ).fetchone()
            if referenced:
                raise ValueError("credential is assigned to an active host or environment")
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

    @staticmethod
    def _template_sequence(template: str, hostname: str) -> int | None:
        prefix, width, suffix = hostname_template_parts(template)
        match = re.fullmatch(rf"{re.escape(prefix)}(\d{{{width}}}){re.escape(suffix)}", hostname, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _settings_locked(self, connection: sqlite3.Connection) -> dict[str, Any]:
        rows = connection.execute("SELECT key,value_json,updated_at,updated_by FROM hosts_manager_settings").fetchall()
        values = {str(row["key"]): json.loads(row["value_json"]) for row in rows}
        defaults = HostsManagerSettingsUpdate().model_dump(mode="json")
        updated = max(rows, key=lambda row: float(row["updated_at"])) if rows else None
        return defaults | values | {
            "updated_at": float(updated["updated_at"]) if updated else 0,
            "updated_by": str(updated["updated_by"]) if updated else "",
        }

    def _next_sequence_locked(self, connection: sqlite3.Connection, template: str) -> int:
        row = connection.execute(
            "SELECT next_value FROM hostname_sequences WHERE hostname_template=? COLLATE NOCASE", (template,)
        ).fetchone()
        next_value = max(1, int(row["next_value"])) if row else 1
        candidates = connection.execute(
            "SELECT name AS hostname FROM hosts UNION ALL SELECT hostname FROM hosts "
            "UNION ALL SELECT hostname FROM hostname_reservations"
        ).fetchall()
        matched = [value for item in candidates if (value := self._template_sequence(template, str(item["hostname"]))) is not None]
        next_value = max(next_value, max(matched, default=0) + 1)
        render_hostname(template, next_value)
        return next_value

    def settings(self) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            value = self._settings_locked(connection)
            sequence = self._next_sequence_locked(connection, value["hostname_template"])
        _, width, _ = hostname_template_parts(value["hostname_template"])
        return value | {
            "next_hostname": render_hostname(value["hostname_template"], sequence),
            "sequence_width": width,
            "preview_hostnames": [
                render_hostname(value["hostname_template"], sequence + offset)
                for offset in range(3)
                if sequence + offset <= (10**width) - 1
            ],
        }

    def save_settings(self, payload: HostsManagerSettingsUpdate, actor: str) -> tuple[dict[str, Any], dict[str, Any]]:
        now = time.time()
        values = payload.model_dump(mode="json")
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._settings_locked(connection)
            pattern_id = values.get("default_hostname_pattern_id")
            if pattern_id and not connection.execute(
                "SELECT 1 FROM hostname_patterns WHERE id=? AND active=1",
                (pattern_id,),
            ).fetchone():
                raise KeyError("default hostname pattern not found")
            for key, value in values.items():
                connection.execute(
                    "INSERT INTO hosts_manager_settings(key,value_json,updated_at,updated_by) VALUES(?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                    (key, json.dumps(value), now, actor),
                )
            sequence = self._next_sequence_locked(connection, str(values["hostname_template"]))
            connection.execute(
                "INSERT INTO hostname_sequences(hostname_template,next_value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(hostname_template) DO UPDATE SET next_value=MAX(next_value,excluded.next_value),updated_at=excluded.updated_at",
                (values["hostname_template"], sequence, now),
            )
        return previous, self.settings()

    def create_enrollment_token(self, payload: EnrollmentTokenInput, actor: str) -> dict[str, Any]:
        now, item_id, token = time.time(), stable_id(), secrets.token_urlsafe(32)
        value = payload.model_dump(mode="json")
        expires = 0 if value["mode"] == "permanent" else now + int(value["expires_minutes"]) * 60
        apmid = self.apmid_service.active(str(value["apmid_id"]))
        if not apmid:
            raise KeyError("APMID not found or inactive")
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            settings = self._settings_locked(connection)
            environment = connection.execute(
                "SELECT * FROM environments WHERE id=? AND active=1", (value["environment_id"],)
            ).fetchone()
            if not environment:
                raise KeyError("environment not found or inactive")
            self._sync_apmid_environment_groups_locked(connection, actor)
            managed = connection.execute(
                """SELECT relation.group_id,groups.name
                   FROM apmid_environment_groups relation
                   JOIN groups ON groups.id=relation.group_id
                   WHERE relation.apmid_id=? AND relation.environment_id=? AND groups.active=1""",
                (value["apmid_id"], value["environment_id"]),
            ).fetchone()
            if not managed:
                raise KeyError("APMID environment group not found")
            requested_group_ids = list(dict.fromkeys(value["group_ids"]))
            selected_groups: list[sqlite3.Row] = []
            if requested_group_ids:
                placeholders = ",".join("?" for _ in requested_group_ids)
                selected_groups = connection.execute(
                    f"SELECT id,active FROM groups WHERE id IN ({placeholders})", requested_group_ids
                ).fetchall()
                if len(selected_groups) != len(requested_group_ids) or any(not row["active"] for row in selected_groups):
                    raise KeyError("additional group not found or inactive")
                other_managed = {
                    str(row["group_id"])
                    for row in connection.execute(
                        "SELECT group_id FROM apmid_environment_groups WHERE group_id<>?", (managed["group_id"],)
                    ).fetchall()
                }
                if any(group_id in other_managed for group_id in requested_group_ids):
                    raise ManagedGroupProtectedError("another APMID managed group cannot be selected manually")
            group_ids = [str(managed["group_id"]), *[
                group_id for group_id in requested_group_ids if group_id != str(managed["group_id"])
            ]]
            pattern_id = value["hostname_pattern_id"] or (
                environment["default_hostname_pattern_id"]
            ) or settings.get("default_hostname_pattern_id")
            pattern_row = connection.execute(
                "SELECT * FROM hostname_patterns WHERE id=? AND active=1", (pattern_id,)
            ).fetchone() if pattern_id else None
            if pattern_id and not pattern_row:
                raise KeyError("hostname pattern not found")
            pattern = self._decode(pattern_row) if pattern_row else None
            assigned_hostname = ""
            sequence = 0
            if value["mode"] == "one_time":
                if pattern:
                    sequence = self._next_pattern_value_locked(connection, pattern)
                    assigned_hostname = self._render_pattern(pattern, sequence)
                    template = self._pattern_template(pattern)
                    connection.execute(
                        "UPDATE hostname_patterns SET next_value=?,last_value=?,updated_at=?,updated_by=? WHERE id=?",
                        (sequence + int(pattern["step"]), sequence, now, actor, pattern["id"]),
                    )
                else:
                    template = str(settings["hostname_template"])
                    sequence = self._next_sequence_locked(connection, template)
                    assigned_hostname = render_hostname(template, sequence)
                    connection.execute(
                        "INSERT INTO hostname_sequences(hostname_template,next_value,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(hostname_template) DO UPDATE SET next_value=excluded.next_value,updated_at=excluded.updated_at",
                        (template, sequence + 1, now),
                    )
                connection.execute(
                    "INSERT INTO hostname_reservations(hostname,hostname_template,sequence_value,token_id,pattern_id,reserved_at,reserved_by) VALUES(?,?,?,?,?,?,?)",
                    (assigned_hostname, template, sequence, item_id, pattern_id, now, actor),
                )
            else:
                template = self._pattern_template(pattern) if pattern else str(settings["hostname_template"])
            bootstrap_os = str(value["bootstrap_os"] or settings["bootstrap_default_os"])
            apply_hostname = settings["bootstrap_apply_hostname"] if value["apply_hostname"] is None else bool(value["apply_hostname"])
            agent_port = int(value["agent_port"] or environment["default_agent_port"] or settings["agent_default_port"])
            report_interval = int(value["report_interval_seconds"] or environment["report_interval_seconds"] or settings["report_interval_seconds"])
            connection.execute("""INSERT INTO enrollment_tokens(
                    id,token_hash,hostname_pattern,ssh_user,port,credential_id,environment,location,tags_json,group_ids_json,
                    require_approval,onboard_ansible,expires_at,assigned_hostname,bootstrap_os,apply_hostname,mode,
                    hostname_pattern_id,bound_address,agent_port,report_interval_seconds,apmid_id,environment_id,
                    managed_group_id,created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item_id, hashlib.sha256(token.encode()).hexdigest(), assigned_hostname or template, "hosts-manager-agent",
                    22, None, value["environment_id"], value["location"], json.dumps(value["tags"]),
                    json.dumps(group_ids), int(value["require_approval"]), int(value["onboard_ansible"]), expires,
                    assigned_hostname, bootstrap_os, int(apply_hostname), value["mode"], pattern_id, value["bound_address"],
                    agent_port, report_interval, value["apmid_id"], value["environment_id"], managed["group_id"],
                    now, now, actor, actor,
                ))
        return {
            "id": item_id, "token": token, "hostname_pattern": assigned_hostname or template,
            "assigned_hostname": assigned_hostname, "bootstrap_os": bootstrap_os, "apply_hostname": apply_hostname,
            "mode": value["mode"], "hostname_pattern_id": pattern_id, "bound_address": value["bound_address"],
            "agent_port": agent_port, "report_interval_seconds": report_interval, "expires_at": expires,
            "apmid_id": value["apmid_id"], "apmid_code": str(apmid["code"]),
            "environment_id": value["environment_id"], "environment_name": str(environment["name"]),
            "environment_slug": str(environment["slug"]), "managed_group_id": str(managed["group_id"]),
            "managed_group_name": str(managed["name"]), "group_ids": group_ids,
            "created_at": now, "created_by": actor, "used": False,
        }

    def enrollment_tokens(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            apmids = {str(row["id"]): row for row in self.apmid_service.all_for_hosts()}
            environments = {
                str(row["id"]): dict(row)
                for row in connection.execute("SELECT id,name,slug FROM environments").fetchall()
            }
            managed = {
                (str(row["apmid_id"]), str(row["environment_id"])): {
                    "id": str(row["group_id"]),
                    "name": str(row["group_name"]),
                }
                for row in connection.execute(
                    """SELECT relation.apmid_id,relation.environment_id,relation.group_id,groups.name AS group_name
                       FROM apmid_environment_groups relation JOIN groups ON groups.id=relation.group_id"""
                ).fetchall()
            }
            group_names = {
                str(row["id"]): str(row["name"])
                for row in connection.execute("SELECT id,name FROM groups").fetchall()
            }
        def enrich(item: dict[str, Any]) -> dict[str, Any]:
            apmid = apmids.get(str(item.get("apmid_id") or ""))
            environment = environments.get(str(item.get("environment_id") or ""))
            stored_group_id = str(item.get("managed_group_id") or "")
            automatic_group = (
                {"id": stored_group_id, "name": group_names.get(stored_group_id)}
                if stored_group_id else managed.get((
                    str(item.get("apmid_id") or ""),
                    str(item.get("environment_id") or ""),
                ))
            )
            return {key: value for key, value in item.items() if key != "token_hash"} | {
                "used": item.get("used_at") is not None,
                "expired": bool(item["expires_at"] and item["expires_at"] < time.time()),
                "revoked": item.get("revoked_at") is not None,
                "apmid_code": apmid.get("code") if apmid else None,
                "environment_name": environment.get("name") if environment else None,
                "environment_slug": environment.get("slug") if environment else None,
                "managed_group_id": automatic_group.get("id") if automatic_group else None,
                "managed_group_name": automatic_group.get("name") if automatic_group else None,
            }
        return [
            enrich(item)
            for item in self._list("enrollment_tokens")
        ]

    def revoke_enrollment_token(self, token_id: str, actor: str) -> bool:
        with self.connect() as connection:
            return bool(connection.execute("UPDATE enrollment_tokens SET revoked_at=?,updated_at=?,updated_by=? WHERE id=? AND revoked_at IS NULL", (time.time(), time.time(), actor, token_id)).rowcount)

    def claim_enrollment_token(self, token: str, claim: dict[str, Any]) -> dict[str, Any] | None:
        now, token_hash, hostname = time.time(), hashlib.sha256(token.encode()).hexdigest(), str(claim["hostname"])
        existing_host_id: str | None = None
        automatic_group_id = ""
        managed_group_ids: set[str] = set()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM enrollment_tokens WHERE token_hash=? AND revoked_at IS NULL "
                "AND (expires_at=0 OR expires_at>=?) AND (mode='permanent' OR used_at IS NULL)",
                (token_hash, now),
            ).fetchone()
            if not row:
                return None
            try:
                claim_address = ipaddress.ip_address(str(claim["address"]))
            except ValueError:
                return None
            settings = self._settings_locked(connection)
            if not any(
                claim_address in ipaddress.ip_network(value, strict=False)
                for value in settings["allowed_registration_networks"]
            ):
                return None
            if row["bound_address"] and ipaddress.ip_address(str(row["bound_address"])) != claim_address:
                return None
            if row["apmid_id"] or row["environment_id"]:
                if not row["apmid_id"] or not row["environment_id"]:
                    return None
                if not self.apmid_service.active(str(row["apmid_id"])):
                    return None
                relation = connection.execute(
                    """SELECT relation.group_id FROM apmid_environment_groups relation
                       JOIN environments ON environments.id=relation.environment_id AND environments.active=1
                       JOIN groups ON groups.id=relation.group_id AND groups.active=1
                       WHERE relation.apmid_id=? AND relation.environment_id=?""",
                    (row["apmid_id"], row["environment_id"]),
                ).fetchone()
                if not relation:
                    return None
                automatic_group_id = str(relation["group_id"])
                if row["managed_group_id"] and str(row["managed_group_id"]) != automatic_group_id:
                    return None
                managed_group_ids = {
                    str(item["group_id"])
                    for item in connection.execute("SELECT group_id FROM apmid_environment_groups").fetchall()
                }
            assigned = str(row["assigned_hostname"] or "")
            permanent = str(row["mode"]) == "permanent"
            allowed = permanent or (
                hostname.casefold() == assigned.casefold()
                if assigned else fnmatch.fnmatchcase(hostname.casefold(), str(row["hostname_pattern"]).casefold())
            )
            if not allowed:
                return None
            existing_host = connection.execute(
                "SELECT id,registration_status FROM hosts WHERE active=1 AND "
                "(name=? COLLATE NOCASE OR hostname=? COLLATE NOCASE OR address=?) LIMIT 1",
                (hostname, hostname, str(claim["address"])),
            ).fetchone()
            installation_id = str(claim.get("installation_id") or "")
            installation = connection.execute(
                "SELECT host_id FROM host_agents WHERE installation_id=?",
                (installation_id,),
            ).fetchone() if installation_id else None
            if installation and existing_host and str(installation["host_id"]) != str(existing_host["id"]):
                return None
            if installation and not existing_host:
                existing_host = connection.execute(
                    "SELECT id,registration_status FROM hosts WHERE id=? AND active=1",
                    (installation["host_id"],),
                ).fetchone()
            if existing_host and installation_id:
                paired = connection.execute(
                    "SELECT installation_id,status FROM host_agents WHERE host_id=? ORDER BY updated_at DESC LIMIT 1",
                    (existing_host["id"],),
                ).fetchone()
                if (
                    paired
                    and str(paired["installation_id"]) != installation_id
                    and str(paired["status"]) != "authentication_required"
                ):
                    return None
            existing_host_id = str(existing_host["id"]) if existing_host else None
            changed = connection.execute(
                "UPDATE enrollment_tokens SET used_at=CASE WHEN mode='one_time' THEN ? ELSE used_at END,"
                "used_hostname=?,reported_hostname=?,use_count=use_count+1,updated_at=?,updated_by=? "
                "WHERE id=? AND (mode='permanent' OR used_at IS NULL)",
                (now, hostname, str(claim.get("original_hostname") or hostname), now, f"enrollment:{hostname}", row["id"]),
            ).rowcount
            if not changed:
                return None
            token_data = self._decode(row) or {}
        token_group_ids = [
            str(group_id) for group_id in token_data["group_ids"]
            if str(group_id) not in managed_group_ids or str(group_id) == automatic_group_id
        ]
        if automatic_group_id and automatic_group_id not in token_group_ids:
            token_group_ids.insert(0, automatic_group_id)
        host_payload = HostInput(
            name=hostname, hostname=hostname, fqdn=str(claim.get("fqdn") or ""), address=str(claim["address"]),
            port=22, ssh_user="hosts-manager-agent", credential_id=None,
            environment=str(token_data.get("environment_id") or token_data["environment"]),
            location=str(token_data["location"]), tags=token_data["tags"],
            group_ids=token_group_ids, approved=not bool(token_data["require_approval"]),
            variables={
                "enrollment_os": claim.get("os", ""), "enrollment_architecture": claim.get("architecture", ""),
                "enrollment_python": claim.get("python", ""), "original_hostname": claim.get("original_hostname", ""),
                "system_id": claim.get("system_id", ""), "system_version": claim.get("system_version", ""),
                "powershell": claim.get("powershell", ""),
            },
        )
        host = self.save_host(
            host_payload,
            f"enrollment:{hostname}",
            existing_host_id,
            source="script",
        )
        if claim.get("installation_id"):
            agent = self.register_agent(
                host["id"], str(claim["installation_id"]), str(claim.get("agent_version") or "1.0.0"),
                int(token_data.get("agent_port") or 8443), int(token_data.get("report_interval_seconds") or 300),
                f"enrollment:{hostname}",
            )
            host["agent_credentials"] = agent
        return host

    def active_enrollment_token(self, token: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        with self._lock, self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM enrollment_tokens WHERE token_hash=? AND revoked_at IS NULL "
                "AND (expires_at=0 OR expires_at>=?) AND (mode='permanent' OR used_at IS NULL)",
                (token_hash, now),
            ).fetchone()
        return self._decode(row)

    def enrollment_script(self, token: str, endpoint: str) -> tuple[str, dict[str, Any]]:
        token_item = self.active_enrollment_token(token)
        if not token_item or token_item.get("revoked_at") or (
            token_item.get("mode") != "permanent" and (
                token_item.get("used_at") or token_item["expires_at"] < time.time()
            )
        ):
            raise KeyError("enrollment token is not active")
        endpoint = endpoint.rstrip("/")
        if token_item["bootstrap_os"] == "windows":
            return self._windows_enrollment_script(token_item, token, endpoint), token_item
        return f"""#!/usr/bin/env bash
set -euo pipefail
die() {{ printf '%s\\n' "Hosts Manager enrollment failed: $1" >&2; exit 1; }}
[[ "${{EUID}}" -eq 0 ]] || die "run this script as root"
[[ '{endpoint}' == https://* ]] || die "HTTPS is required"
MISSING_DEPENDENCY=false
for required in curl hostname ip awk python3 uname tr install; do
  command -v "$required" >/dev/null 2>&1 || MISSING_DEPENDENCY=true
done
if [[ "$MISSING_DEPENDENCY" == true ]]; then
  . /etc/os-release 2>/dev/null || die "/etc/os-release is required to install dependencies"
  case "${{ID:-}}" in
    debian|ubuntu|raspbian|proxmox)
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl python3 iproute2 hostname coreutils gawk
      ;;
    fedora|rhel|rocky|almalinux|centos)
      manager=dnf; command -v dnf >/dev/null 2>&1 || manager=yum
      "$manager" install -y curl python3 iproute hostname coreutils gawk
      ;;
    opensuse*|sles)
      zypper --non-interactive install curl python3 iproute2 hostname coreutils gawk
      ;;
    arch|manjaro)
      pacman --noconfirm --needed -S curl python iproute2 inetutils coreutils gawk
      ;;
    alpine)
      apk add --no-cache curl python3 iproute2 coreutils gawk
      ;;
    *) die "unsupported distribution and required dependencies are missing" ;;
  esac
fi
for required in curl hostname ip awk python3 uname tr install; do command -v "$required" >/dev/null 2>&1 || die "$required is required"; done
ORIGINAL_HOSTNAME="$(hostname)"
ASSIGNED_HOSTNAME='{token_item["assigned_hostname"]}'
if [[ '{str(bool(token_item["apply_hostname"])).lower()}' == true && -n "$ASSIGNED_HOSTNAME" ]]; then
  if command -v hostnamectl >/dev/null 2>&1; then hostnamectl set-hostname "$ASSIGNED_HOSTNAME"; else
    printf '%s\\n' "$ASSIGNED_HOSTNAME" >/etc/hostname
    hostname "$ASSIGNED_HOSTNAME"
  fi
  [[ "$(hostname | tr '[:upper:]' '[:lower:]')" == "$(printf '%s' "$ASSIGNED_HOSTNAME" | tr '[:upper:]' '[:lower:]')" ]] || die "hostname change verification failed"
fi
HOSTNAME_VALUE="${{ASSIGNED_HOSTNAME:-$(hostname)}}"
FQDN_VALUE="$(hostname -f 2>/dev/null || printf '%s' "$HOSTNAME_VALUE")"
ADDRESS_VALUE="${{WEBNAS_ENROLL_ADDRESS:-$(ip -4 route get 1.1.1.1 | awk '{{for(i=1;i<=NF;i++) if($i=="src") {{print $(i+1); exit}}}}')}}"
[[ -n "$ADDRESS_VALUE" && "$ADDRESS_VALUE" != 127.* && "$ADDRESS_VALUE" != 169.254.* ]] || die "a primary IPv4 address is required"
. /etc/os-release 2>/dev/null || die "/etc/os-release is required"
case "${{ID:-}}" in
  debian|ubuntu|raspbian|fedora|rhel|rocky|almalinux|centos|opensuse*|sles|arch|manjaro|alpine|proxmox) ;;
  *) [[ -f /etc/pve-release ]] || die "unsupported Linux distribution" ;;
esac
OS_VALUE="${{ID:-unknown}}"
OS_VERSION="${{VERSION_ID:-}}"
SYSTEM_ID_VALUE=""
[[ -r /etc/machine-id ]] && IFS= read -r SYSTEM_ID_VALUE </etc/machine-id
[[ -n "$SYSTEM_ID_VALUE" ]] || SYSTEM_ID_VALUE="$OS_VALUE-$OS_VERSION"
install -d -m 0700 /var/lib/hosts-manager-agent
INSTALLATION_ID_FILE=/var/lib/hosts-manager-agent/installation-id
if [[ ! -s "$INSTALLATION_ID_FILE" ]]; then
  python3 - <<'PY' >"$INSTALLATION_ID_FILE"
import uuid
print(uuid.uuid4())
PY
  chmod 0600 "$INSTALLATION_ID_FILE"
fi
INSTALLATION_ID="$(cat "$INSTALLATION_ID_FILE")"
ARCH_VALUE="$(uname -m)"
PYTHON_VALUE="$(command -v python3)"
export HOSTNAME_VALUE FQDN_VALUE ADDRESS_VALUE OS_VALUE OS_VERSION SYSTEM_ID_VALUE ARCH_VALUE PYTHON_VALUE ORIGINAL_HOSTNAME INSTALLATION_ID
BODY="$(python3 - <<'PY'
import json, os
keys = ("HOSTNAME_VALUE", "FQDN_VALUE", "ADDRESS_VALUE", "OS_VALUE", "OS_VERSION", "SYSTEM_ID_VALUE", "ARCH_VALUE", "PYTHON_VALUE", "ORIGINAL_HOSTNAME", "INSTALLATION_ID")
v = {{key: os.environ[key] for key in keys}}
print(json.dumps({{"hostname": v["HOSTNAME_VALUE"], "fqdn": v["FQDN_VALUE"], "address": v["ADDRESS_VALUE"], "os": v["OS_VALUE"], "system_id": v["SYSTEM_ID_VALUE"], "system_version": v["OS_VERSION"], "architecture": v["ARCH_VALUE"], "python": v["PYTHON_VALUE"], "original_hostname": v["ORIGINAL_HOSTNAME"], "installation_id": v["INSTALLATION_ID"], "agent_version": "1.0.0"}}))
PY
)"
RESULT="$(curl --fail --silent --show-error --proto '=https' --tlsv1.2 -X POST -H 'Content-Type: application/json' -H 'Authorization: Bearer {token}' --data "$BODY" '{endpoint}/api/modules/hosts-manager/enroll')" || die "server rejected enrollment"
install -d -m 0755 /opt/hosts-manager-agent /etc/hosts-manager-agent /var/log/hosts-manager-agent
curl --fail --silent --show-error --proto '=https' --tlsv1.2 '{endpoint}/api/modules/hosts-manager/agent/source' -o /opt/hosts-manager-agent/agent.py
chmod 0755 /opt/hosts-manager-agent/agent.py
RESULT_FILE=/var/lib/hosts-manager-agent/enrollment-result.json
printf '%s' "$RESULT" >"$RESULT_FILE"
chmod 0600 "$RESULT_FILE"
python3 - "$RESULT_FILE" <<'PY'
import json, os, sys, time
path = sys.argv[1]
with open(path, encoding="utf-8") as source:
    result = json.load(source)
credentials = result.get("agent_credentials") or {{}}
required = ("agent_id", "host_id", "token")
if any(not credentials.get(key) for key in required):
    raise SystemExit("server did not return agent credentials")
config = {{
    "server": {{"url": "{endpoint}", "timeout_seconds": {int(self._settings_value("connection_timeout_seconds", 15))}, "verify_tls": {str(bool(self._settings_value("agent_enforce_tls", True)))} }},
    "agent": {{
        "heartbeat_interval": {int(self._settings_value("heartbeat_interval_seconds", 30))},
        "report_interval": {int(token_item.get("report_interval_seconds") or 300)},
        "max_retries": {int(self._settings_value("max_connection_retries", 10))}
    }},
    "authentication": {{}},
    "logging": {{"level": "{str(self._settings_value("agent_log_level", "INFO"))}", "file": "/var/log/hosts-manager-agent/agent.log"}}
}}
state = {{
    "installation_id": open("/var/lib/hosts-manager-agent/installation-id", encoding="utf-8").read().strip(),
    "host_id": credentials["host_id"], "agent_id": credentials["agent_id"], "token": credentials["token"],
    "identity_hash": credentials.get("identity_hash", ""), "registered_at": time.time()
}}
for target, value in (("/etc/hosts-manager-agent/config.yaml", config), ("/var/lib/hosts-manager-agent/state.json", state)):
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
os.remove(path)
PY
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  cat >/etc/systemd/system/hosts-manager-agent.service <<'UNIT'
[Unit]
Description=Hosts Manager Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/env python3 /opt/hosts-manager-agent/agent.py run
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/hosts-manager-agent /var/lib/hosts-manager-agent /var/log/hosts-manager-agent /etc/hosts-manager-agent

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now hosts-manager-agent.service
elif command -v rc-update >/dev/null 2>&1; then
  cat >/etc/init.d/hosts-manager-agent <<'RC'
#!/sbin/openrc-run
name="Hosts Manager Agent"
command="/usr/bin/env"
command_args="python3 /opt/hosts-manager-agent/agent.py run"
command_background="yes"
pidfile="/run/hosts-manager-agent.pid"
output_log="/var/log/hosts-manager-agent/agent.log"
error_log="/var/log/hosts-manager-agent/agent.log"
depend() {{ need net; }}
RC
  chmod 0755 /etc/init.d/hosts-manager-agent
  rc-update add hosts-manager-agent default
  rc-service hosts-manager-agent restart
else
  (crontab -l 2>/dev/null || true; printf '%s\\n' '@reboot /usr/bin/env python3 /opt/hosts-manager-agent/agent.py run') | sort -u | crontab -
  nohup /usr/bin/env python3 /opt/hosts-manager-agent/agent.py run >/var/log/hosts-manager-agent/agent.log 2>&1 &
fi
python3 - "$RESULT" "$ASSIGNED_HOSTNAME" <<'PY'
import json, sys
result = json.loads(sys.argv[1])
print(f"Assigned hostname: {{sys.argv[2]}}")
print(f"Host ID: {{result['id']}}")
print(f"Approval status: {{result['registration_status']}}")
print("Administrator approval and SSH fingerprint verification are required.")
PY
""", token_item

    @staticmethod
    def _windows_enrollment_script(token_item: dict[str, Any], token: str, endpoint: str) -> str:
        assigned = str(token_item["assigned_hostname"]).replace("'", "''")
        return f"""#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'Run this script as Administrator.' }}
if (-not '{endpoint}'.StartsWith('https://')) {{ throw 'HTTPS is required.' }}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$originalHostname = $env:COMPUTERNAME
$assignedHostname = '{assigned}'
$restartRequired = $false
if (${str(bool(token_item["apply_hostname"])).lower()} -and $assignedHostname) {{
  Rename-Computer -NewName $assignedHostname -Force
  $restartRequired = $true
}}
if (-not $assignedHostname) {{ $assignedHostname = $originalHostname }}
$address = $env:WEBNAS_ENROLL_ADDRESS
if (-not $address) {{
  $address = Get-NetIPConfiguration | Where-Object {{ $_.NetAdapter.Status -eq 'Up' }} |
    ForEach-Object {{ $_.IPv4Address.IPAddress }} |
    Where-Object {{ $_ -and $_ -notlike '127.*' -and $_ -notlike '169.254.*' }} |
    Select-Object -First 1
}}
if (-not $address) {{ throw 'A primary IPv4 address is required.' }}
$os = Get-CimInstance Win32_OperatingSystem
$system = Get-CimInstance Win32_ComputerSystemProduct
$body = @{{
  hostname = $assignedHostname; original_hostname = $originalHostname; fqdn = $assignedHostname
  address = $address; os = 'windows'; system_id = $system.UUID; system_version = $os.Version
  architecture = $env:PROCESSOR_ARCHITECTURE; powershell = $PSVersionTable.PSVersion.ToString(); python = ''
}} | ConvertTo-Json -Compress
$headers = @{{ Authorization = 'Bearer {token}' }}
$result = Invoke-RestMethod -Uri '{endpoint}/api/modules/hosts-manager/enroll' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
Write-Host "Assigned hostname: $assignedHostname"
Write-Host "Host ID: $($result.id)"
Write-Host "Approval status: $($result.registration_status)"
if ($restartRequired) {{ Write-Warning 'The computer name change will fully apply after restart; this script does not restart Windows.' }}
Write-Host 'Administrator approval and SSH fingerprint verification are required.'
"""

    @staticmethod
    def _agent_token_hash(token: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{token}".encode()).hexdigest()

    def register_agent(
        self,
        host_id: str,
        installation_id: str,
        agent_version: str,
        communication_port: int,
        report_interval_seconds: int,
        actor: str,
    ) -> dict[str, Any]:
        now, raw_token, salt = time.time(), secrets.token_urlsafe(48), secrets.token_hex(32)
        agent_id = stable_id()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            host = connection.execute("SELECT id FROM hosts WHERE id=?", (host_id,)).fetchone()
            if not host:
                raise KeyError("host not found")
            existing = connection.execute(
                "SELECT * FROM host_agents WHERE installation_id=?", (installation_id,)
            ).fetchone()
            if existing and str(existing["host_id"]) != host_id:
                raise PermissionError("agent installation identity is already paired with another host")
            if existing:
                agent_id = str(existing["id"])
                connection.execute(
                    "UPDATE host_identity_salts SET status='invalidated',invalidated_at=?,updated_by=? "
                    "WHERE agent_id=? AND status='valid'",
                    (now, actor, agent_id),
                )
                connection.execute(
                    "UPDATE host_agents SET token_hash=?,agent_version=?,status='online',communication_port=?,"
                    "report_interval_seconds=?,last_heartbeat_at=?,last_error='',auth_failures=0,updated_at=?,updated_by=? "
                    "WHERE id=?",
                    (
                        self._agent_token_hash(raw_token, salt), agent_version, communication_port,
                        report_interval_seconds, now, now, actor, agent_id,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO host_agents(
                        id,host_id,installation_id,token_hash,agent_version,status,communication_port,
                        report_interval_seconds,installed_at,last_heartbeat_at,created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,'online',?,?,?,?,?,?,?,?)""",
                    (
                        agent_id, host_id, installation_id, self._agent_token_hash(raw_token, salt), agent_version,
                        communication_port, report_interval_seconds, now, now, now, now, actor, actor,
                    ),
                )
            identity_id = stable_id()
            identity_hash = hashlib.sha256(f"{host_id}:{agent_id}:{salt}".encode()).hexdigest()
            connection.execute(
                """INSERT INTO host_identity_salts(
                    id,host_id,agent_id,salt,identity_hash,status,generated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,'valid',?,?,?)""",
                (identity_id, host_id, agent_id, salt, identity_hash, now, actor, actor),
            )
            connection.execute(
                "INSERT INTO agent_versions(id,host_id,agent_id,version,source,reported_at,reported_by) VALUES(?,?,?,?,?,?,?)",
                (stable_id(), host_id, agent_id, agent_version, "pairing", now, actor),
            )
        self._update_host(
            host_id, actor, connection_status="online", registration_status="registered",
            last_seen_at=now, last_error="",
        )
        self.operation(
            host_id, "agent.pair", actor, status="completed",
            details={"agent_id": agent_id, "installation_id": installation_id},
        )
        return {
            "agent_id": agent_id,
            "host_id": host_id,
            "token": raw_token,
            "identity_hash": identity_hash,
            "identity_generated_at": now,
        }

    def _verified_agent(self, agent_id: str, token: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            agent_row = connection.execute("SELECT * FROM host_agents WHERE id=?", (agent_id,)).fetchone()
            identity_row = connection.execute(
                "SELECT * FROM host_identity_salts WHERE agent_id=? AND status='valid' ORDER BY generated_at DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if not agent_row or not identity_row:
            return None
        if str(agent_row["status"]) == "authentication_required":
            return None
        expected = self._agent_token_hash(token, str(identity_row["salt"]))
        if not secrets.compare_digest(expected, str(agent_row["token_hash"])):
            failures = int(agent_row["auth_failures"]) + 1
            locked = failures >= int(self._settings_value("max_auth_failures", 5))
            now = time.time()
            with self.connect() as connection:
                connection.execute(
                    "UPDATE host_agents SET auth_failures=?,status=?,last_error=?,updated_at=? WHERE id=?",
                    (
                        failures,
                        "authentication_required" if locked else str(agent_row["status"]),
                        "Agent authentication failure limit exceeded" if locked else str(agent_row["last_error"]),
                        now,
                        agent_id,
                    ),
                )
                if locked:
                    connection.execute(
                        "UPDATE host_identity_salts SET status='invalidated',invalidated_at=?,updated_by=? "
                        "WHERE agent_id=? AND status='valid'",
                        (now, f"agent:{agent_id}", agent_id),
                    )
            if locked:
                self._update_host(
                    str(agent_row["host_id"]),
                    f"agent:{agent_id}",
                    connection_status="offline",
                    registration_status="authentication_required",
                    last_error="Agent authentication failure limit exceeded",
                )
                self.operation(
                    str(agent_row["host_id"]),
                    "agent.authentication.lock",
                    f"agent:{agent_id}",
                    status="completed",
                    details={"agent_id": agent_id, "failures": failures},
                )
            return None
        return self._decode(agent_row)

    def agent_heartbeat(self, agent_id: str, token: str, heartbeat: dict[str, Any]) -> dict[str, Any] | None:
        agent = self._verified_agent(agent_id, token)
        if not agent:
            return None
        now = time.time()
        with self.connect() as connection:
            connection.execute(
                "UPDATE host_agents SET agent_version=?,status=?,last_heartbeat_at=?,last_error=?,auth_failures=0,"
                "updated_at=?,updated_by=? WHERE id=?",
                (
                    heartbeat["agent_version"], heartbeat["status"], now, heartbeat.get("error", ""),
                    now, f"agent:{agent_id}", agent_id,
                ),
            )
            if str(agent.get("agent_version") or "") != str(heartbeat["agent_version"]):
                connection.execute(
                    "INSERT INTO agent_versions(id,host_id,agent_id,version,source,reported_at,reported_by) VALUES(?,?,?,?,?,?,?)",
                    (
                        stable_id(),
                        agent["host_id"],
                        agent_id,
                        heartbeat["agent_version"],
                        "heartbeat",
                        now,
                        f"agent:{agent_id}",
                    ),
                )
        self._update_host(
            str(agent["host_id"]), f"agent:{agent_id}", connection_status=heartbeat["status"],
            last_seen_at=now, last_error=heartbeat.get("error", ""),
        )
        if str(agent.get("agent_version") or "") != str(heartbeat["agent_version"]):
            self.operation(
                str(agent["host_id"]),
                "agent.update",
                f"agent:{agent_id}",
                status="completed",
                stage="reported",
                progress=100,
                details={
                    "previous_version": str(agent.get("agent_version") or ""),
                    "agent_version": str(heartbeat["agent_version"]),
                },
            )
        agent_source = Path(__file__).with_name("agent.py")
        source_checksum = hashlib.sha256(agent_source.read_bytes()).hexdigest()
        return {
            "ok": True,
            "server_time": now,
            "next_heartbeat_seconds": int(self._settings_value("heartbeat_interval_seconds", 30)),
            "enforce_tls": bool(self._settings_value("agent_enforce_tls", True)),
            "agent_update": {
                "enabled": bool(self._settings_value("agent_auto_update", False)),
                "minimum_version": str(self._settings_value("agent_min_version", "1.0.0")),
                "channel": str(self._settings_value("agent_update_channel", "stable")),
                "url": str(self._settings_value("agent_repository_url", "")),
                "sha256": source_checksum,
                "max_size": 2 * 1024 * 1024,
            },
        }

    def save_agent_report(self, agent_id: str, token: str, report: dict[str, Any]) -> dict[str, Any] | None:
        agent = self._verified_agent(agent_id, token)
        if not agent:
            return None
        now = time.time()
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO host_reports(id,host_id,agent_id,report_json,checksum,created_at) VALUES(?,?,?,?,?,?)",
                (stable_id(), agent["host_id"], agent_id, encoded, checksum, now),
            )
            connection.execute(
                "UPDATE host_agents SET status='online',last_report_at=?,last_heartbeat_at=?,last_error='',"
                "auth_failures=0,updated_at=?,updated_by=? WHERE id=?",
                (now, now, now, f"agent:{agent_id}", agent_id),
            )
        self._update_host(
            str(agent["host_id"]), f"agent:{agent_id}", connection_status="online",
            last_seen_at=now, last_facts_at=now, last_error="",
        )
        return {"ok": True, "checksum": checksum, "received_at": now}

    def rotate_agent_identity(self, host_id: str, actor: str) -> dict[str, Any]:
        agents = self._list("host_agents", where="host_id=?", values=(host_id,), order="updated_at DESC", limit=1)
        if not agents:
            raise KeyError("agent not found")
        agent = agents[0]
        return self.register_agent(
            host_id, str(agent["installation_id"]), str(agent.get("agent_version") or "1.0.0"),
            int(agent["communication_port"]), int(agent["report_interval_seconds"]), actor,
        )

    def invalidate_agent_identity(self, host_id: str, actor: str) -> bool:
        now = time.time()
        with self.connect() as connection:
            agent = connection.execute("SELECT id FROM host_agents WHERE host_id=?", (host_id,)).fetchone()
            if not agent:
                return False
            connection.execute(
                "UPDATE host_identity_salts SET status='invalidated',invalidated_at=?,updated_by=? "
                "WHERE agent_id=? AND status='valid'",
                (now, actor, agent["id"]),
            )
            connection.execute(
                "UPDATE host_agents SET status='authentication_required',token_hash='',updated_at=?,updated_by=? WHERE id=?",
                (now, actor, agent["id"]),
            )
        self._update_host(
            host_id, actor, connection_status="offline", registration_status="authentication_required",
            last_error="Agent identity was invalidated; pairing is required",
        )
        self.operation(host_id, "agent.identity.invalidate", actor, status="completed")
        return True

    def agent_history(self, host_id: str) -> dict[str, Any]:
        identities = self._list(
            "host_identity_salts", where="host_id=?", values=(host_id,), order="generated_at DESC", limit=100
        )
        reports = self._list("host_reports", where="host_id=?", values=(host_id,), order="created_at DESC", limit=25)
        versions = self._list("agent_versions", where="host_id=?", values=(host_id,), order="reported_at DESC", limit=100)
        return {
            "identities": [{key: value for key, value in item.items() if key != "salt"} for item in identities],
            "reports": [
                {"id": item["id"], "checksum": item["checksum"], "created_at": item["created_at"]}
                for item in reports
            ],
            "versions": versions,
            "operations": self.operations(host_id, limit=100),
        }

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

    def update_operation(
        self,
        operation_id: str,
        actor: str,
        *,
        status: str,
        stage: str,
        progress: int,
        details: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        item = self._get("operations", operation_id)
        if not item:
            raise KeyError("operation not found")
        safe_details = redact(details) if details is not None else item.get("details", {})
        with self.connect() as connection:
            connection.execute(
                "UPDATE operations SET status=?,stage=?,progress=?,details_json=?,error=?,updated_at=?,updated_by=? WHERE id=?",
                (
                    status,
                    stage,
                    max(0, min(100, progress)),
                    json.dumps(safe_details),
                    error[:2000],
                    time.time(),
                    actor,
                    operation_id,
                ),
            )
        return self._get("operations", operation_id) or {}

    def operations(self, host_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        return self._list("operations", where="host_id=?" if host_id else "", values=(host_id,) if host_id else (), limit=limit)

    def dashboard(self) -> dict[str, Any]:
        hosts = self.list_hosts()
        now = time.time()
        environments: dict[str, int] = {}
        updates = security_updates = without_agent = stale = low_disk = high_cpu = high_memory = errors = 0
        for item in hosts:
            environment = str(item.get("environment") or "unassigned")
            environments[environment] = environments.get(environment, 0) + 1
            updates += int(item.get("available_updates") or 0)
            security_updates += int(item.get("security_updates") or 0)
            without_agent += item.get("agent") is None
            agent = item.get("agent") or {}
            report = item.get("latest_report") or {}
            system = report.get("system", {}) if isinstance(report, dict) else {}
            hardware = report.get("hardware", {}) if isinstance(report, dict) else {}
            last_report = float(agent.get("last_report_at") or 0)
            interval = int(agent.get("report_interval_seconds") or 300)
            stale += bool(agent and (not last_report or now - last_report > max(interval * 3, 900)))
            errors += bool(item.get("last_error") or item.get("agent_status") == "error")
            high_cpu += float(system.get("cpu_percent") or 0) >= 90
            high_memory += float(system.get("memory_percent") or 0) >= 90
            filesystems = hardware.get("filesystems", []) if isinstance(hardware, dict) else []
            low_disk += any(float(fs.get("free_percent") or 100) < 10 for fs in filesystems if isinstance(fs, dict))
        operations = self.operations(limit=100)
        return {
            "generated_at": now,
            "total": len(hosts), "online": sum(item["connection_status"] == "online" for item in hosts),
            "offline": sum(item["connection_status"] == "offline" for item in hosts),
            "errors": errors,
            "unverified": sum(item["fingerprint_status"] in {"unverified", "scanned"} for item in hosts),
            "fingerprint_errors": sum(item["fingerprint_status"] == "changed" for item in hosts),
            "pending_approval": sum(not item["approved"] for item in hosts),
            "pending_registration": sum(item.get("status") in {"pending", "installing"} for item in hosts),
            "ansible_available": sum(any(c["id"].startswith("ansible.") for c in self.capabilities(item["id"])) for item in hosts),
            "power_managed": sum(bool(item.get("power_profile_id")) for item in hosts),
            "available_updates": updates,
            "security_updates": security_updates,
            "without_agent": without_agent,
            "stale_reports": stale,
            "low_disk": low_disk,
            "high_cpu": high_cpu,
            "high_memory": high_memory,
            "by_environment": environments,
            "recent_hosts": sorted(hosts, key=lambda item: item.get("created_at", 0), reverse=True)[:8],
            "recent_connections": sorted(
                [item for item in hosts if (item.get("agent") or {}).get("last_heartbeat_at")],
                key=lambda item: (item.get("agent") or {}).get("last_heartbeat_at", 0),
                reverse=True,
            )[:8],
            "onboarding_history": [item for item in operations if item["capability_id"] in {"host.create", "agent.pair"}][:8],
            "hostname_changes": [item for item in operations if item["capability_id"] == "host.hostname.change"][:8],
            "administrative_operations": operations[:10],
            "recent_operations": operations[:10],
            "recent_errors": [item for item in hosts if item.get("last_error")][:10],
        }


@lru_cache
def registry() -> HostRegistryService:
    return HostRegistryService()
