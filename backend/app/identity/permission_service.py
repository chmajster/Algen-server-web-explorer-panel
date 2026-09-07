from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
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
            "resource": self.resource.__dict__,
            "reason": self.reason,
            "sources": [source.__dict__ for source in self.sources],
        }


SYSTEM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": set(ALL_PERMISSIONS),
    "Operator": set(ROLE_PERMISSIONS.get("operator", set())),
    "Auditor": set(ROLE_PERMISSIONS.get("auditor", set())),
    "User": set(ROLE_PERMISSIONS.get("user", set())),
    "Read Only": {permission for permission in ALL_PERMISSIONS if permission.endswith((".view", ".read", ".view_own"))},
}

# Compatibility aliases are kept in the central catalog so old modules and the
# new API resolve to the same authorization graph instead of parallel RBACs.
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


class PermissionRepository:
    """Single SQLite store for dynamic RBAC entities.

    The tables live in identity.sqlite3 next to the legacy identity policy
    tables. This is intentionally an in-place migration, not a second RBAC DB.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(get_config().paths.data_dir) / "identity.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS rbac_roles(
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                role_type TEXT NOT NULL CHECK(role_type IN ('system','custom')),
                protected INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
                created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rbac_role_permissions(
                role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                permission TEXT NOT NULL, effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
                resource_type TEXT NOT NULL DEFAULT 'global', resource_id TEXT NOT NULL DEFAULT '*',
                scope TEXT NOT NULL DEFAULT '*', PRIMARY KEY(role_id,permission,effect,resource_type,resource_id,scope)
            );
            CREATE TABLE IF NOT EXISTS rbac_groups(
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'local', external_id TEXT NOT NULL DEFAULT '',
                distinguished_name TEXT NOT NULL DEFAULT '', managed INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rbac_group_members(
                group_id TEXT NOT NULL REFERENCES rbac_groups(id) ON DELETE CASCADE,
                provider TEXT NOT NULL, identity_id TEXT NOT NULL, username TEXT NOT NULL,
                PRIMARY KEY(group_id,provider,identity_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_group_roles(
                group_id TEXT NOT NULL REFERENCES rbac_groups(id) ON DELETE CASCADE,
                role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                PRIMARY KEY(group_id,role_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_user_roles(
                provider TEXT NOT NULL, identity_id TEXT NOT NULL, username TEXT NOT NULL,
                role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                created_at REAL NOT NULL, created_by TEXT NOT NULL,
                PRIMARY KEY(provider,identity_id,role_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_external_groups(
                id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, external_id TEXT NOT NULL,
                distinguished_name TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                parent_ids_json TEXT NOT NULL DEFAULT '[]', last_seen_at REAL NOT NULL DEFAULT 0,
                UNIQUE(provider_id, external_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_external_memberships(
                external_group_id TEXT NOT NULL REFERENCES rbac_external_groups(id) ON DELETE CASCADE,
                provider TEXT NOT NULL, identity_id TEXT NOT NULL, username TEXT NOT NULL,
                direct INTEGER NOT NULL DEFAULT 1, last_seen_at REAL NOT NULL,
                PRIMARY KEY(external_group_id,provider,identity_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_external_group_roles(
                external_group_id TEXT NOT NULL REFERENCES rbac_external_groups(id) ON DELETE CASCADE,
                role_id TEXT NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
                PRIMARY KEY(external_group_id,role_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_policies(
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1, effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
                permission TEXT NOT NULL, resource_type TEXT NOT NULL DEFAULT 'global',
                resource_id TEXT NOT NULL DEFAULT '*', scope TEXT NOT NULL DEFAULT '*',
                conditions_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, created_by TEXT NOT NULL,
                updated_at REAL NOT NULL, updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rbac_policy_subjects(
                policy_id TEXT NOT NULL REFERENCES rbac_policies(id) ON DELETE CASCADE,
                subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
                PRIMARY KEY(policy_id,subject_type,subject_id)
            );
            CREATE TABLE IF NOT EXISTS rbac_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
                target TEXT NOT NULL, before_json TEXT NOT NULL DEFAULT '{}', after_json TEXT NOT NULL DEFAULT '{}',
                timestamp REAL NOT NULL, source_ip TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_rbac_external_members_identity ON rbac_external_memberships(provider,identity_id);
            CREATE INDEX IF NOT EXISTS idx_rbac_group_members_identity ON rbac_group_members(provider,identity_id);
            CREATE INDEX IF NOT EXISTS idx_rbac_audit_timestamp ON rbac_audit(timestamp DESC);
            """)
            now = time.time()
            for name, permissions in SYSTEM_ROLE_PERMISSIONS.items():
                role_id = f"system:{name.casefold().replace(' ', '-')}"
                connection.execute(
                    "INSERT OR IGNORE INTO rbac_roles(id,name,description,active,role_type,protected,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (role_id, name, f"WebNAS system role: {name}", 1, "system", 1, now, "migration", now, "migration"),
                )
                for permission in permissions:
                    connection.execute(
                        "INSERT OR IGNORE INTO rbac_role_permissions(role_id,permission,effect) VALUES(?,?, 'allow')",
                        (role_id, permission),
                    )

    @staticmethod
    def _rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def roles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            roles = self._rows(connection.execute("SELECT * FROM rbac_roles ORDER BY role_type DESC,name"))
            for role in roles:
                role["permissions"] = self._rows(connection.execute(
                    "SELECT permission,effect,resource_type,resource_id,scope FROM rbac_role_permissions WHERE role_id=? ORDER BY permission",
                    (role["id"],),
                ))
            return roles

    def create_role(self, payload: dict[str, Any], actor: str, source_ip: str = "") -> dict[str, Any]:
        role_id = str(uuid.uuid4())
        now = time.time()
        permissions = payload.get("permissions") or []
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO rbac_roles VALUES(?,?,?,?,?,?,?,?,?,?)",
                (role_id, str(payload["name"]).strip(), str(payload.get("description") or ""), int(payload.get("active", True)), "custom", 0, now, actor, now, actor),
            )
            for item in permissions:
                permission = normalize_permission_id(str(item["permission"]))
                connection.execute(
                    "INSERT INTO rbac_role_permissions(role_id,permission,effect,resource_type,resource_id,scope) VALUES(?,?,?,?,?,?)",
                    (role_id, permission, item.get("effect", "allow"), item.get("resource_type", "global"), item.get("resource_id", "*"), item.get("scope", "*")),
                )
            self._audit(connection, actor, "role.create", role_id, {}, payload, source_ip)
        return next(role for role in self.roles() if role["id"] == role_id)

    def update_role(self, role_id: str, payload: dict[str, Any], actor: str, source_ip: str = "") -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            before = connection.execute("SELECT * FROM rbac_roles WHERE id=?", (role_id,)).fetchone()
            if not before:
                raise HTTPException(404, "Role not found")
            if before["protected"] and payload.get("name") not in (None, before["name"]):
                raise HTTPException(409, "System role name is protected")
            now = time.time()
            connection.execute(
                "UPDATE rbac_roles SET name=?,description=?,active=?,updated_at=?,updated_by=? WHERE id=?",
                (payload.get("name", before["name"]), payload.get("description", before["description"]), int(payload.get("active", bool(before["active"]))), now, actor, role_id),
            )
            if "permissions" in payload:
                connection.execute("DELETE FROM rbac_role_permissions WHERE role_id=?", (role_id,))
                for item in payload["permissions"]:
                    connection.execute(
                        "INSERT INTO rbac_role_permissions(role_id,permission,effect,resource_type,resource_id,scope) VALUES(?,?,?,?,?,?)",
                        (role_id, normalize_permission_id(str(item["permission"])), item.get("effect", "allow"), item.get("resource_type", "global"), item.get("resource_id", "*"), item.get("scope", "*")),
                    )
            self._audit(connection, actor, "role.update", role_id, dict(before), payload, source_ip)
        return next(role for role in self.roles() if role["id"] == role_id)

    def delete_role(self, role_id: str, actor: str, source_ip: str = "") -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM rbac_roles WHERE id=?", (role_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Role not found")
            if row["protected"]:
                raise HTTPException(409, "System role is protected")
            connection.execute("DELETE FROM rbac_roles WHERE id=?", (role_id,))
            self._audit(connection, actor, "role.delete", role_id, dict(row), {}, source_ip)

    def assign_user_role(self, user: SessionUser, role_id: str, actor: str, source_ip: str = "") -> None:
        identity_id = user.identity_id or user.username
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO rbac_user_roles(provider,identity_id,username,role_id,created_at,created_by) VALUES(?,?,?,?,?,?)",
                (user.auth_provider, identity_id, user.username, role_id, time.time(), actor),
            )
            self._audit(connection, actor, "assignment.user-role", f"{user.auth_provider}:{identity_id}", {}, {"role_id": role_id}, source_ip)

    def effective_sources(self, user: SessionUser) -> list[DecisionSource]:
        identity_id = user.identity_id or user.username
        result: list[DecisionSource] = []
        with self._connect() as connection:
            role_rows = connection.execute(
                """SELECT rp.*,r.name role_name FROM rbac_user_roles ur JOIN rbac_roles r ON r.id=ur.role_id AND r.active=1
                JOIN rbac_role_permissions rp ON rp.role_id=r.id WHERE ur.provider=? AND ur.identity_id=?""",
                (user.auth_provider, identity_id),
            ).fetchall()
            for row in role_rows:
                result.append(_source(row, "direct-role", row["role_id"], row["role_name"]))
            local_rows = connection.execute(
                """SELECT rp.*,g.id group_id,g.name group_name,r.name role_name FROM rbac_group_members gm
                JOIN rbac_groups g ON g.id=gm.group_id AND g.active=1 JOIN rbac_group_roles gr ON gr.group_id=g.id
                JOIN rbac_roles r ON r.id=gr.role_id AND r.active=1 JOIN rbac_role_permissions rp ON rp.role_id=r.id
                WHERE gm.provider=? AND gm.identity_id=?""",
                (user.auth_provider, identity_id),
            ).fetchall()
            for row in local_rows:
                result.append(_source(row, "local-group", row["group_id"], f"{row['group_name']} -> {row['role_name']}"))
            external_rows = connection.execute(
                """SELECT rp.*,eg.id group_id,eg.name group_name,eg.distinguished_name,r.name role_name
                FROM rbac_external_memberships em JOIN rbac_external_groups eg ON eg.id=em.external_group_id AND eg.status='active'
                JOIN rbac_external_group_roles er ON er.external_group_id=eg.id JOIN rbac_roles r ON r.id=er.role_id AND r.active=1
                JOIN rbac_role_permissions rp ON rp.role_id=r.id WHERE em.provider=? AND em.identity_id=?""",
                (user.auth_provider, identity_id),
            ).fetchall()
            for row in external_rows:
                result.append(_source(row, "ldap-group", row["group_id"], f"{row['group_name']} -> {row['role_name']}", row["distinguished_name"]))
            policy_rows = connection.execute("SELECT * FROM rbac_policies WHERE active=1").fetchall()
            for row in policy_rows:
                subjects = connection.execute("SELECT subject_type,subject_id FROM rbac_policy_subjects WHERE policy_id=?", (row["id"],)).fetchall()
                if self._policy_matches(user, subjects, connection, json.loads(row["conditions_json"] or "{}")):
                    result.append(DecisionSource(row["effect"], row["permission"], "policy", row["id"], row["name"], row["resource_type"], row["resource_id"], row["scope"], "conditional policy"))
        return result

    def _policy_matches(self, user: SessionUser, subjects: Iterable[sqlite3.Row], connection: sqlite3.Connection, conditions: dict[str, Any]) -> bool:
        subject_list = list(subjects)
        if subject_list:
            identity_id = user.identity_id or user.username
            matched = False
            for subject in subject_list:
                if subject["subject_type"] == "user" and subject["subject_id"] in {identity_id, user.username}:
                    matched = True
                elif subject["subject_type"] == "provider" and subject["subject_id"] == user.auth_provider:
                    matched = True
                elif subject["subject_type"] == "group":
                    found = connection.execute("SELECT 1 FROM rbac_group_members WHERE group_id=? AND provider=? AND identity_id=?", (subject["subject_id"], user.auth_provider, identity_id)).fetchone()
                    matched = matched or bool(found)
                elif subject["subject_type"] == "external_group":
                    found = connection.execute("SELECT 1 FROM rbac_external_memberships WHERE external_group_id=? AND provider=? AND identity_id=?", (subject["subject_id"], user.auth_provider, identity_id)).fetchone()
                    matched = matched or bool(found)
            if not matched:
                return False
        # MFA is intentionally evaluated from trusted session context supplied by
        # callers; absence never satisfies an MFA-required policy.
        if conditions.get("auth_provider") and conditions["auth_provider"] != user.auth_provider:
            return False
        return True

    def audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._rows(connection.execute("SELECT * FROM rbac_audit ORDER BY timestamp DESC LIMIT ?", (min(max(limit, 1), 1000),)))

    @staticmethod
    def _audit(connection: sqlite3.Connection, actor: str, action: str, target: str, before: dict[str, Any], after: dict[str, Any], source_ip: str) -> None:
        connection.execute(
            "INSERT INTO rbac_audit(actor,action,target,before_json,after_json,timestamp,source_ip) VALUES(?,?,?,?,?,?,?)",
            (actor, action, target, json.dumps(before, default=str, sort_keys=True), json.dumps(after, default=str, sort_keys=True), time.time(), source_ip),
        )


