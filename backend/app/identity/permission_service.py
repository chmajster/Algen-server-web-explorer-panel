from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from fastapi import HTTPException

from ..config import get_config
from ..security import SessionUser
from ..sqlite_utils import ClosingConnection
from .permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS

Effect = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class Resource:
    resource_type: str = "global"
    resource_id: str = "*"
    scope: str = "*"


@dataclass(frozen=True, slots=True)
class DecisionSource:
    effect: Effect
    permission: str
    source_type: str
    source_id: str
    source_name: str
    resource_type: str = "global"
    resource_id: str = "*"
    scope: str = "*"
    reason: str = ""


@dataclass(slots=True)
class PermissionDecision:
    allowed: bool
    permission: str
    resource: Resource
    sources: list[DecisionSource] = field(default_factory=list)
    reason: str = "default deny"

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": "ALLOW" if self.allowed else "DENY",
            "permission": self.permission,
            "resource": asdict(self.resource),
            "reason": self.reason,
            "sources": [asdict(source) for source in self.sources],
        }


PERMISSION_ALIASES = {
    "desktop.read": "settings.view_own",
    "desktop.manage": "settings.edit_own",
    "files.write": "files.edit",
    "files.share": "files.download",
    "groups.read": "groups.view",
    "groups.update": "groups.manage_members",
    "roles.read": "access.view",
    "roles.create": "access.manage_roles",
    "roles.update": "access.manage_roles",
    "roles.delete": "access.manage_roles",
    "docker.read": "docker.view",
    "docker.manage": "docker.manage_containers",
    "services.read": "services.view",
    "services.manage": "services.restart",
    "system.read": "settings.view_system",
    "system.manage": "settings.edit_system",
    "settings.read": "settings.view_system",
    "settings.manage": "settings.edit_system",
    "rbac.read": "access.view",
    "rbac.manage": "access.manage_roles",
    "ldap.read": "access.view",
    "ldap.manage": "access.manage_roles",
    "audit.read": "audit.view_all",
}


def normalize_permission_id(permission: str) -> str:
    value = PERMISSION_ALIASES.get(permission.strip(), permission.strip())
    if value not in ALL_PERMISSIONS:
        raise HTTPException(422, f"Unknown permission: {permission}")
    return value


def _role_permissions(name: str) -> set[str]:
    for role, permissions in ROLE_PERMISSIONS.items():
        if str(getattr(role, "value", role)).casefold() == name.casefold():
            return set(permissions)
    return set()


SYSTEM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": set(ALL_PERMISSIONS),
    "Operator": _role_permissions("operator"),
    "Auditor": _role_permissions("auditor"),
    "User": _role_permissions("user"),
    "Read Only": {
        permission
        for permission in ALL_PERMISSIONS
        if permission.endswith((".view", ".read", ".view_own"))
    },
}


