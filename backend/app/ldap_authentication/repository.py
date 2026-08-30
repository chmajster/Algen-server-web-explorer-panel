from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_config
from ..identity.repository import repository as identity_repository
from ..modules.secrets_manager import SecretInput, service as secrets_service
from ..sqlite_utils import ClosingConnection
from .models import LdapAccessPolicyInput, LdapAuthenticationSettingsInput, LdapGroupMappingInput, LdapServerInput


AUTH_BIND_SECRET_NAME = "auth-ldap-bind-password"
AUTH_SECRET_MODULE = "settings"
SCHEMA_VERSION = 2


class LdapAuthenticationRepository:
    """Persistent state owned exclusively by Settings -> LDAP Authentication.

    The database deliberately stays at the historical ldap-auth.sqlite3 path so
    upgrades are in-place. LDAP Manager never reads this database and never
    reuses its bind secret.
    """

    def __init__(self, path: Path | None = None) -> None:
        root = Path(get_config().paths.data_dir).resolve(strict=False)
        self.path = path or root / "ldap-auth.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _json(value: Any, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return fallback
        return parsed

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ldap_auth_schema(
                    version INTEGER NOT NULL,
                    applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ldap_auth_settings_v2(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    directory_type TEXT NOT NULL DEFAULT 'auto',
                    failover_strategy TEXT NOT NULL DEFAULT 'priority',
                    dns_srv_domain TEXT NOT NULL DEFAULT '',
                    security_mode TEXT NOT NULL DEFAULT 'starttls',
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    ca_certificate TEXT NOT NULL DEFAULT '',
                    connect_timeout REAL NOT NULL DEFAULT 5,
                    operation_timeout REAL NOT NULL DEFAULT 10,
                    base_dn TEXT NOT NULL DEFAULT '',
                    user_search_base TEXT NOT NULL DEFAULT '',
                    user_search_filter TEXT NOT NULL DEFAULT '(uid={username})',
                    username_attribute TEXT NOT NULL DEFAULT 'uid',
                    immutable_id_attribute TEXT NOT NULL DEFAULT '',
                    bind_dn TEXT NOT NULL DEFAULT '',
                    bind_secret_id TEXT NOT NULL DEFAULT '',
                    display_name_attribute TEXT NOT NULL DEFAULT 'displayName',
                    email_attribute TEXT NOT NULL DEFAULT 'mail',
                    group_search_base TEXT NOT NULL DEFAULT '',
                    group_search_filter TEXT NOT NULL DEFAULT '(|(member={dn})(uniqueMember={dn})(memberUid={username}))',
                    group_membership_attribute TEXT NOT NULL DEFAULT 'memberOf',
                    group_cache_ttl_seconds INTEGER NOT NULL DEFAULT 300,
                    legacy_migrated INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO ldap_auth_settings_v2(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS ldap_auth_servers(
                    id TEXT PRIMARY KEY,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 10,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    position INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS ldap_auth_group_mappings(
                    id TEXT PRIMARY KEY,
                    group_dn TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    role TEXT NOT NULL DEFAULT 'user',
                    allow_json TEXT NOT NULL DEFAULT '[]',
                    deny_json TEXT NOT NULL DEFAULT '[]',
                    priority INTEGER NOT NULL DEFAULT 100,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ldap_auth_access_policy(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    mode TEXT NOT NULL DEFAULT 'allow_all',
                    allow_groups_json TEXT NOT NULL DEFAULT '[]',
                    deny_groups_json TEXT NOT NULL DEFAULT '[]',
                    updated_at REAL NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO ldap_auth_access_policy(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS ldap_auth_identities_v2(
                    immutable_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'ldap',
                    username TEXT NOT NULL,
                    canonical_username TEXT NOT NULL,
                    dn TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    uid INTEGER,
                    gid INTEGER,
                    home TEXT NOT NULL DEFAULT '',
                    groups_json TEXT NOT NULL DEFAULT '[]',
                    groups_refreshed_at REAL NOT NULL DEFAULT 0,
                    first_seen_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    last_login_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ldap_auth_identity_username
                    ON ldap_auth_identities_v2(canonical_username);
                """
            )
            row = connection.execute("SELECT version FROM ldap_auth_schema ORDER BY applied_at DESC LIMIT 1").fetchone()
            if row and int(row["version"]) > SCHEMA_VERSION:
                raise RuntimeError("LDAP authentication database was created by a newer WebNAS version")
            if not row or int(row["version"]) < SCHEMA_VERSION:
                connection.execute(
                    "INSERT INTO ldap_auth_schema(version,applied_at) VALUES(?,?)",
                    (SCHEMA_VERSION, time.time()),
                )
            self._migrate_legacy(connection)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _migrate_legacy(self, connection: sqlite3.Connection) -> None:
        state = connection.execute("SELECT legacy_migrated FROM ldap_auth_settings_v2 WHERE id=1").fetchone()
        if state and bool(state["legacy_migrated"]):
            return
        legacy_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ldap_settings'"
        ).fetchone()
        if legacy_exists:
            row = connection.execute("SELECT * FROM ldap_settings WHERE id=1").fetchone()
            if row:
                connection.execute(
                    """
                    UPDATE ldap_auth_settings_v2 SET
                        enabled=?,security_mode=?,verify_tls=?,connect_timeout=?,operation_timeout=?,
                        base_dn=?,user_search_base=?,user_search_filter=?,username_attribute=?,bind_dn=?,
                        bind_secret_id=?,display_name_attribute=?,email_attribute=?,legacy_migrated=1,
                        updated_at=?,updated_by='migration'
                    WHERE id=1
                    """,
                    (
                        int(row["enabled"]), str(row["security_mode"]), int(row["verify_tls"]),
                        float(row["connect_timeout"]), float(row["operation_timeout"]), str(row["base_dn"]),
                        str(row["user_search_base"]), str(row["user_search_filter"]), str(row["username_attribute"]),
                        str(row["bind_dn"]), str(row["bind_secret_id"]), str(row["display_name_attribute"]),
                        str(row["email_attribute"]), time.time(),
                    ),
                )
                host = str(row["server"] or "").strip()
                if host and not connection.execute("SELECT 1 FROM ldap_auth_servers LIMIT 1").fetchone():
                    connection.execute(
                        "INSERT INTO ldap_auth_servers(id,host,port,priority,enabled,position) VALUES(?,?,?,?,1,0)",
                        (str(uuid.uuid4()), host, int(row["port"]), 10),
                    )
        connection.execute("UPDATE ldap_auth_settings_v2 SET legacy_migrated=1 WHERE id=1")

        old_identity_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ldap_identities'"
        ).fetchone()
        if old_identity_exists:
            for row in connection.execute("SELECT * FROM ldap_identities").fetchall():
                username = str(row["username"])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ldap_auth_identities_v2(
                        immutable_id,provider,username,canonical_username,dn,display_name,email,home,
                        first_seen_at,last_seen_at,last_login_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"legacy:{username.casefold()}", "ldap", username, username.casefold(), str(row["dn"]),
                        str(row["display_name"] or ""), str(row["email"] or ""), str(row["home"] or ""),
                        float(row["created_at"]), float(row["last_login_at"]), float(row["last_login_at"]),
                    ),
                )

    def _settings_row(self) -> sqlite3.Row:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM ldap_auth_settings_v2 WHERE id=1").fetchone()
        if not row:
            raise RuntimeError("LDAP authentication settings are unavailable")
        return row

    def servers(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,host,port,priority,enabled FROM ldap_auth_servers ORDER BY priority,position,id"
            ).fetchall()
        return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]

    def settings(self, *, include_secret_id: bool = False) -> dict[str, Any]:
        row = self._settings_row()
        servers = self.servers()
        result = {
            "enabled": bool(row["enabled"]),
            "directory_type": str(row["directory_type"]),
            "servers": servers,
            "server": str(servers[0]["host"]) if servers else "",
            "port": int(servers[0]["port"]) if servers else 389,
            "failover_strategy": str(row["failover_strategy"]),
            "dns_srv_domain": str(row["dns_srv_domain"]),
            "security_mode": str(row["security_mode"]),
            "verify_tls": bool(row["verify_tls"]),
            "ca_certificate": str(row["ca_certificate"]),
            "connect_timeout": float(row["connect_timeout"]),
            "operation_timeout": float(row["operation_timeout"]),
            "base_dn": str(row["base_dn"]),
            "user_search_base": str(row["user_search_base"]),
            "user_search_filter": str(row["user_search_filter"]),
            "username_attribute": str(row["username_attribute"]),
            "immutable_id_attribute": str(row["immutable_id_attribute"]),
            "bind_dn": str(row["bind_dn"]),
            "bind_password_configured": bool(row["bind_secret_id"]),
            "display_name_attribute": str(row["display_name_attribute"]),
            "email_attribute": str(row["email_attribute"]),
            "group_search_base": str(row["group_search_base"]),
            "group_search_filter": str(row["group_search_filter"]),
            "group_membership_attribute": str(row["group_membership_attribute"]),
            "group_cache_ttl_seconds": int(row["group_cache_ttl_seconds"]),
        }
        if include_secret_id:
            result["bind_secret_id"] = str(row["bind_secret_id"])
        return result

    def save(self, payload: LdapAuthenticationSettingsInput, actor: str, *, enabled: bool | None = None) -> dict[str, Any]:
        current = self.settings(include_secret_id=True)
        secret_id = str(current.get("bind_secret_id") or "")
        if payload.clear_bind_password:
            if payload.enabled:
                raise ValueError("Disable LDAP authentication before clearing its bind password")
            if secret_id:
                secrets_service().delete(secret_id, actor)
                secret_id = ""
        elif payload.bind_password:
            secret = secrets_service().save(
                SecretInput(
                    name=AUTH_BIND_SECRET_NAME,
                    type="generic_secret",
                    secret=payload.bind_password,
                    description="WebNAS LDAP Authentication read-only service bind credential",
                    shared_with=[AUTH_SECRET_MODULE],
                ),
                actor,
                secret_id or None,
            )
            secret_id = str(secret["id"])
        elif secret_id:
            secrets_service().save(
                SecretInput(
                    name=AUTH_BIND_SECRET_NAME,
                    type="generic_secret",
                    description="WebNAS LDAP Authentication read-only service bind credential",
                    shared_with=[AUTH_SECRET_MODULE],
                ),
                actor,
                secret_id,
            )
        requested_enabled = payload.enabled if enabled is None else enabled
        if requested_enabled and not secret_id:
            raise ValueError("LDAP Authentication bind password is required before activation")

        servers = list(payload.servers)
        if not servers and payload.server:
            servers = [LdapServerInput(host=payload.server, port=payload.port, priority=10, enabled=True)]
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE ldap_auth_settings_v2 SET
                    enabled=?,directory_type=?,failover_strategy=?,dns_srv_domain=?,security_mode=?,verify_tls=?,
                    ca_certificate=?,connect_timeout=?,operation_timeout=?,base_dn=?,user_search_base=?,user_search_filter=?,
                    username_attribute=?,immutable_id_attribute=?,bind_dn=?,bind_secret_id=?,display_name_attribute=?,
                    email_attribute=?,group_search_base=?,group_search_filter=?,group_membership_attribute=?,
                    group_cache_ttl_seconds=?,updated_at=?,updated_by=? WHERE id=1
                """,
                (
                    int(requested_enabled), payload.directory_type.value, payload.failover_strategy.value,
                    payload.dns_srv_domain, payload.security_mode.value, int(payload.verify_tls), payload.ca_certificate,
                    payload.connect_timeout, payload.operation_timeout, payload.base_dn, payload.user_search_base,
                    payload.user_search_filter, payload.username_attribute, payload.immutable_id_attribute, payload.bind_dn,
                    secret_id, payload.display_name_attribute, payload.email_attribute, payload.group_search_base,
                    payload.group_search_filter, payload.group_membership_attribute, payload.group_cache_ttl_seconds,
                    time.time(), actor,
                ),
            )
            connection.execute("DELETE FROM ldap_auth_servers")
            for position, item in enumerate(servers):
                connection.execute(
                    "INSERT INTO ldap_auth_servers(id,host,port,priority,enabled,position) VALUES(?,?,?,?,?,?)",
                    (item.id or str(uuid.uuid4()), item.host, item.port, item.priority, int(item.enabled), position),
                )
        return self.settings()

    def set_enabled(self, enabled: bool, actor: str) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE ldap_auth_settings_v2 SET enabled=?,updated_at=?,updated_by=? WHERE id=1",
                (int(enabled), time.time(), actor),
            )
        return self.settings()

    def mappings(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ldap_auth_group_mappings ORDER BY priority,group_dn"
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "group_dn": str(row["group_dn"]),
                "role": str(row["role"]),
                "allow": self._json(row["allow_json"], []),
                "deny": self._json(row["deny_json"], []),
                "priority": int(row["priority"]),
            }
            for row in rows
        ]

    def save_mapping(self, payload: LdapGroupMappingInput, actor: str, mapping_id: str | None = None) -> dict[str, Any]:
        identifier = mapping_id or str(uuid.uuid4())
        now = time.time()
        with self._lock, self.connect() as connection:
            if mapping_id and not connection.execute("SELECT 1 FROM ldap_auth_group_mappings WHERE id=?", (mapping_id,)).fetchone():
                raise LookupError("LDAP group mapping not found")
            connection.execute(
                """
                INSERT INTO ldap_auth_group_mappings(id,group_dn,role,allow_json,deny_json,priority,updated_at,updated_by)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET group_dn=excluded.group_dn,role=excluded.role,
                    allow_json=excluded.allow_json,deny_json=excluded.deny_json,priority=excluded.priority,
                    updated_at=excluded.updated_at,updated_by=excluded.updated_by
                """,
                (identifier, payload.group_dn, payload.role.value, json.dumps(payload.allow), json.dumps(payload.deny), payload.priority, now, actor),
            )
        return next(item for item in self.mappings() if item["id"] == identifier)

    def delete_mapping(self, mapping_id: str) -> bool:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM ldap_auth_group_mappings WHERE id=?", (mapping_id,))
        return int(cursor.rowcount) > 0

    def access_policy(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM ldap_auth_access_policy WHERE id=1").fetchone()
        if not row:
            return {"mode": "allow_all", "allow_groups": [], "deny_groups": []}
        return {
            "mode": str(row["mode"]),
            "allow_groups": self._json(row["allow_groups_json"], []),
            "deny_groups": self._json(row["deny_groups_json"], []),
        }

    def save_access_policy(self, payload: LdapAccessPolicyInput, actor: str) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            connection.execute(
                """UPDATE ldap_auth_access_policy SET mode=?,allow_groups_json=?,deny_groups_json=?,updated_at=?,updated_by=? WHERE id=1""",
                (payload.mode, json.dumps(payload.allow_groups), json.dumps(payload.deny_groups), time.time(), actor),
            )
        return self.access_policy()

    def identity_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ldap_auth_identities_v2 WHERE canonical_username=?",
                (username.casefold(),),
            ).fetchone()
        return self._identity(row) if row else None

    def identity_by_id(self, immutable_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM ldap_auth_identities_v2 WHERE immutable_id=?", (immutable_id,)).fetchone()
        return self._identity(row) if row else None

    def _identity(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["groups"] = self._json(value.pop("groups_json", "[]"), [])
        return value

    def remember_identity(
        self,
        immutable_id: str,
        username: str,
        dn: str,
        *,
        display_name: str,
        email: str,
        uid: int | None,
        gid: int | None,
        home: str,
        groups: list[str],
        logged_in: bool = True,
    ) -> dict[str, Any]:
        now = time.time()
        existing = self.identity_by_id(immutable_id)
        legacy = self.identity_by_username(username)
        if existing is None and legacy and str(legacy["immutable_id"]).startswith("legacy:"):
            existing = legacy
        previous_username = str(existing["username"]) if existing else ""
        first_seen = float(existing["first_seen_at"]) if existing else now
        last_login = now if logged_in else float(existing["last_login_at"]) if existing else 0.0
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if existing and str(existing["immutable_id"]) != immutable_id:
                connection.execute("DELETE FROM ldap_auth_identities_v2 WHERE immutable_id=?", (existing["immutable_id"],))
            connection.execute(
                """
                INSERT INTO ldap_auth_identities_v2(
                    immutable_id,provider,username,canonical_username,dn,display_name,email,uid,gid,home,groups_json,
                    groups_refreshed_at,first_seen_at,last_seen_at,last_login_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(immutable_id) DO UPDATE SET
                    username=excluded.username,canonical_username=excluded.canonical_username,dn=excluded.dn,
                    display_name=excluded.display_name,email=excluded.email,uid=excluded.uid,gid=excluded.gid,
                    home=excluded.home,groups_json=excluded.groups_json,groups_refreshed_at=excluded.groups_refreshed_at,
                    last_seen_at=excluded.last_seen_at,last_login_at=excluded.last_login_at
                """,
                (
                    immutable_id, "ldap", username, username.casefold(), dn, display_name, email, uid, gid, home,
                    json.dumps(groups, ensure_ascii=False), now, first_seen, now, last_login,
                ),
            )
        if previous_username and previous_username.casefold() != username.casefold():
            policies = identity_repository()
            if policies.user_policy(previous_username) and not policies.user_policy(username):
                policies.rename_user_policy(previous_username, username, "ldap-identity-sync")
        return self.identity_by_id(immutable_id) or {}

    def update_groups(self, immutable_id: str, groups: list[str]) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE ldap_auth_identities_v2 SET groups_json=?,groups_refreshed_at=?,last_seen_at=? WHERE immutable_id=?",
                (json.dumps(groups, ensure_ascii=False), time.time(), time.time(), immutable_id),
            )

    def home(self, username: str) -> str | None:
        identity = self.identity_by_username(username)
        return str(identity["home"]) if identity else None


@lru_cache(maxsize=1)
def repository() -> LdapAuthenticationRepository:
    return LdapAuthenticationRepository()