def _source(row: sqlite3.Row, source_type: str, source_id: str, source_name: str, reason: str = "") -> DecisionSource:
    return DecisionSource(row["effect"], row["permission"], source_type, source_id, source_name, row["resource_type"], row["resource_id"], row["scope"], reason)


def normalize_permission_id(permission: str) -> str:
    permission = permission.strip()
    permission = PERMISSION_ALIASES.get(permission, permission)
    if permission not in ALL_PERMISSIONS:
        raise HTTPException(422, f"Unknown permission: {permission}")
    return permission


def _resource_matches(source: DecisionSource, resource: Resource) -> bool:
    if source.resource_type not in {"global", "*", resource.resource_type}:
        return False
    if source.resource_id not in {"*", resource.resource_id}:
        return False
    if source.scope in {"", "*"}:
        return True
    return resource.scope == source.scope or resource.scope.startswith(source.scope.rstrip("/") + "/")


class PermissionService:
    """Authoritative RBAC resolver. Deny overrides allow; no match is deny."""

    def __init__(self, repository: PermissionRepository | None = None) -> None:
        self.repository = repository or PermissionRepository()
        self._cache: dict[tuple[str, str, str], tuple[float, list[DecisionSource]]] = {}
        self._lock = threading.RLock()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def sources(self, user: SessionUser) -> list[DecisionSource]:
        key = (user.auth_provider, user.identity_id or user.username, user.username)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
        sources = self.repository.effective_sources(user)
        with self._lock:
            self._cache[key] = (time.monotonic() + 5.0, sources)
        return list(sources)

    def explain(self, user: SessionUser, permission: str, resource: Resource | None = None) -> PermissionDecision:
        expected = normalize_permission_id(permission)
        target = resource or Resource()
        matches = [source for source in self.sources(user) if source.permission == expected and _resource_matches(source, target)]
        denies = [source for source in matches if source.effect == "deny"]
        allows = [source for source in matches if source.effect == "allow"]
        if denies:
            return PermissionDecision(False, expected, target, denies + allows, "explicit deny overrides allow")
        if allows:
            return PermissionDecision(True, expected, target, allows, "permission granted by effective assignment")
        return PermissionDecision(False, expected, target, [], "default deny: no effective grant")

    def can(self, user: SessionUser, permission: str, resource: Resource | None = None) -> bool:
        return self.explain(user, permission, resource).allowed

    def authorize(self, user: SessionUser, permission: str, resource: Resource | None = None) -> None:
        decision = self.explain(user, permission, resource)
        if not decision.allowed:
            raise HTTPException(403, detail={"code": "PERMISSION_REQUIRED", **decision.as_dict()})

    def effective(self, user: SessionUser) -> dict[str, Any]:
        sources = self.sources(user)
        permissions = sorted({source.permission for source in sources})
        decisions = [self.explain(user, permission).as_dict() for permission in permissions]
        return {
            "user": {"username": user.username, "provider": user.auth_provider, "identity_id": user.identity_id or user.username},
            "permissions": decisions,
            "allowed": sorted(item["permission"] for item in decisions if item["result"] == "ALLOW"),
            "denied": sorted(item["permission"] for item in decisions if item["result"] == "DENY"),
        }


_service: PermissionService | None = None
_service_lock = threading.Lock()


def permission_service() -> PermissionService:
    global _service
    with _service_lock:
        if _service is None:
            _service = PermissionService()
        return _service