class PermissionRepository:
    """Dynamic RBAC tables in the existing identity.sqlite3 store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(get_config().paths.data_dir) / "identity.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rbac_roles(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    role_type TEXT NOT NULL CHECK(role_type IN ('system','custom')),
                    protected INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rbac_role_permissions(
                    role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                    permission TEXT NOT NULL,
                    effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
                    resource_type TEXT NOT NULL DEFAULT 'global',
                    resource_id TEXT NOT NULL DEFAULT '*',
                    scope TEXT NOT NULL DEFAULT '*',
                    PRIMARY KEY(role_id,permission,effect,resource_type,resource_id,scope)
                );
                CREATE TABLE IF NOT EXISTS rbac_groups(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'local',
                    external_id TEXT NOT NULL DEFAULT '',
                    distinguished_name TEXT NOT NULL DEFAULT '',
                    managed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rbac_group_members(
                    group_id TEXT NOT NULL REFERENCES rbac_groups(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    PRIMARY KEY(group_id,provider,identity_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_group_roles(
                    group_id TEXT NOT NULL REFERENCES rbac_groups(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                    PRIMARY KEY(group_id,role_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_user_roles(
                    provider TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                    created_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY(provider,identity_id,role_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_external_groups(
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    distinguished_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    parent_ids_json TEXT NOT NULL DEFAULT '[]',
                    last_seen_at REAL NOT NULL DEFAULT 0,
                    UNIQUE(provider_id,external_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_external_memberships(
                    external_group_id TEXT NOT NULL REFERENCES rbac_external_groups(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    direct INTEGER NOT NULL DEFAULT 1,
                    last_seen_at REAL NOT NULL,
                    PRIMARY KEY(external_group_id,provider,identity_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_external_group_roles(
                    external_group_id TEXT NOT NULL REFERENCES rbac_external_groups(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                    PRIMARY KEY(external_group_id,role_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_policies(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
                    permission TEXT NOT NULL,
                    resource_type TEXT NOT NULL DEFAULT 'global',
                    resource_id TEXT NOT NULL DEFAULT '*',
                    scope TEXT NOT NULL DEFAULT '*',
                    conditions_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rbac_policy_subjects(
                    policy_id TEXT NOT NULL REFERENCES rbac_policies(id) ON DELETE CASCADE,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    PRIMARY KEY(policy_id,subject_type,subject_id)
                );
                CREATE TABLE IF NOT EXISTS rbac_audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    before_json TEXT NOT NULL DEFAULT '{}',
                    after_json TEXT NOT NULL DEFAULT '{}',
                    timestamp REAL NOT NULL,
                    source_ip TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_rbac_group_members_identity
                    ON rbac_group_members(provider,identity_id);
                CREATE INDEX IF NOT EXISTS idx_rbac_ext_members_identity
                    ON rbac_external_memberships(provider,identity_id);
                CREATE INDEX IF NOT EXISTS idx_rbac_audit_time
                    ON rbac_audit(timestamp DESC);
                """
            )
            self._seed_system_roles(connection)

    def _seed_system_roles(self, connection: sqlite3.Connection) -> None:
        now = time.time()
        for name, permissions in SYSTEM_ROLE_PERMISSIONS.items():
            role_id = f"system:{name.casefold().replace(' ', '-')}"
            connection.execute(
                """
                INSERT OR IGNORE INTO rbac_roles(
                    id,name,description,active,role_type,protected,
                    created_at,created_by,updated_at,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    role_id,
                    name,
                    f"WebNAS system role: {name}",
                    1,
                    "system",
                    1,
                    now,
                    "migration",
                    now,
                    "migration",
                ),
            )
            for permission in permissions:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO rbac_role_permissions(
                        role_id,permission,effect
                    ) VALUES(?,?, 'allow')
                    """,
                    (role_id, permission),
                )

    @staticmethod
    def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        actor: str,
        action: str,
        target: str,
        before: Any,
        after: Any,
        source_ip: str = "",
    ) -> None:
        connection.execute(
            """
            INSERT INTO rbac_audit(
                actor,action,target,before_json,after_json,timestamp,source_ip
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                actor,
                action,
                target,
                json.dumps(before, default=str, sort_keys=True),
                json.dumps(after, default=str, sort_keys=True),
                time.time(),
                source_ip,
            ),
        )

    def permissions(self) -> list[dict[str, str]]:
        canonical = [
            {"id": item, "category": item.split(".", 1)[0], "canonical": item}
            for item in sorted(ALL_PERMISSIONS)
        ]
        aliases = [
            {"id": alias, "category": alias.split(".", 1)[0], "canonical": target}
            for alias, target in sorted(PERMISSION_ALIASES.items())
        ]
        return canonical + aliases

    def roles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            result = self._dicts(
                connection.execute(
                    "SELECT * FROM rbac_roles ORDER BY role_type DESC,name"
                )
            )
            for role in result:
                role["permissions"] = self._dicts(
                    connection.execute(
                        """
                        SELECT permission,effect,resource_type,resource_id,scope
                        FROM rbac_role_permissions
                        WHERE role_id=? ORDER BY permission
                        """,
                        (role["id"],),
                    )
                )
            return result

    def role(self, role_id: str) -> dict[str, Any]:
        result = next((item for item in self.roles() if item["id"] == role_id), None)
        if not result:
            raise HTTPException(404, "Role not found")
        return result

    def create_role(
        self,
        payload: dict[str, Any],
        actor: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        role_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO rbac_roles VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        role_id,
                        str(payload["name"]).strip(),
                        str(payload.get("description") or ""),
                        int(payload.get("active", True)),
                        "custom",
                        0,
                        now,
                        actor,
                        now,
                        actor,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Role name already exists") from exc
            self._replace_role_permissions(
                connection,
                role_id,
                payload.get("permissions") or [],
            )
            self._audit(connection, actor, "role.create", role_id, {}, payload, source_ip)
        return self.role(role_id)

    def update_role(
        self,
        role_id: str,
        payload: dict[str, Any],
        actor: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        before = self.role(role_id)
        if before["protected"] and payload.get("name") not in (None, before["name"]):
            raise HTTPException(409, "System role name is protected")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE rbac_roles
                SET name=?,description=?,active=?,updated_at=?,updated_by=?
                WHERE id=?
                """,
                (
                    payload.get("name", before["name"]),
                    payload.get("description", before["description"]),
                    int(payload.get("active", bool(before["active"]))),
                    time.time(),
                    actor,
                    role_id,
                ),
            )
            if "permissions" in payload:
                self._replace_role_permissions(connection, role_id, payload["permissions"])
            self._audit(
                connection,
                actor,
                "role.update",
                role_id,
                before,
                payload,
                source_ip,
            )
        return self.role(role_id)

    def _replace_role_permissions(
        self,
        connection: sqlite3.Connection,
        role_id: str,
        permissions: list[dict[str, Any]],
    ) -> None:
        connection.execute(
            "DELETE FROM rbac_role_permissions WHERE role_id=?",
            (role_id,),
        )
        for item in permissions:
            permission = normalize_permission_id(str(item["permission"]))
            connection.execute(
                """
                INSERT INTO rbac_role_permissions(
                    role_id,permission,effect,resource_type,resource_id,scope
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    role_id,
                    permission,
                    item.get("effect", "allow"),
                    item.get("resource_type", "global"),
                    item.get("resource_id", "*"),
                    item.get("scope", "*"),
                ),
            )

    def delete_role(self, role_id: str, actor: str, source_ip: str = "") -> None:
        before = self.role(role_id)
        if before["protected"]:
            raise HTTPException(409, "System role is protected")
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM rbac_roles WHERE id=?", (role_id,))
            self._audit(
                connection,
                actor,
                "role.delete",
                role_id,
                before,
                {},
                source_ip,
            )

    def groups(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            result = self._dicts(
                connection.execute("SELECT * FROM rbac_groups ORDER BY source,name")
            )
            for group in result:
                group["roles"] = [
                    row["role_id"]
                    for row in connection.execute(
                        "SELECT role_id FROM rbac_group_roles WHERE group_id=?",
                        (group["id"],),
                    )
                ]
                group["members"] = self._dicts(
                    connection.execute(
                        """
                        SELECT provider,identity_id,username
                        FROM rbac_group_members
                        WHERE group_id=? ORDER BY username
                        """,
                        (group["id"],),
                    )
                )
            return result

    def group(self, group_id: str) -> dict[str, Any]:
        result = next((item for item in self.groups() if item["id"] == group_id), None)
        if not result:
            raise HTTPException(404, "Group not found")
        return result

    def create_group(
        self,
        payload: dict[str, Any],
        actor: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        group_id = str(uuid.uuid4())
        now = time.time()
        source = str(payload.get("source") or "local")
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO rbac_groups VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        group_id,
                        str(payload["name"]).strip(),
                        str(payload.get("description") or ""),
                        int(payload.get("active", True)),
                        source,
                        str(payload.get("external_id") or ""),
                        str(payload.get("distinguished_name") or ""),
                        int(source != "local"),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Group name already exists") from exc
            self._replace_group_roles(connection, group_id, payload.get("role_ids") or [])
            self._audit(connection, actor, "group.create", group_id, {}, payload, source_ip)
        return self.group(group_id)

    def update_group(
        self,
        group_id: str,
        payload: dict[str, Any],
        actor: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        before = self.group(group_id)
        if before["managed"] and any(
            key in payload for key in ("name", "external_id", "distinguished_name")
        ):
            raise HTTPException(409, "LDAP-managed attributes are read-only")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE rbac_groups SET description=?,active=?,updated_at=? WHERE id=?
                """,
                (
                    payload.get("description", before["description"]),
                    int(payload.get("active", bool(before["active"]))),
                    time.time(),
                    group_id,
                ),
            )
            if not before["managed"] and "name" in payload:
                connection.execute(
                    "UPDATE rbac_groups SET name=? WHERE id=?",
                    (payload["name"], group_id),
                )
            if "role_ids" in payload:
                self._replace_group_roles(connection, group_id, payload["role_ids"])
            self._audit(
                connection,
                actor,
                "group.update",
                group_id,
                before,
                payload,
                source_ip,
            )
        return self.group(group_id)

    def _replace_group_roles(
        self,
        connection: sqlite3.Connection,
        group_id: str,
        role_ids: list[str],
    ) -> None:
        connection.execute("DELETE FROM rbac_group_roles WHERE group_id=?", (group_id,))
        for role_id in role_ids:
            self.role(role_id)
            connection.execute(
                "INSERT INTO rbac_group_roles VALUES(?,?)",
                (group_id, role_id),
            )

    def delete_group(self, group_id: str, actor: str, source_ip: str = "") -> None:
        before = self.group(group_id)
        if before["managed"]:
            raise HTTPException(409, "LDAP-managed groups cannot be deleted locally")
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM rbac_groups WHERE id=?", (group_id,))
            self._audit(
                connection,
                actor,
                "group.delete",
                group_id,
                before,
                {},
                source_ip,
            )

    def set_group_members(
        self,
        group_id: str,
        members: list[dict[str, str]],
        actor: str,
        source_ip: str = "",
    ) -> None:
        group = self.group(group_id)
        if group["managed"]:
            raise HTTPException(409, "LDAP-managed group membership cannot be edited locally")
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM rbac_group_members WHERE group_id=?",
                (group_id,),
            )
            for item in members:
                username = item["username"]
                connection.execute(
                    "INSERT INTO rbac_group_members VALUES(?,?,?,?)",
                    (
                        group_id,
                        item.get("provider", "pam"),
                        item.get("identity_id") or username,
                        username,
                    ),
                )
            self._audit(
                connection,
                actor,
                "group.members.update",
                group_id,
                group.get("members", []),
                members,
                source_ip,
            )

    def external_groups(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            result = self._dicts(
                connection.execute("SELECT * FROM rbac_external_groups ORDER BY name")
            )
            for group in result:
                group["role_ids"] = [
                    row["role_id"]
                    for row in connection.execute(
                        """
                        SELECT role_id FROM rbac_external_group_roles
                        WHERE external_group_id=?
                        """,
                        (group["id"],),
                    )
                ]
                group["parent_ids"] = json.loads(group.pop("parent_ids_json") or "[]")
            return result

    def upsert_external_group(
        self,
        provider_id: str,
        external_id: str,
        distinguished_name: str,
        name: str,
        parent_ids: list[str] | None = None,
        status: str = "active",
    ) -> str:
        group_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"webnas:{provider_id}:{external_id}")
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rbac_external_groups(
                    id,provider_id,external_id,distinguished_name,name,status,
                    parent_ids_json,last_seen_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_id,external_id) DO UPDATE SET
                    distinguished_name=excluded.distinguished_name,
                    name=excluded.name,status=excluded.status,
                    parent_ids_json=excluded.parent_ids_json,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    group_id,
                    provider_id,
                    external_id,
                    distinguished_name,
                    name,
                    status,
                    json.dumps(parent_ids or []),
                    time.time(),
                ),
            )
        return group_id

    def map_external_group_role(
        self,
        group_id: str,
        role_id: str,
        actor: str,
        source_ip: str = "",
    ) -> None:
        self.role(role_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO rbac_external_group_roles VALUES(?,?)",
                (group_id, role_id),
            )
            self._audit(
                connection,
                actor,
                "ldap.mapping.create",
                group_id,
                {},
                {"role_id": role_id},
                source_ip,
            )

    def unmap_external_group_role(
        self,
        group_id: str,
        role_id: str,
        actor: str,
        source_ip: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                DELETE FROM rbac_external_group_roles
                WHERE external_group_id=? AND role_id=?
                """,
                (group_id, role_id),
            )
            self._audit(
                connection,
                actor,
                "ldap.mapping.delete",
                group_id,
                {"role_id": role_id},
                {},
                source_ip,
            )

    def replace_external_memberships(
        self,
        provider_id: str,
        identity_id: str,
        username: str,
        group_ids: set[str],
        direct_group_ids: set[str] | None = None,
    ) -> None:
        direct_group_ids = direct_group_ids or group_ids
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                DELETE FROM rbac_external_memberships
                WHERE provider=? AND identity_id=?
                """,
                (provider_id, identity_id),
            )
            now = time.time()
            for group_id in group_ids:
                connection.execute(
                    "INSERT INTO rbac_external_memberships VALUES(?,?,?,?,?,?)",
                    (
                        group_id,
                        provider_id,
                        identity_id,
                        username,
                        int(group_id in direct_group_ids),
                        now,
                    ),
                )

    def assign_user_role(
        self,
        user: SessionUser,
        role_id: str,
        actor: str,
        source_ip: str = "",
    ) -> None:
        self.role(role_id)
        identity_id = user.identity_id or user.username
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO rbac_user_roles(
                    provider,identity_id,username,role_id,created_at,created_by
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    user.auth_provider,
                    identity_id,
                    user.username,
                    role_id,
                    time.time(),
                    actor,
                ),
            )
            self._audit(
                connection,
                actor,
                "assignment.user-role",
                f"{user.auth_provider}:{identity_id}",
                {},
                {"role_id": role_id},
                source_ip,
            )

    def revoke_user_role(
        self,
        user: SessionUser,
        role_id: str,
        actor: str,
        source_ip: str = "",
    ) -> None:
        identity_id = user.identity_id or user.username
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                DELETE FROM rbac_user_roles
                WHERE provider=? AND identity_id=? AND role_id=?
                """,
                (user.auth_provider, identity_id, role_id),
            )
            self._audit(
                connection,
                actor,
                "assignment.user-role.revoke",
                f"{user.auth_provider}:{identity_id}",
                {"role_id": role_id},
                {},
                source_ip,
            )

    def policies(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            result = self._dicts(
                connection.execute("SELECT * FROM rbac_policies ORDER BY name")
            )
            for item in result:
                item["conditions"] = json.loads(item.pop("conditions_json") or "{}")
                item["subjects"] = self._dicts(
                    connection.execute(
                        """
                        SELECT subject_type,subject_id FROM rbac_policy_subjects
                        WHERE policy_id=?
                        """,
                        (item["id"],),
                    )
                )
            return result

    def policy(self, policy_id: str) -> dict[str, Any]:
        result = next((item for item in self.policies() if item["id"] == policy_id), None)
        if not result:
            raise HTTPException(404, "Policy not found")
        return result

    def create_policy(
        self,
        payload: dict[str, Any],
        actor: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        policy_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, self._connect() as connection:
            self._insert_or_replace_policy(
                connection,
                policy_id,
                payload,
                actor,
                now,
                created=True,
            )
            self._audit(
                connection,
                actor,
                "policy.create",
                policy_id,
                {},
                payload,
                source_ip,
            )
        return self.policy(policy_id)

    def update_policy(
        self,
        policy_id: str,
        payload: dict[str, Any],
        actor: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        before = self.policy(policy_id)
        merged = {**before, **payload}
        merged["conditions"] = payload.get("conditions", before["conditions"])
        merged["subjects"] = payload.get("subjects", before["subjects"])
        with self._lock, self._connect() as connection:
            self._insert_or_replace_policy(
                connection,
                policy_id,
                merged,
                actor,
                float(before["created_at"]),
                created=False,
            )
            self._audit(
                connection,
                actor,
                "policy.update",
                policy_id,
                before,
                payload,
                source_ip,
            )
        return self.policy(policy_id)

    def _insert_or_replace_policy(
        self,
        connection: sqlite3.Connection,
        policy_id: str,
        payload: dict[str, Any],
        actor: str,
        created_at: float,
        *,
        created: bool,
    ) -> None:
        permission = normalize_permission_id(str(payload["permission"]))
        created_by = actor if created else str(payload.get("created_by") or actor)
        connection.execute(
            """
            INSERT OR REPLACE INTO rbac_policies VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                policy_id,
                str(payload["name"]).strip(),
                str(payload.get("description") or ""),
                int(payload.get("active", True)),
                payload.get("effect", "allow"),
                permission,
                payload.get("resource_type", "global"),
                payload.get("resource_id", "*"),
                payload.get("scope", "*"),
                json.dumps(payload.get("conditions") or {}),
                created_at,
                created_by,
                time.time(),
                actor,
            ),
        )
        connection.execute(
            "DELETE FROM rbac_policy_subjects WHERE policy_id=?",
            (policy_id,),
        )
        for subject in payload.get("subjects") or []:
            connection.execute(
                "INSERT INTO rbac_policy_subjects VALUES(?,?,?)",
                (policy_id, subject["subject_type"], subject["subject_id"]),
            )

    def delete_policy(self, policy_id: str, actor: str, source_ip: str = "") -> None:
        before = self.policy(policy_id)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM rbac_policies WHERE id=?", (policy_id,))
            self._audit(
                connection,
                actor,
                "policy.delete",
                policy_id,
                before,
                {},
                source_ip,
            )

    def effective_sources(self, user: SessionUser) -> list[DecisionSource]:
        identity_id = user.identity_id or user.username
        result: list[DecisionSource] = []
        with self._connect() as connection:
            direct = connection.execute(
                """
                SELECT rp.*,r.id source_id,r.name source_name,'' reason
                FROM rbac_user_roles ur
                JOIN rbac_roles r ON r.id=ur.role_id AND r.active=1
                JOIN rbac_role_permissions rp ON rp.role_id=r.id
                WHERE ur.provider=? AND ur.identity_id=?
                """,
                (user.auth_provider, identity_id),
            )
            result.extend(self._sources(direct, "direct-role"))

            local = connection.execute(
                """
                SELECT rp.*,g.id source_id,
                    (g.name||' -> '||r.name) source_name,'' reason
                FROM rbac_group_members gm
                JOIN rbac_groups g ON g.id=gm.group_id AND g.active=1
                JOIN rbac_group_roles gr ON gr.group_id=g.id
                JOIN rbac_roles r ON r.id=gr.role_id AND r.active=1
                JOIN rbac_role_permissions rp ON rp.role_id=r.id
                WHERE gm.provider=? AND gm.identity_id=?
                """,
                (user.auth_provider, identity_id),
            )
            result.extend(self._sources(local, "local-group"))

            external = connection.execute(
                """
                SELECT rp.*,eg.id source_id,
                    (eg.name||' -> '||r.name) source_name,
                    eg.distinguished_name reason
                FROM rbac_external_memberships em
                JOIN rbac_external_groups eg
                    ON eg.id=em.external_group_id AND eg.status='active'
                JOIN rbac_external_group_roles er
                    ON er.external_group_id=eg.id
                JOIN rbac_roles r ON r.id=er.role_id AND r.active=1
                JOIN rbac_role_permissions rp ON rp.role_id=r.id
                WHERE em.provider=? AND em.identity_id=?
                """,
                (user.auth_provider, identity_id),
            )
            result.extend(self._sources(external, "ldap-group"))

            for policy in connection.execute(
                "SELECT * FROM rbac_policies WHERE active=1"
            ):
                subjects = list(
                    connection.execute(
                        """
                        SELECT subject_type,subject_id FROM rbac_policy_subjects
                        WHERE policy_id=?
                        """,
                        (policy["id"],),
                    )
                )
                conditions = json.loads(policy["conditions_json"] or "{}")
                if self._policy_matches(user, subjects, connection, conditions):
                    result.append(
                        DecisionSource(
                            policy["effect"],
                            policy["permission"],
                            "policy",
                            policy["id"],
                            policy["name"],
                            policy["resource_type"],
                            policy["resource_id"],
                            policy["scope"],
                            "conditional policy",
                        )
                    )
        return result

    @staticmethod
    def _sources(
        rows: Iterable[sqlite3.Row],
        source_type: str,
    ) -> list[DecisionSource]:
        return [
            DecisionSource(
                row["effect"],
                row["permission"],
                source_type,
                row["source_id"],
                row["source_name"],
                row["resource_type"],
                row["resource_id"],
                row["scope"],
                row["reason"],
            )
            for row in rows
        ]

    @staticmethod
    def _policy_matches(
        user: SessionUser,
        subjects: list[sqlite3.Row],
        connection: sqlite3.Connection,
        conditions: dict[str, Any],
    ) -> bool:
        identity_id = user.identity_id or user.username
        if conditions.get("auth_provider") and conditions["auth_provider"] != user.auth_provider:
            return False
        if not subjects:
            return True
        for subject in subjects:
            subject_type = subject["subject_type"]
            subject_id = subject["subject_id"]
            if subject_type == "user" and subject_id in {identity_id, user.username}:
                return True
            if subject_type == "provider" and subject_id == user.auth_provider:
                return True
            if subject_type == "group":
                found = connection.execute(
                    """
                    SELECT 1 FROM rbac_group_members
                    WHERE group_id=? AND provider=? AND identity_id=?
                    """,
                    (subject_id, user.auth_provider, identity_id),
                ).fetchone()
                if found:
                    return True
            if subject_type == "external_group":
                found = connection.execute(
                    """
                    SELECT 1 FROM rbac_external_memberships
                    WHERE external_group_id=? AND provider=? AND identity_id=?
                    """,
                    (subject_id, user.auth_provider, identity_id),
                ).fetchone()
                if found:
                    return True
        return False

    def audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._dicts(
                connection.execute(
                    """
                    SELECT * FROM rbac_audit ORDER BY timestamp DESC LIMIT ?
                    """,
                    (min(max(limit, 1), 1000),),
                )
            )


