from __future__ import annotations

import fnmatch
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
from typing import Any

from ...config import get_config
from .models import CredentialInput, EnrollmentTokenInput, GroupInput, HostInput, PlaybookInput, ProjectInput, ScheduleInput, TemplateInput
from .security import CredentialCipher, redact


SCHEMA_VERSION = 2
JSON_COLUMNS = {
    "tags_json": "tags",
    "variables_json": "variables",
    "host_ids_json": "host_ids",
    "group_ids_json": "group_ids",
    "credential_ids_json": "credential_ids",
    "skip_tags_json": "skip_tags",
    "warnings_json": "warnings",
    "summary_json": "summary",
    "details_json": "details",
    "facts_json": "facts",
    "config_json": "config",
}


def stable_id() -> str:
    return secrets.token_hex(16)


class ClosingConnection(sqlite3.Connection):
    """SQLite transaction context that also releases the database handle."""

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> bool | None:
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


class AnsibleRepository:
    """Private, versioned module database. Credential plaintext never enters it."""

    def __init__(self, path: Path | None = None, key_path: Path | None = None) -> None:
        self.centralized_hosts = path is None
        root = (path.parent if path else Path(get_config().paths.data_dir) / "ansible-controller").resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        self.root = root
        self.path = path or root / "controller.sqlite3"
        self.cipher = CredentialCipher(key_path or root.parent / "secrets" / "ansible-controller.key")
        self._lock = threading.RLock()
        self._initialize()

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
                CREATE TABLE IF NOT EXISTS hosts(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, address TEXT NOT NULL, port INTEGER NOT NULL DEFAULT 22,
                    ssh_user TEXT NOT NULL, credential_id TEXT, python_interpreter TEXT NOT NULL, connection_type TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    variables_json TEXT NOT NULL DEFAULT '{}', fingerprint_status TEXT NOT NULL DEFAULT 'unverified',
                    last_test_at REAL, last_facts_at REAL, last_error TEXT NOT NULL DEFAULT '', last_execution_id TEXT,
                    managed_user_created INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(credential_id) REFERENCES credentials(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_hosts_address ON hosts(address,port);
                CREATE INDEX IF NOT EXISTS idx_ansible_hosts_active ON hosts(active,name);
                CREATE TABLE IF NOT EXISTS inventory_groups(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', parent_id TEXT,
                    variables_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(parent_id) REFERENCES inventory_groups(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_groups_parent ON inventory_groups(parent_id,active);
                CREATE TABLE IF NOT EXISTS host_group_memberships(
                    host_id TEXT NOT NULL, group_id TEXT NOT NULL, created_at REAL NOT NULL, created_by TEXT NOT NULL,
                    PRIMARY KEY(host_id,group_id), FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE,
                    FOREIGN KEY(group_id) REFERENCES inventory_groups(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS host_variables(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, name TEXT NOT NULL, value_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, UNIQUE(host_id,name),
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS group_variables(
                    id TEXT PRIMARY KEY, group_id TEXT NOT NULL, name TEXT NOT NULL, value_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, UNIQUE(group_id,name),
                    FOREIGN KEY(group_id) REFERENCES inventory_groups(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS credentials(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, type TEXT NOT NULL, username TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '', encrypted_secret TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_credentials_type ON credentials(type,active);
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, source_type TEXT NOT NULL, repository_url TEXT NOT NULL DEFAULT '',
                    revision TEXT NOT NULL DEFAULT 'main', credential_id TEXT, sync_before_run INTEGER NOT NULL DEFAULT 0,
                    allow_submodules INTEGER NOT NULL DEFAULT 0, last_commit TEXT NOT NULL DEFAULT '', last_sync_at REAL,
                    last_sync_status TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(credential_id) REFERENCES credentials(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS project_sync_history(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, status TEXT NOT NULL, commit_hash TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, created_by TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS playbooks(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, filename TEXT NOT NULL, content TEXT NOT NULL,
                    current_version INTEGER NOT NULL DEFAULT 1, risk_status TEXT NOT NULL DEFAULT 'unknown', warnings_json TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, UNIQUE(project_id,name),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS playbook_versions(
                    id TEXT PRIMARY KEY, playbook_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
                    checksum TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, created_by TEXT NOT NULL,
                    UNIQUE(playbook_id,version), FOREIGN KEY(playbook_id) REFERENCES playbooks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS job_templates(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', project_id TEXT NOT NULL,
                    playbook_id TEXT NOT NULL, host_ids_json TEXT NOT NULL DEFAULT '[]', group_ids_json TEXT NOT NULL DEFAULT '[]',
                    ssh_credential_id TEXT, become_credential_id TEXT, vault_credential_id TEXT, limit_pattern TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]', skip_tags_json TEXT NOT NULL DEFAULT '[]', check_mode INTEGER NOT NULL DEFAULT 0,
                    diff_mode INTEGER NOT NULL DEFAULT 0, verbosity INTEGER NOT NULL DEFAULT 0, forks INTEGER NOT NULL DEFAULT 10,
                    timeout_seconds INTEGER NOT NULL DEFAULT 3600, extra_vars TEXT NOT NULL DEFAULT '{}', concurrency_policy TEXT NOT NULL DEFAULT 'same_hosts',
                    sync_before_run INTEGER NOT NULL DEFAULT 0, confirmation_required INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(playbook_id) REFERENCES playbooks(id)
                );
                CREATE TABLE IF NOT EXISTS schedules(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, template_id TEXT NOT NULL, kind TEXT NOT NULL, expression TEXT NOT NULL,
                    timezone TEXT NOT NULL, missed_policy TEXT NOT NULL, next_run_at REAL, last_run_at REAL, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(template_id) REFERENCES job_templates(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_schedules_due ON schedules(active,next_run_at);
                CREATE TABLE IF NOT EXISTS executions(
                    id TEXT PRIMARY KEY, package_job_id TEXT, template_id TEXT, retry_of TEXT, requested_by TEXT NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, inventory_snapshot TEXT NOT NULL DEFAULT '', playbook_snapshot TEXT NOT NULL DEFAULT '',
                    project_commit TEXT NOT NULL DEFAULT '', credential_ids_json TEXT NOT NULL DEFAULT '[]', host_ids_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]', summary_json TEXT NOT NULL DEFAULT '{}', stdout TEXT NOT NULL DEFAULT '', stderr TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER, started_at REAL, finished_at REAL, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
                    FOREIGN KEY(template_id) REFERENCES job_templates(id) ON DELETE SET NULL,
                    FOREIGN KEY(retry_of) REFERENCES executions(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_executions_status ON executions(status,created_at DESC);
                CREATE TABLE IF NOT EXISTS host_results(
                    id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, host_id TEXT, host_name TEXT NOT NULL, status TEXT NOT NULL,
                    ok_count INTEGER NOT NULL DEFAULT 0, changed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
                    unreachable_count INTEGER NOT NULL DEFAULT 0, skipped_count INTEGER NOT NULL DEFAULT 0, rescued_count INTEGER NOT NULL DEFAULT 0,
                    ignored_count INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(execution_id,host_name), FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS saved_facts(
                    id TEXT PRIMARY KEY, host_id TEXT NOT NULL, facts_json TEXT NOT NULL, checksum TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_facts_host_time ON saved_facts(host_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS network_scans(
                    id TEXT PRIMARY KEY, request_json TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    discovered INTEGER NOT NULL DEFAULT 0, package_job_id TEXT, error TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scan_hosts(
                    id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, address TEXT NOT NULL, hostname TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL,
                    latency_ms REAL, ssh_status TEXT NOT NULL, imported_host_id TEXT, selected INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, UNIQUE(scan_id,address,port),
                    FOREIGN KEY(scan_id) REFERENCES network_scans(id) ON DELETE CASCADE,
                    FOREIGN KEY(imported_host_id) REFERENCES hosts(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS controller_audit_events(
                    id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, actor TEXT NOT NULL, object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL, action TEXT NOT NULL, result TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_audit_time ON controller_audit_events(created_at DESC);
                CREATE TABLE IF NOT EXISTS known_host_keys(
                    id TEXT PRIMARY KEY, host_id TEXT, address TEXT NOT NULL, port INTEGER NOT NULL, key_type TEXT NOT NULL,
                    public_key TEXT NOT NULL, fingerprint TEXT NOT NULL, previous_fingerprint TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL, UNIQUE(address,port,key_type),
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS host_locks(
                    host_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, acquired_at REAL NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE, FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS controller_settings(
                    key TEXT PRIMARY KEY, config_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS enrollment_tokens(
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, hostname_pattern TEXT NOT NULL,
                    ssh_user TEXT NOT NULL, port INTEGER NOT NULL, credential_id TEXT, environment TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
                    expires_at REAL NOT NULL, used_at REAL, used_hostname TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ansible_enrollment_tokens_hash
                ON enrollment_tokens(token_hash,active,expires_at);
                """
            )
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (?,?)", (SCHEMA_VERSION, now))
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for column, target in JSON_COLUMNS.items():
            if column in result:
                try:
                    result[target] = json.loads(result.pop(column) or "{}")
                except (TypeError, ValueError):
                    result[target] = [] if column.endswith("ids_json") or column in {"tags_json", "skip_tags_json", "warnings_json"} else {}
        for key in ("active", "managed_user_created", "sync_before_run", "allow_submodules", "check_mode", "diff_mode", "confirmation_required"):
            if key in result:
                result[key] = bool(result[key])
        return result

    def _list(self, table: str, *, where: str = "", values: tuple[Any, ...] = (), order: str = "updated_at DESC", limit: int = 500) -> list[dict[str, Any]]:
        if self.centralized_hosts and table == "host_group_memberships":
            from ..hosts_manager.service import registry
            return registry()._list("memberships", where=where, values=values, order=order, limit=limit)
        if self.centralized_hosts and table == "saved_facts":
            from ..hosts_manager.service import registry
            return registry()._list("facts", where=where, values=values, order=order, limit=limit)
        allowed = {"hosts", "inventory_groups", "credentials", "projects", "playbooks", "job_templates", "schedules", "executions", "network_scans", "scan_hosts", "controller_audit_events", "known_host_keys", "host_results", "saved_facts", "host_group_memberships", "playbook_versions"}
        if table not in allowed:
            raise ValueError("unsupported repository table")
        clause = f" WHERE {where}" if where else ""
        with self._lock, self.connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table}{clause} ORDER BY {order} LIMIT ?", (*values, min(max(limit, 1), 5000))).fetchall()
        return [self._decode(row) or {} for row in rows]

    def _get(self, table: str, object_id: str) -> dict[str, Any] | None:
        values = self._list(table, where="id=?", values=(object_id,), limit=1)
        return values[0] if values else None

    def list_hosts(self, *, active_only: bool = False, limit: int = 5000) -> list[dict[str, Any]]:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            return registry().list_hosts(active_only=active_only, limit=limit)
        return self._list("hosts", where="active=1" if active_only else "", order="name", limit=limit)

    def host(self, host_id: str) -> dict[str, Any] | None:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            return registry().host(host_id)
        host = self._get("hosts", host_id)
        if host:
            host["groups"] = self._memberships_for_host(host_id)
            facts = self._list("saved_facts", where="host_id=?", values=(host_id,), limit=1)
            host["facts"] = facts[0].get("facts", {}) if facts else {}
        return host

    def save_host(self, payload: HostInput, actor: str, host_id: str | None = None) -> dict[str, Any]:
        if self.centralized_hosts:
            from ..hosts_manager.models import HostInput as CentralHostInput
            from ..hosts_manager.service import registry
            value = payload.model_dump(mode="json")
            return registry().save_host(CentralHostInput(**value, approved=True), actor, host_id, source="ansible-controller")
        now, object_id = time.time(), host_id or stable_id()
        values = payload.model_dump(mode="json")
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT id,created_at,created_by FROM hosts WHERE id=?", (object_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO hosts(id,name,address,port,ssh_user,credential_id,python_interpreter,connection_type,environment,location,tags_json,variables_json,active,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,address=excluded.address,port=excluded.port,ssh_user=excluded.ssh_user,credential_id=excluded.credential_id,python_interpreter=excluded.python_interpreter,connection_type=excluded.connection_type,environment=excluded.environment,location=excluded.location,tags_json=excluded.tags_json,variables_json=excluded.variables_json,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, values["name"], values["address"], values["port"], values["ssh_user"], values["credential_id"], values["python_interpreter"], values["connection_type"], values["environment"], values["location"], json.dumps(values["tags"]), json.dumps(values["variables"]), int(values["active"]), created_at, now, created_by, actor),
            )
        self.audit(actor, "host", object_id, "create" if not host_id else "update")
        return self.host(object_id) or {}

    def create_enrollment_token(self, payload: EnrollmentTokenInput, actor: str) -> dict[str, Any]:
        if self.centralized_hosts:
            from ..hosts_manager.models import EnrollmentTokenInput as CentralEnrollmentTokenInput
            from ..hosts_manager.service import registry
            return registry().create_enrollment_token(CentralEnrollmentTokenInput(**payload.model_dump(mode="json")), actor)
        now, token_id, token = time.time(), stable_id(), secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        values = payload.model_dump(mode="json")
        expires_at = now + values.pop("expires_minutes") * 60
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM enrollment_tokens WHERE expires_at<? OR used_at IS NOT NULL", (now - 86400,))
            connection.execute(
                """INSERT INTO enrollment_tokens(id,token_hash,hostname_pattern,ssh_user,port,credential_id,environment,location,tags_json,expires_at,used_at,used_hostname,active,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,NULL,'',1,?,?,?,?)""",
                (token_id, token_hash, values["hostname_pattern"], values["ssh_user"], values["port"], values["credential_id"], values["environment"], values["location"], json.dumps(values["tags"]), expires_at, now, now, actor, actor),
            )
        self.audit(actor, "enrollment_token", token_id, "create", {"hostname_pattern": values["hostname_pattern"], "expires_at": expires_at})
        return {"id": token_id, "token": token, "hostname_pattern": values["hostname_pattern"], "expires_at": expires_at}

    def claim_enrollment_token(self, token: str, hostname: str) -> dict[str, Any] | None:
        if self.centralized_hosts:
            # The public enrollment endpoint is owned by Hosts Manager. This
            # compatibility method deliberately cannot bypass its strict claim model.
            return None
        now = time.time()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock, self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM enrollment_tokens WHERE token_hash=? AND active=1 AND used_at IS NULL AND expires_at>=?",
                (token_hash, now),
            ).fetchone()
            if not row or not fnmatch.fnmatchcase(hostname.casefold(), str(row["hostname_pattern"]).casefold()):
                return None
            changed = connection.execute(
                "UPDATE enrollment_tokens SET used_at=?,used_hostname=?,active=0,updated_at=?,updated_by=? WHERE id=? AND used_at IS NULL AND active=1",
                (now, hostname, now, f"self-enrollment:{hostname}", row["id"]),
            ).rowcount
            if not changed:
                return None
            result = dict(row)
            result["tags"] = json.loads(result.pop("tags_json") or "[]")
            return result

    def delete_host(self, host_id: str, actor: str) -> bool:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            return registry().delete_host(host_id, actor)
        with self._lock, self.connect() as connection:
            changed = connection.execute("UPDATE hosts SET active=0,updated_at=?,updated_by=? WHERE id=? AND active=1", (time.time(), actor, host_id)).rowcount
        if changed:
            self.audit(actor, "host", host_id, "delete")
        return bool(changed)

    def list_groups(self) -> list[dict[str, Any]]:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            return registry().list_groups()
        groups = self._list("inventory_groups", order="name", limit=5000)
        with self._lock, self.connect() as connection:
            memberships = connection.execute("SELECT host_id,group_id,created_at,created_by FROM host_group_memberships").fetchall()
        mapping: dict[str, list[str]] = {}
        for item in memberships:
            mapping.setdefault(str(item["group_id"]), []).append(str(item["host_id"]))
        for group in groups:
            group["host_ids"] = mapping.get(group["id"], [])
        return groups

    def _memberships_for_host(self, host_id: str) -> list[dict[str, Any]]:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            item = registry().host(host_id)
            return list(item.get("groups", [])) if item else []
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT g.id,g.name FROM inventory_groups g JOIN host_group_memberships m ON m.group_id=g.id WHERE m.host_id=? AND g.active=1 ORDER BY g.name", (host_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_group(self, payload: GroupInput, actor: str, group_id: str | None = None) -> dict[str, Any]:
        if self.centralized_hosts:
            from ..hosts_manager.models import GroupInput as CentralGroupInput
            from ..hosts_manager.service import registry
            return registry().save_group(CentralGroupInput(**payload.model_dump(mode="json")), actor, group_id)
        now, object_id = time.time(), group_id or stable_id()
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at,created_by FROM inventory_groups WHERE id=?", (object_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO inventory_groups(id,name,description,parent_id,variables_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,parent_id=excluded.parent_id,variables_json=excluded.variables_json,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, payload.name, payload.description, payload.parent_id, json.dumps(payload.variables), int(payload.active), created_at, now, created_by, actor),
            )
            connection.execute("DELETE FROM host_group_memberships WHERE group_id=?", (object_id,))
            connection.executemany("INSERT INTO host_group_memberships(host_id,group_id,created_at,created_by) VALUES(?,?,?,?)", [(host_id, object_id, now, actor) for host_id in payload.host_ids])
        self.audit(actor, "group", object_id, "create" if not group_id else "update")
        return next(item for item in self.list_groups() if item["id"] == object_id)

    def credentials(self) -> list[dict[str, Any]]:
        local = [self._credential_metadata(item) for item in self._list("credentials", order="name", limit=5000)]
        if not self.centralized_hosts:
            return local
        from ..hosts_manager.service import registry
        central = registry().credentials()
        return list({str(item["id"]): item for item in [*local, *central]}.values())

    @staticmethod
    def _credential_metadata(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "encrypted_secret"} | {"secret_configured": bool(item.get("encrypted_secret"))}

    def save_credential(self, payload: CredentialInput, actor: str, credential_id: str | None = None) -> dict[str, Any]:
        if self.centralized_hosts and payload.type.value in {"ssh_private_key", "ssh_password", "become_password"}:
            from ..hosts_manager.models import CredentialInput as CentralCredentialInput
            from ..hosts_manager.service import registry
            return registry().save_credential(CentralCredentialInput(**payload.model_dump(mode="json")), actor, credential_id)
        now, object_id = time.time(), credential_id or stable_id()
        envelope = self.cipher.encrypt(json.dumps({"secret": payload.secret, "passphrase": payload.passphrase}, ensure_ascii=False), associated_data=object_id)
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at,created_by FROM credentials WHERE id=?", (object_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO credentials(id,name,type,username,description,encrypted_secret,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,type=excluded.type,username=excluded.username,description=excluded.description,encrypted_secret=excluded.encrypted_secret,active=1,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, payload.name, payload.type.value, payload.username, payload.description, envelope, created_at, now, created_by, actor),
            )
        self.audit(actor, "credential", object_id, "create" if not credential_id else "update", {"type": payload.type.value})
        item = self._get("credentials", object_id)
        return self._credential_metadata(item or {})

    def credential_secret(self, credential_id: str) -> dict[str, str]:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            try:
                return registry().verified_credential(credential_id, module_id="ansible-controller", purpose="automation")
            except KeyError:
                pass
        item = self._get("credentials", credential_id)
        if not item or not item.get("active"):
            raise KeyError("credential not found")
        value = json.loads(self.cipher.decrypt(str(item["encrypted_secret"]), associated_data=credential_id))
        return {"secret": str(value.get("secret") or ""), "passphrase": str(value.get("passphrase") or ""), "username": str(item.get("username") or ""), "type": str(item.get("type") or "")}

    def delete_credential(self, credential_id: str, actor: str) -> bool:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            if registry()._get("credentials", credential_id):
                return registry().delete_credential(credential_id)
        with self._lock, self.connect() as connection:
            changed = connection.execute("UPDATE credentials SET active=0,encrypted_secret='',updated_at=?,updated_by=? WHERE id=? AND active=1", (time.time(), actor, credential_id)).rowcount
        if changed:
            self.audit(actor, "credential", credential_id, "delete")
        return bool(changed)

    def projects(self) -> list[dict[str, Any]]:
        return self._list("projects", order="name", limit=5000)

    def save_project(self, payload: ProjectInput, actor: str, project_id: str | None = None) -> dict[str, Any]:
        now, object_id = time.time(), project_id or stable_id()
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at,created_by FROM projects WHERE id=?", (object_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO projects(id,name,source_type,repository_url,revision,credential_id,sync_before_run,allow_submodules,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,source_type=excluded.source_type,repository_url=excluded.repository_url,revision=excluded.revision,credential_id=excluded.credential_id,sync_before_run=excluded.sync_before_run,allow_submodules=excluded.allow_submodules,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, payload.name, payload.source_type, str(payload.repository_url or ""), payload.revision, payload.credential_id, int(payload.sync_before_run), int(payload.allow_submodules), int(payload.active), created_at, now, created_by, actor),
            )
        self.audit(actor, "project", object_id, "create" if not project_id else "update")
        return self._get("projects", object_id) or {}

    def playbooks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._list("playbooks", where="project_id=? AND active=1" if project_id else "active=1", values=(project_id,) if project_id else (), order="name", limit=5000)

    def save_playbook(self, payload: PlaybookInput, actor: str, analysis: dict[str, Any], playbook_id: str | None = None) -> dict[str, Any]:
        import hashlib

        now, object_id = time.time(), playbook_id or stable_id()
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT current_version,created_at,created_by FROM playbooks WHERE id=?", (object_id,)).fetchone()
            version = int(existing["current_version"]) + 1 if existing else 1
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO playbooks(id,project_id,name,filename,content,current_version,risk_status,warnings_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,name=excluded.name,filename=excluded.filename,content=excluded.content,current_version=excluded.current_version,risk_status=excluded.risk_status,warnings_json=excluded.warnings_json,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, payload.project_id, payload.name, payload.filename, payload.content, version, "blocked" if analysis.get("blocked") else "warning" if analysis.get("warnings") else "safe", json.dumps(analysis.get("warnings", [])), int(payload.active), created_at, now, created_by, actor),
            )
            connection.execute("INSERT INTO playbook_versions(id,playbook_id,version,content,checksum,comment,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)", (stable_id(), object_id, version, payload.content, hashlib.sha256(payload.content.encode()).hexdigest(), payload.comment, now, actor))
        self.audit(actor, "playbook", object_id, "create" if not playbook_id else "update", {"version": version})
        return self._get("playbooks", object_id) or {}

    def playbook_versions(self, playbook_id: str) -> list[dict[str, Any]]:
        return self._list("playbook_versions", where="playbook_id=?", values=(playbook_id,), order="version DESC", limit=1000)

    def delete_playbook(self, playbook_id: str, actor: str) -> bool:
        with self._lock, self.connect() as connection:
            changed = connection.execute("DELETE FROM playbooks WHERE id=? AND active=1", (playbook_id,)).rowcount
        if changed:
            self.audit(actor, "playbook", playbook_id, "delete")
        return bool(changed)

    def templates(self) -> list[dict[str, Any]]:
        return self._list("job_templates", order="name", limit=5000)

    def save_template(self, payload: TemplateInput, actor: str, template_id: str | None = None) -> dict[str, Any]:
        now, object_id = time.time(), template_id or stable_id()
        value = payload.model_dump(mode="json")
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at,created_by FROM job_templates WHERE id=?", (object_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO job_templates(id,name,description,project_id,playbook_id,host_ids_json,group_ids_json,ssh_credential_id,become_credential_id,vault_credential_id,limit_pattern,tags_json,skip_tags_json,check_mode,diff_mode,verbosity,forks,timeout_seconds,extra_vars,concurrency_policy,sync_before_run,confirmation_required,active,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,project_id=excluded.project_id,playbook_id=excluded.playbook_id,host_ids_json=excluded.host_ids_json,group_ids_json=excluded.group_ids_json,ssh_credential_id=excluded.ssh_credential_id,become_credential_id=excluded.become_credential_id,vault_credential_id=excluded.vault_credential_id,limit_pattern=excluded.limit_pattern,tags_json=excluded.tags_json,skip_tags_json=excluded.skip_tags_json,check_mode=excluded.check_mode,diff_mode=excluded.diff_mode,verbosity=excluded.verbosity,forks=excluded.forks,timeout_seconds=excluded.timeout_seconds,extra_vars=excluded.extra_vars,concurrency_policy=excluded.concurrency_policy,sync_before_run=excluded.sync_before_run,confirmation_required=excluded.confirmation_required,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, value["name"], value["description"], value["project_id"], value["playbook_id"], json.dumps(value["host_ids"]), json.dumps(value["group_ids"]), value["ssh_credential_id"], value["become_credential_id"], value["vault_credential_id"], value["limit"], json.dumps(value["tags"]), json.dumps(value["skip_tags"]), int(value["check_mode"]), int(value["diff_mode"]), value["verbosity"], value["forks"], value["timeout_seconds"], value["extra_vars"], value["concurrency_policy"], int(value["sync_before_run"]), int(value["confirmation_required"]), int(value["active"]), created_at, now, created_by, actor),
            )
        self.audit(actor, "template", object_id, "create" if not template_id else "update")
        return self._get("job_templates", object_id) or {}

    def schedules(self) -> list[dict[str, Any]]:
        return self._list("schedules", order="next_run_at", limit=5000)

    def save_schedule(self, payload: ScheduleInput, actor: str, schedule_id: str | None = None, next_run_at: float | None = None) -> dict[str, Any]:
        now, object_id = time.time(), schedule_id or stable_id()
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT created_at,created_by FROM schedules WHERE id=?", (object_id,)).fetchone()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO schedules(id,name,template_id,kind,expression,timezone,missed_policy,next_run_at,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,template_id=excluded.template_id,kind=excluded.kind,expression=excluded.expression,timezone=excluded.timezone,missed_policy=excluded.missed_policy,next_run_at=excluded.next_run_at,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, payload.name, payload.template_id, payload.kind.value, payload.expression, payload.timezone, payload.missed_policy, next_run_at, int(payload.active), created_at, now, created_by, actor),
            )
        self.audit(actor, "schedule", object_id, "create" if not schedule_id else "update")
        return self._get("schedules", object_id) or {}

    def create_scan(self, request: dict[str, Any], actor: str) -> dict[str, Any]:
        object_id, now = stable_id(), time.time()
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO network_scans(id,request_json,status,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,'queued',1,?,?,?,?)", (object_id, json.dumps(request), now, now, actor, actor))
        self.audit(actor, "scan", object_id, "start", {"port": request.get("port"), "method": request.get("method")})
        return self.scan(object_id) or {}

    def scan(self, scan_id: str) -> dict[str, Any] | None:
        item = self._get("network_scans", scan_id)
        if item:
            item["request"] = json.loads(item.pop("request_json", "{}"))
            item["hosts"] = self._list("scan_hosts", where="scan_id=?", values=(scan_id,), order="address", limit=5000)
        return item

    def scans(self) -> list[dict[str, Any]]:
        result = self._list("network_scans", limit=500)
        for item in result:
            item["request"] = json.loads(item.pop("request_json", "{}"))
        return result

    def set_scan_job(self, scan_id: str, job_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("UPDATE network_scans SET package_job_id=?,status='running',updated_at=? WHERE id=?", (job_id, time.time(), scan_id))

    def complete_scan(self, scan_id: str, actor: str, hosts: list[dict[str, Any]], error: str = "") -> None:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM scan_hosts WHERE scan_id=?", (scan_id,))
            for host in hosts:
                connection.execute("INSERT INTO scan_hosts(id,scan_id,address,hostname,port,latency_ms,ssh_status,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,1,?,?,?,?)", (stable_id(), scan_id, host["address"], host.get("hostname", ""), host["port"], host.get("latency_ms"), host.get("ssh_status", "unknown"), now, now, actor, actor))
            connection.execute("UPDATE network_scans SET status=?,progress=100,discovered=?,error=?,updated_at=?,updated_by=? WHERE id=?", ("failed" if error else "completed", len(hosts), str(redact(error))[:2000], now, actor, scan_id))
        self.audit(actor, "scan", scan_id, "finish", {"discovered": len(hosts), "status": "failed" if error else "completed"})

    def cancel_scan(self, scan_id: str, actor: str) -> None:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("UPDATE network_scans SET status='cancelled',error='Network scan cancelled',updated_at=?,updated_by=? WHERE id=?", (now, actor, scan_id))
        self.audit(actor, "scan", scan_id, "cancel", result="cancelled")

    def create_execution(self, template_id: str, actor: str, host_ids: list[str], warnings: list[Any], retry_of: str | None = None) -> dict[str, Any]:
        object_id, now = stable_id(), time.time()
        template = self._get("job_templates", template_id)
        if not template:
            raise KeyError("template not found")
        credential_ids = [value for key, value in template.items() if key.endswith("_credential_id") and value]
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO executions(id,template_id,retry_of,requested_by,status,stage,credential_ids_json,host_ids_json,warnings_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,'queued','queued',?,?,?,1,?,?,?,?)""",
                (object_id, template_id, retry_of, actor, json.dumps(credential_ids), json.dumps(host_ids), json.dumps(redact(warnings)), now, now, actor, actor),
            )
        self.audit(actor, "execution", object_id, "launch", {"template_id": template_id, "host_count": len(host_ids), "retry_of": retry_of})
        return self._get("executions", object_id) or {}

    def set_execution_job(self, execution_id: str, job_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("UPDATE executions SET package_job_id=?,updated_at=? WHERE id=?", (job_id, time.time(), execution_id))

    def update_execution(self, execution_id: str, actor: str, **values: Any) -> None:
        allowed = {"status", "stage", "inventory_snapshot", "playbook_snapshot", "project_commit", "summary_json", "stdout", "stderr", "exit_code", "started_at", "finished_at"}
        filtered = {key: value for key, value in values.items() if key in allowed}
        if not filtered:
            return
        if "summary_json" in filtered and not isinstance(filtered["summary_json"], str):
            filtered["summary_json"] = json.dumps(redact(filtered["summary_json"]))
        filtered["updated_at"] = time.time()
        filtered["updated_by"] = actor
        columns = ",".join(f"{key}=?" for key in filtered)
        with self._lock, self.connect() as connection:
            connection.execute(f"UPDATE executions SET {columns} WHERE id=?", (*filtered.values(), execution_id))

    def execution(self, execution_id: str) -> dict[str, Any] | None:
        item = self._get("executions", execution_id)
        if item:
            item["host_results"] = self._list("host_results", where="execution_id=?", values=(execution_id,), order="host_name", limit=5000)
        return item

    def executions(self) -> list[dict[str, Any]]:
        return self._list("executions", order="created_at DESC", limit=1000)

    def save_host_result(self, execution_id: str, actor: str, result: dict[str, Any]) -> None:
        now = time.time()
        with self._lock, self.connect() as connection:
            existing = connection.execute("SELECT id,created_at,created_by FROM host_results WHERE execution_id=? AND host_name=?", (execution_id, result["host_name"])).fetchone()
            object_id = existing["id"] if existing else stable_id()
            created_at, created_by = (existing["created_at"], existing["created_by"]) if existing else (now, actor)
            connection.execute(
                """INSERT INTO host_results(id,execution_id,host_id,host_name,status,ok_count,changed_count,failed_count,unreachable_count,skipped_count,rescued_count,ignored_count,message,created_at,updated_at,created_by,updated_by,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(execution_id,host_name) DO UPDATE SET status=excluded.status,ok_count=excluded.ok_count,changed_count=excluded.changed_count,failed_count=excluded.failed_count,unreachable_count=excluded.unreachable_count,skipped_count=excluded.skipped_count,rescued_count=excluded.rescued_count,ignored_count=excluded.ignored_count,message=excluded.message,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, execution_id, result.get("host_id"), result["host_name"], result.get("status", "unknown"), result.get("ok", 0), result.get("changed", 0), result.get("failed", 0), result.get("unreachable", 0), result.get("skipped", 0), result.get("rescued", 0), result.get("ignored", 0), str(redact(result.get("message", "")))[:4000], created_at, now, created_by, actor),
            )

    def acquire_host_locks(self, execution_id: str, host_ids: list[str]) -> None:
        with self._lock, self.connect() as connection:
            conflicts = connection.execute(f"SELECT host_id,execution_id FROM host_locks WHERE host_id IN ({','.join('?' for _ in host_ids)})", host_ids).fetchall() if host_ids else []
            if conflicts:
                raise RuntimeError("one or more target hosts are locked by another execution")
            connection.executemany("INSERT INTO host_locks(host_id,execution_id,acquired_at) VALUES(?,?,?)", [(host_id, execution_id, time.time()) for host_id in host_ids])

    def acquire_execution_locks(self, execution_id: str, template_id: str, host_ids: list[str], policy: str) -> None:
        if policy == "parallel":
            return
        if policy == "same_hosts":
            self.acquire_host_locks(execution_id, host_ids)
            return
        with self._lock, self.connect() as connection:
            if policy == "template":
                conflict = connection.execute(
                    "SELECT id FROM executions WHERE id<>? AND template_id=? AND status='running' LIMIT 1",
                    (execution_id, template_id),
                ).fetchone()
            elif policy == "single":
                conflict = connection.execute(
                    "SELECT id FROM executions WHERE id<>? AND status='running' LIMIT 1",
                    (execution_id,),
                ).fetchone()
            else:
                raise ValueError("invalid execution concurrency policy")
            if conflict:
                raise RuntimeError("execution is blocked by the selected concurrency policy")

    def release_host_locks(self, execution_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM host_locks WHERE execution_id=?", (execution_id,))

    def save_facts(self, host_id: str, actor: str, facts: dict[str, Any]) -> dict[str, Any]:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            safe = registry().save_facts(host_id, facts, actor)
            return {"host_id": host_id, "facts": safe}
        import hashlib

        safe = redact(facts)
        encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        now, object_id = time.time(), stable_id()
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO saved_facts(id,host_id,facts_json,checksum,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,1,?,?,?,?)", (object_id, host_id, encoded, hashlib.sha256(encoded.encode()).hexdigest(), now, now, actor, actor))
            connection.execute("UPDATE hosts SET last_facts_at=?,updated_at=?,updated_by=? WHERE id=?", (now, now, actor, host_id))
        return self._get("saved_facts", object_id) or {}

    def known_key(self, address: str, port: int) -> dict[str, Any] | None:
        if self.centralized_hosts:
            from ..hosts_manager.service import registry
            target = next((item for item in registry().list_hosts() if item["address"] == address and int(item["port"]) == port), None)
            if not target:
                return None
            keys = registry().host_keys(target["id"])
            if not keys:
                return None
            return keys[0] | {"address": address, "port": port}
        values = self._list("known_host_keys", where="address=? AND port=? AND active=1", values=(address, port), limit=1)
        return values[0] if values else None

    def accept_known_key(self, host_id: str | None, address: str, port: int, key_type: str, public_key: str, fingerprint: str, actor: str, replace: bool = False) -> dict[str, Any]:
        if self.centralized_hosts and host_id:
            from ..hosts_manager.service import registry
            try:
                return registry().accept_host_key(host_id, key_type, public_key, fingerprint, actor, replace)
            except PermissionError as error:
                raise RuntimeError(str(error)) from error
        existing = self.known_key(address, port)
        if existing and existing["fingerprint"] != fingerprint and not replace:
            raise RuntimeError("SSH host fingerprint changed; explicit replacement is required")
        now, object_id = time.time(), existing["id"] if existing else stable_id()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO known_host_keys(id,host_id,address,port,key_type,public_key,fingerprint,previous_fingerprint,status,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?)
                ON CONFLICT(address,port,key_type) DO UPDATE SET host_id=excluded.host_id,public_key=excluded.public_key,previous_fingerprint=known_host_keys.fingerprint,fingerprint=excluded.fingerprint,status='accepted',active=1,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (object_id, host_id, address, port, key_type, public_key, fingerprint, existing["fingerprint"] if existing else "", "accepted", existing["created_at"] if existing else now, now, existing["created_by"] if existing else actor, actor),
            )
            if host_id:
                connection.execute("UPDATE hosts SET fingerprint_status='accepted',updated_at=?,updated_by=? WHERE id=?", (now, actor, host_id))
        self.audit(actor, "host_key", object_id, "replace" if existing else "accept", {"address": address, "port": port, "fingerprint": fingerprint})
        return self._get("known_host_keys", object_id) or {}

    def setting(self, key: str) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            row = connection.execute("SELECT config_json FROM controller_settings WHERE key=? AND active=1", (key,)).fetchone()
        return json.loads(row["config_json"]) if row else {}

    def save_setting(self, key: str, value: dict[str, Any], actor: str) -> dict[str, Any]:
        now = time.time()
        safe = redact(value)
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO controller_settings(key,config_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,1,?,?,?,?) ON CONFLICT(key) DO UPDATE SET config_json=excluded.config_json,active=1,updated_at=excluded.updated_at,updated_by=excluded.updated_by", (key, json.dumps(safe), now, now, actor, actor))
        self.audit(actor, "settings", key, "update")
        return safe

    def audit(self, actor: str, object_type: str, object_id: str, action: str, details: dict[str, Any] | None = None, result: str = "success", correlation_id: str | None = None) -> None:
        now, event_id = time.time(), stable_id()
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO controller_audit_events(id,correlation_id,actor,object_type,object_id,action,result,details_json,active,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?)", (event_id, correlation_id or event_id, actor, object_type, object_id, action, result, json.dumps(redact(details or {})), now, now, actor, actor))

    def audit_events(self, limit: int = 500) -> list[dict[str, Any]]:
        return self._list("controller_audit_events", order="created_at DESC", limit=limit)

    def dashboard(self) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            def scalar(sql: str) -> int:
                return int(connection.execute(sql).fetchone()[0])

            latest_scan = connection.execute("SELECT id,status,created_at,discovered FROM network_scans ORDER BY created_at DESC LIMIT 1").fetchone()
            latest_sync = connection.execute("SELECT id,name,last_sync_at,last_sync_status,last_commit FROM projects WHERE last_sync_at IS NOT NULL ORDER BY last_sync_at DESC LIMIT 1").fetchone()
            central_hosts = self.list_hosts(active_only=True) if self.centralized_hosts else []
            return {
                "hosts": len(central_hosts) if self.centralized_hosts else scalar("SELECT count(*) FROM hosts WHERE active=1"),
                "hosts_online": sum(item["connection_status"] == "online" for item in central_hosts) if self.centralized_hosts else scalar("SELECT count(*) FROM hosts WHERE active=1 AND last_error='' AND last_test_at IS NOT NULL"),
                "hosts_unreachable": sum(item["connection_status"] == "offline" for item in central_hosts) if self.centralized_hosts else scalar("SELECT count(*) FROM hosts WHERE active=1 AND last_error<>''"),
                "host_key_errors": sum(item["fingerprint_status"] == "changed" for item in central_hosts) if self.centralized_hosts else scalar("SELECT count(*) FROM hosts WHERE active=1 AND fingerprint_status='changed'"),
                "groups": len([item for item in self.list_groups() if item["active"]]) if self.centralized_hosts else scalar("SELECT count(*) FROM inventory_groups WHERE active=1"),
                "projects": scalar("SELECT count(*) FROM projects WHERE active=1"),
                "playbooks": scalar("SELECT count(*) FROM playbooks WHERE active=1"),
                "templates": scalar("SELECT count(*) FROM job_templates WHERE active=1"),
                "active_jobs": scalar("SELECT count(*) FROM executions WHERE status IN ('queued','running')"),
                "failed_jobs": scalar("SELECT count(*) FROM executions WHERE status='failed'"),
                "scheduled": scalar("SELECT count(*) FROM schedules WHERE active=1"),
                "last_scan": dict(latest_scan) if latest_scan else None,
                "last_git_sync": dict(latest_sync) if latest_sync else None,
            }


@lru_cache
def repository() -> AnsibleRepository:
    return AnsibleRepository()