def _resource_matches(source: DecisionSource, resource: Resource) -> bool:
    if source.resource_type not in {"global", "*", resource.resource_type}:
        return False
    if source.resource_id not in {"*", resource.resource_id}:
        return False
    if source.scope in {"", "*"}:
        return True
    return resource.scope == source.scope or resource.scope.startswith(
        source.scope.rstrip("/") + "/"
    )


class PermissionService:
    """Authoritative resolver: explicit deny > allow > default deny."""

    def __init__(
        self,
        repository: PermissionRepository | None = None,
        cache_ttl: float = 5.0,
    ) -> None:
        self.repository = repository or PermissionRepository()
        self.cache_ttl = max(0.0, cache_ttl)
        self._cache: dict[
            tuple[str, str, str],
            tuple[float, list[DecisionSource]],
        ] = {}
        self._lock = threading.RLock()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def sources(self, user: SessionUser) -> list[DecisionSource]:
        key = (
            user.auth_provider,
            user.identity_id or user.username,
            user.username,
        )
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
        sources = self.repository.effective_sources(user)
        with self._lock:
            self._cache[key] = (time.monotonic() + self.cache_ttl, sources)
        return list(sources)

    def explain(
        self,
        user: SessionUser,
        permission: str,
        resource: Resource | None = None,
    ) -> PermissionDecision:
        expected = normalize_permission_id(permission)
        target = resource or Resource()
        matches = [
            source
            for source in self.sources(user)
            if source.permission == expected and _resource_matches(source, target)
        ]
        denies = [source for source in matches if source.effect == "deny"]
        allows = [source for source in matches if source.effect == "allow"]
        if denies:
            return PermissionDecision(
                False,
                expected,
                target,
                denies + allows,
                "explicit deny overrides allow",
            )
        if allows:
            return PermissionDecision(
                True,
                expected,
                target,
                allows,
                "permission granted by effective assignment",
            )
        return PermissionDecision(
            False,
            expected,
            target,
            [],
            "default deny: no effective grant",
        )

    def can(
        self,
        user: SessionUser,
        permission: str,
        resource: Resource | None = None,
    ) -> bool:
        return self.explain(user, permission, resource).allowed

    def authorize(
        self,
        user: SessionUser,
        permission: str,
        resource: Resource | None = None,
    ) -> None:
        decision = self.explain(user, permission, resource)
        if not decision.allowed:
            raise HTTPException(
                403,
                detail={"code": "PERMISSION_REQUIRED", **decision.as_dict()},
            )

    def effective(self, user: SessionUser) -> dict[str, Any]:
        permissions = sorted({source.permission for source in self.sources(user)})
        decisions = [self.explain(user, item).as_dict() for item in permissions]
        return {
            "user": {
                "username": user.username,
                "provider": user.auth_provider,
                "identity_id": user.identity_id or user.username,
            },
            "permissions": decisions,
            "allowed": [
                decision["permission"]
                for decision in decisions
                if decision["result"] == "ALLOW"
            ],
            "denied": [
                decision["permission"]
                for decision in decisions
                if decision["result"] == "DENY"
            ],
        }


_service: PermissionService | None = None
_service_lock = threading.Lock()


def permission_service() -> PermissionService:
    global _service
    with _service_lock:
        if _service is None:
            _service = PermissionService()
        return _service
