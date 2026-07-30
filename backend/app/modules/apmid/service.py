from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from types import TracebackType
from typing import Any

from fastapi import HTTPException
from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...config import get_config
from ...identity import linux_accounts
from ...identity.permissions import Permission, has_permission
from .models import ApmidInput, ApmidMemberCreate, ApmidPermissionUpdate, ApmidResourcePermission, ApmidRole


SCHEMA_VERSION = 1
ROLE_PERMISSIONS: dict[ApmidRole, set[ApmidResourcePermission]] = {
    ApmidRole.viewer: {ApmidResourcePermission.view},
    ApmidRole.operator: {ApmidResourcePermission.view, ApmidResourcePermission.members_view},
    ApmidRole.manager: {
        ApmidResourcePermission.view, ApmidResourcePermission.update, ApmidResourcePermission.members_view,
        ApmidResourcePermission.members_manage, ApmidResourcePermission.permissions_view,
        ApmidResourcePermission.audit_view,
    },
    ApmidRole.owner: set(ApmidResourcePermission),
}
GLOBAL_RESOURCE_PERMISSION: dict[ApmidResourcePermission, Permission] = {
    ApmidResourcePermission.view: Permission.APMID_VIEW,
    ApmidResourcePermission.update: Permission.APMID_UPDATE,
    ApmidResourcePermission.members_view: Permission.APMID_MEMBERS_VIEW,
    ApmidResourcePermission.members_manage: Permission.APMID_MEMBERS_MANAGE,
    ApmidResourcePermission.permissions_view: Permission.APMID_PERMISSIONS_VIEW,
    ApmidResourcePermission.permissions_manage: Permission.APMID_PERMISSIONS_MANAGE,
    ApmidResourcePermission.audit_view: Permission.APMID_AUDIT_VIEW,
    ApmidResourcePermission.delete: Permission.APMID_DELETE,
}


class ApmidConflictError(ValueError):
    pass


class ApmidNotFoundError(KeyError):
    pass


class ApmidInUseError(RuntimeError):
    def __init__(self, usages: list[dict[str, Any]]) -> None:
        super().__init__("APMID is in use")
        self.usages = usages


class LastOwnerError(RuntimeError):
    pass


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> bool | None:  # type: ignore[override]
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


class ApmidService:
    """Authoritative APMID registry and resource authorization boundary."""

    def __init__(self, path: Path | None = None, legacy_path: Path | None = None) -> None:
        root = (path.parent if path else Path(get_config().paths.data_dir) / "apmid").resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.root = root
        self.path = path or root / "apmid.sqlite3"
        self.backups_root = root / "backups"
        self.migrations_root = root / "migrations"
        for directory in (self.backups_root, self.migrations_root):
            directory.mkdir(exist_ok=True)
            os.chmod(directory, 0o700)
        self.legacy_path = legacy_path or root.parent / "hosts-manager" / "hosts.sqlite3"
        self._lock = threading.RLock()
        self._initialize()
        self.migrate_hosts_manager()

    def connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
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
                CREATE TABLE IF NOT EXISTS schema_version(
                    version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migration_markers(
                    source TEXT PRIMARY KEY, backup_path TEXT NOT NULL, migrated_at REAL NOT NULL,
                    record_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS apmids(
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                    business_owner TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_apmid_code_ci ON apmids(code COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_apmid_active_updated ON apmids(active,updated_at DESC);
                CREATE TABLE IF NOT EXISTS apmid_members(
                    apmid_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('viewer','operator','manager','owner')),
                    assigned_at REAL NOT NULL,
                    assigned_by TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL,
                    PRIMARY KEY(apmid_id,username),
                    FOREIGN KEY(apmid_id) REFERENCES apmids(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_apmid_members_user ON apmid_members(username,apmid_id);
                CREATE TABLE IF NOT EXISTS apmid_member_permissions(
                    apmid_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    permission TEXT NOT NULL CHECK(permission IN ('view','update','members.view','members.manage','permissions.view','permissions.manage','audit.view','delete')),
                    effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL,
                    PRIMARY KEY(apmid_id,username,permission),
                    FOREIGN KEY(apmid_id,username) REFERENCES apmid_members(apmid_id,username) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_apmid_permissions_member ON apmid_member_permissions(username,apmid_id);
                CREATE TABLE IF NOT EXISTS apmid_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apmid_id TEXT,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_apmid_history_item ON apmid_history(apmid_id,created_at DESC,id DESC);
                CREATE INDEX IF NOT EXISTS idx_apmid_history_time ON apmid_history(created_at DESC,id DESC);
                """
            )
            connection.execute("INSERT OR IGNORE INTO schema_version(version,applied_at) VALUES(?,?)", (SCHEMA_VERSION, now))
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        os.chmod(self.path, 0o600)

    @staticmethod
    def _item(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        if "active" in result:
            result["active"] = bool(result["active"])
        return result

    def migrate_hosts_manager(self) -> dict[str, Any]:
        """Copy legacy APMIDs once without deleting or rewriting rollback data."""
        if not self.legacy_path.is_file() or self.legacy_path.resolve() == self.path.resolve():
            return {"migrated": 0}
        with self.connect() as target:
            if target.execute("SELECT 1 FROM migration_markers WHERE source='hosts-manager-v1'").fetchone():
                return {"migrated": 0, "already_applied": True}
        source = sqlite3.connect(self.legacy_path)
        source.row_factory = sqlite3.Row
        try:
            tables = {str(row[0]) for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "apmids" not in tables:
                return {"migrated": 0}
            backup = self.migrations_root / "hosts-manager-apmids-v1.sqlite3.bak"
            if not backup.exists():
                with sqlite3.connect(backup) as destination:
                    source.backup(destination)
                os.chmod(backup, 0o600)
            rows = source.execute("SELECT id,code,description,active,created_at,updated_at,created_by,updated_by FROM apmids").fetchall()
            with self._lock, self.connect() as target:
                target.execute("BEGIN IMMEDIATE")
                for row in rows:
                    target.execute(
                        """INSERT OR IGNORE INTO apmids(
                           id,code,name,description,active,business_owner,created_at,updated_at,created_by,updated_by
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            row["id"], str(row["code"]).strip().upper(), str(row["code"]).strip().upper(),
                            row["description"], row["active"], None, row["created_at"], row["updated_at"],
                            row["created_by"], row["updated_by"],
                        ),
                    )
                target.execute(
                    "INSERT INTO migration_markers(source,backup_path,migrated_at,record_count) VALUES(?,?,?,?)",
                    ("hosts-manager-v1", str(backup), time.time(), len(rows)),
                )
            return {"migrated": len(rows), "backup_path": str(backup)}
        finally:
            source.close()

    def _history(self, connection: sqlite3.Connection, apmid_id: str | None, action: str, actor: str, target: str = "", details: dict[str, Any] | None = None, *, activity_status: ActivityStatus = ActivityStatus.success) -> None:
        safe = details or {}
        connection.execute(
            "INSERT INTO apmid_history(apmid_id,action,actor,target,details_json,created_at) VALUES(?,?,?,?,?,?)",
            (apmid_id, action, actor, target[:256], json.dumps(safe, separators=(",", ":")), time.time()),
        )
        record_activity(ActivityCategory.module, action, actor, target=target or apmid_id or "apmid", status=activity_status, details=safe, source="apmid")

    def get(self, apmid_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT apmids.*,(SELECT COUNT(*) FROM apmid_members WHERE apmid_id=apmids.id) AS member_count
                   FROM apmids WHERE id=?""", (apmid_id,),
            ).fetchone()
        return self._item(row) if row else None

    def active(self, apmid_id: str) -> dict[str, Any] | None:
        item = self.get(apmid_id)
        return item if item and item["active"] else None

    def all_for_hosts(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM apmids ORDER BY code COLLATE NOCASE").fetchall()
        return [self._item(row) for row in rows]

    def list_items(self, username: str, *, page: int = 1, page_size: int = 50, search: str = "", status: str = "", sort: str = "code", direction: str = "asc") -> dict[str, Any]:
        allowed_sort = {"code": "a.code", "name": "a.name", "status": "a.active", "updated_at": "a.updated_at"}
        order = allowed_sort.get(sort, "a.code")
        direction_sql = "DESC" if direction == "desc" else "ASC"
        global_view = has_permission(username, Permission.APMID_VIEW)
        clauses = ["1=1"]
        values: list[Any] = []
        if not global_view:
            clauses.append("EXISTS(SELECT 1 FROM apmid_members m WHERE m.apmid_id=a.id AND m.username=?)")
            values.append(username)
        if search.strip():
            clauses.append("(a.code LIKE ? ESCAPE '\\' OR a.name LIKE ? ESCAPE '\\' OR a.description LIKE ? ESCAPE '\\')")
            escaped_search = search.strip().replace("%", "\\%").replace("_", "\\_")
            needle = f"%{escaped_search}%"
            values.extend([needle, needle, needle])
        if status in {"active", "inactive"}:
            clauses.append("a.active=?")
            values.append(1 if status == "active" else 0)
        where = " AND ".join(clauses)
        with self.connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM apmids a WHERE {where}", values).fetchone()[0])
            rows = connection.execute(
                f"""SELECT a.*,(SELECT COUNT(*) FROM apmid_members m WHERE m.apmid_id=a.id) AS member_count
                    FROM apmids a WHERE {where} ORDER BY {order} {direction_sql},a.id LIMIT ? OFFSET ?""",
                (*values, page_size, (page - 1) * page_size),
            ).fetchall()
        items = [self._item(row) for row in rows]
        for item in items:
            item["related_count"] = sum(int(usage["count"]) for usage in self.usages(str(item["id"]), include_managed_groups=True))
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def create(self, payload: ApmidInput, actor: str) -> dict[str, Any]:
        now, item_id = time.time(), secrets.token_hex(16)
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO apmids(id,code,name,description,active,business_owner,created_at,updated_at,created_by,updated_by)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (item_id, payload.code, payload.name, payload.description, int(payload.active), payload.business_owner, now, now, actor, actor),
                )
            except sqlite3.IntegrityError as error:
                raise ApmidConflictError("APMID code already exists") from error
            connection.execute(
                "INSERT INTO apmid_members(apmid_id,username,role,assigned_at,assigned_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)",
                (item_id, actor, ApmidRole.owner.value, now, actor, now, actor),
            )
            self._history(connection, item_id, "apmid_create", actor, item_id, {"code": payload.code, "active": payload.active})
        return self.get(item_id) or {}

    def update(self, apmid_id: str, payload: ApmidInput, actor: str) -> dict[str, Any]:
        previous = self.get(apmid_id)
        if not previous:
            raise ApmidNotFoundError(apmid_id)
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """UPDATE apmids SET code=?,name=?,description=?,active=?,business_owner=?,updated_at=?,updated_by=? WHERE id=?""",
                    (payload.code, payload.name, payload.description, int(payload.active), payload.business_owner, time.time(), actor, apmid_id),
                ).rowcount
            except sqlite3.IntegrityError as error:
                raise ApmidConflictError("APMID code already exists") from error
            if not changed:
                raise ApmidNotFoundError(apmid_id)
            action = "apmid_status_change" if bool(previous["active"]) != payload.active else "apmid_update"
            self._history(connection, apmid_id, action, actor, apmid_id, {"code": payload.code, "active": payload.active})
        return self.get(apmid_id) or {}

    def usages(self, apmid_id: str, *, include_managed_groups: bool = False) -> list[dict[str, Any]]:
        if not self.legacy_path.is_file():
            return []
        with sqlite3.connect(self.legacy_path) as connection:
            connection.row_factory = sqlite3.Row
            tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            usages: list[dict[str, Any]] = []
            if "enrollment_tokens" in tables:
                count = int(connection.execute("SELECT COUNT(*) FROM enrollment_tokens WHERE apmid_id=?", (apmid_id,)).fetchone()[0])
                if count:
                    usages.append({"module": "hosts-manager", "resource": "enrollment_tokens", "count": count})
            if {"apmid_environment_groups", "memberships"} <= tables:
                if include_managed_groups:
                    group_count = int(connection.execute(
                        "SELECT COUNT(*) FROM apmid_environment_groups WHERE apmid_id=?", (apmid_id,),
                    ).fetchone()[0])
                    if group_count:
                        usages.append({"module": "hosts-manager", "resource": "managed_groups", "count": group_count})
                count = int(connection.execute(
                    """SELECT COUNT(*) FROM memberships m JOIN apmid_environment_groups r ON r.group_id=m.group_id
                       WHERE r.apmid_id=?""", (apmid_id,),
                ).fetchone()[0])
                if count:
                    usages.append({"module": "hosts-manager", "resource": "hosts", "count": count})
        return usages

    def delete(self, apmid_id: str, actor: str) -> None:
        if not self.get(apmid_id):
            raise ApmidNotFoundError(apmid_id)
        usages = self.usages(apmid_id)
        if usages:
            with self.connect() as connection:
                self._history(connection, apmid_id, "apmid_delete_blocked", actor, apmid_id, {"usages": usages}, activity_status=ActivityStatus.failure)
            raise ApmidInUseError(usages)
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._history(connection, apmid_id, "apmid_delete", actor, apmid_id)
            connection.execute("DELETE FROM apmids WHERE id=?", (apmid_id,))

    def effective_permissions(self, apmid_id: str, username: str) -> dict[str, Any]:
        with self.connect() as connection:
            member = connection.execute("SELECT * FROM apmid_members WHERE apmid_id=? AND username=?", (apmid_id, username)).fetchone()
            overrides = connection.execute(
                "SELECT permission,effect FROM apmid_member_permissions WHERE apmid_id=? AND username=?", (apmid_id, username),
            ).fetchall() if member else []
        role = ApmidRole(str(member["role"])) if member else None
        role_values = ROLE_PERMISSIONS[role] if role else set()
        allows = {ApmidResourcePermission(str(row["permission"])) for row in overrides if row["effect"] == "allow"}
        denies = {ApmidResourcePermission(str(row["permission"])) for row in overrides if row["effect"] == "deny"}
        global_values = {
            permission for permission, global_permission in GLOBAL_RESOURCE_PERMISSION.items()
            if has_permission(username, global_permission)
        }
        effective = ((role_values | allows) - denies) | global_values
        sources = {
            permission.value: "global" if permission in global_values else "deny" if permission in denies else "allow" if permission in allows else f"role:{role.value}" if permission in role_values and role else "none"
            for permission in ApmidResourcePermission
        }
        return {
            "username": username, "role": role.value if role else None,
            "allow": sorted(item.value for item in allows), "deny": sorted(item.value for item in denies),
            "effective": sorted(item.value for item in effective), "sources": sources,
        }

    def can(self, username: str, apmid_id: str, permission: ApmidResourcePermission) -> bool:
        if has_permission(username, GLOBAL_RESOURCE_PERMISSION[permission]):
            return True
        return permission.value in self.effective_permissions(apmid_id, username)["effective"]

    def has_access(self, username: str) -> bool:
        if has_permission(username, Permission.APMID_VIEW):
            return True
        with self.connect() as connection:
            rows = connection.execute("SELECT apmid_id FROM apmid_members WHERE username=?", (username,)).fetchall()
        return any(self.can(username, str(row["apmid_id"]), ApmidResourcePermission.view) for row in rows)

    def members(self, apmid_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM apmid_members WHERE apmid_id=? ORDER BY username COLLATE NOCASE", (apmid_id,)).fetchall()
        result = []
        for row in rows:
            username = str(row["username"])
            try:
                identity = linux_accounts.user_record(username)
                account_status = "locked" if identity.get("locked") else "active"
            except (KeyError, HTTPException):
                account_status = "missing"
            result.append(self._item(row) | {"status": account_status, "permissions": self.effective_permissions(apmid_id, username)})
        return result

    @staticmethod
    def _validate_user(username: str) -> None:
        try:
            record = linux_accounts.user_record(username)
        except KeyError as error:
            raise ApmidNotFoundError(username) from error
        if record["is_system"] or not record["manageable"]:
            raise PermissionError("Technical or protected users cannot be assigned")

    def add_members(self, apmid_id: str, payload: ApmidMemberCreate, actor: str) -> list[dict[str, Any]]:
        if not self.get(apmid_id):
            raise ApmidNotFoundError(apmid_id)
        for username in payload.usernames:
            self._validate_user(username)
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executemany(
                    "INSERT INTO apmid_members(apmid_id,username,role,assigned_at,assigned_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)",
                    [(apmid_id, username, payload.role.value, now, actor, now, actor) for username in payload.usernames],
                )
            except sqlite3.IntegrityError as error:
                raise ApmidConflictError("User is already assigned to this APMID") from error
            self._history(connection, apmid_id, "apmid_members_add", actor, ",".join(payload.usernames), {"role": payload.role.value, "count": len(payload.usernames)})
        return self.members(apmid_id)

    def _effective_owner_count(self, connection: sqlite3.Connection, apmid_id: str, excluding: str = "") -> int:
        owners = connection.execute("SELECT username FROM apmid_members WHERE apmid_id=? AND role='owner' AND username<>?", (apmid_id, excluding)).fetchall()
        count = 0
        for row in owners:
            override = connection.execute(
                "SELECT effect FROM apmid_member_permissions WHERE apmid_id=? AND username=? AND permission=?",
                (apmid_id, row["username"], ApmidResourcePermission.permissions_manage.value),
            ).fetchone()
            if not override or override["effect"] != "deny":
                count += 1
        return count

    def update_member(self, apmid_id: str, username: str, role: ApmidRole, actor: str) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT role FROM apmid_members WHERE apmid_id=? AND username=?", (apmid_id, username)).fetchone()
            if not current:
                raise ApmidNotFoundError(username)
            if current["role"] == "owner" and role != ApmidRole.owner and self._effective_owner_count(connection, apmid_id, username) == 0:
                raise LastOwnerError("The last effective owner cannot be demoted")
            connection.execute("UPDATE apmid_members SET role=?,updated_at=?,updated_by=? WHERE apmid_id=? AND username=?", (role.value, time.time(), actor, apmid_id, username))
            self._history(connection, apmid_id, "apmid_member_role", actor, username, {"role": role.value})
        return self.members(apmid_id)

    def remove_member(self, apmid_id: str, username: str, actor: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            member = connection.execute("SELECT role FROM apmid_members WHERE apmid_id=? AND username=?", (apmid_id, username)).fetchone()
            if not member:
                raise ApmidNotFoundError(username)
            if member["role"] == "owner" and self._effective_owner_count(connection, apmid_id, username) == 0:
                raise LastOwnerError("The last effective owner cannot be removed")
            connection.execute("DELETE FROM apmid_members WHERE apmid_id=? AND username=?", (apmid_id, username))
            self._history(connection, apmid_id, "apmid_member_remove", actor, username)

    def permissions(self, apmid_id: str) -> list[dict[str, Any]]:
        return [self.effective_permissions(apmid_id, str(member["username"])) for member in self.members(apmid_id)]

    def set_permissions(self, apmid_id: str, username: str, payload: ApmidPermissionUpdate, actor: str) -> dict[str, Any]:
        if set(payload.allow) & set(payload.deny):
            raise ApmidConflictError("A permission cannot be both allowed and denied")
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            member = connection.execute("SELECT role FROM apmid_members WHERE apmid_id=? AND username=?", (apmid_id, username)).fetchone()
            if not member:
                raise ApmidNotFoundError(username)
            connection.execute("DELETE FROM apmid_member_permissions WHERE apmid_id=? AND username=?", (apmid_id, username))
            now = time.time()
            connection.executemany(
                "INSERT INTO apmid_member_permissions(apmid_id,username,permission,effect,updated_at,updated_by) VALUES(?,?,?,?,?,?)",
                [(apmid_id, username, item.value, "allow", now, actor) for item in payload.allow]
                + [(apmid_id, username, item.value, "deny", now, actor) for item in payload.deny],
            )
            if member["role"] == "owner" and self._effective_owner_count(connection, apmid_id) == 0:
                raise LastOwnerError("At least one owner must keep effective owner permissions")
            self._history(connection, apmid_id, "apmid_permissions_update", actor, username, {"allow": [item.value for item in payload.allow], "deny": [item.value for item in payload.deny]})
        return self.effective_permissions(apmid_id, username)

    def reset_permissions(self, apmid_id: str, username: str, actor: str) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM apmid_members WHERE apmid_id=? AND username=?", (apmid_id, username)).fetchone():
                raise ApmidNotFoundError(username)
            connection.execute("DELETE FROM apmid_member_permissions WHERE apmid_id=? AND username=?", (apmid_id, username))
            self._history(connection, apmid_id, "apmid_permissions_reset", actor, username)
        return self.effective_permissions(apmid_id, username)

    def history(self, username: str, apmid_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if apmid_id:
                rows = connection.execute("SELECT * FROM apmid_history WHERE apmid_id=? ORDER BY created_at DESC,id DESC LIMIT ?", (apmid_id, limit)).fetchall()
            elif has_permission(username, Permission.APMID_AUDIT_VIEW):
                rows = connection.execute("SELECT * FROM apmid_history ORDER BY created_at DESC,id DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = connection.execute(
                    """SELECT h.* FROM apmid_history h WHERE EXISTS(
                       SELECT 1 FROM apmid_members m WHERE m.apmid_id=h.apmid_id AND m.username=?
                    ) ORDER BY h.created_at DESC,h.id DESC LIMIT ?""", (username, limit),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json"))
            except (ValueError, TypeError):
                item["details"] = {}
            result.append(item)
        return result

    def dashboard(self, username: str) -> dict[str, Any]:
        listing = self.list_items(username, page_size=500)
        items = listing["items"]
        ids = {str(item["id"]) for item in items}
        with self.connect() as connection:
            members = int(connection.execute(
                f"SELECT COUNT(*) FROM apmid_members WHERE apmid_id IN ({','.join('?' for _ in ids)})", tuple(ids)
            ).fetchone()[0]) if ids else 0
        return {
            "total": len(items), "active": sum(bool(item["active"]) for item in items),
            "members": members, "without_owner": sum(not item.get("business_owner") for item in items),
            "recent": self.history(username, limit=10),
        }

    def record_event(self, action: str, actor: str, target: str = "", details: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            self._history(connection, None, action, actor, target, details)

    def create_backup(self, actor: str, description: str = "") -> dict[str, Any]:
        backup_id = f"apmid-{int(time.time())}-{secrets.token_hex(4)}"
        target = self.backups_root / f"{backup_id}.sqlite3"
        with self._lock, self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        os.chmod(target, 0o600)
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = {
            "id": backup_id, "schema_version": SCHEMA_VERSION, "created_at": time.time(),
            "created_by": actor, "description": description, "sha256": checksum, "database": target.name,
        }
        manifest_path = self.backups_root / f"{backup_id}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        with self.connect() as connection:
            self._history(connection, None, "apmid_backup", actor, backup_id, {"sha256": checksum})
        return manifest

    def list_backups(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.backups_root.glob("apmid-*.json"), reverse=True):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return result

    def restore(self, backup_id: str, actor: str, confirmation: str) -> dict[str, Any]:
        if confirmation != "APMID":
            raise ValueError("Exact confirmation APMID is required")
        manifest_path = self.backups_root / f"{backup_id}.json"
        if not manifest_path.is_file():
            raise ApmidNotFoundError(backup_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = self.backups_root / str(manifest["database"])
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("Backup checksum verification failed")
        with sqlite3.connect(source) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup SQLite integrity check failed")
            backup_ids = {str(row[0]) for row in check.execute("SELECT id FROM apmids")}
        required_ids: set[str] = set()
        if self.legacy_path.is_file():
            with sqlite3.connect(self.legacy_path) as hosts:
                tables = {str(row[0]) for row in hosts.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "enrollment_tokens" in tables:
                    required_ids.update(str(row[0]) for row in hosts.execute("SELECT DISTINCT apmid_id FROM enrollment_tokens WHERE apmid_id IS NOT NULL"))
                if "apmid_environment_groups" in tables:
                    required_ids.update(str(row[0]) for row in hosts.execute("SELECT DISTINCT apmid_id FROM apmid_environment_groups"))
        missing_references = sorted(required_ids - backup_ids)
        if missing_references:
            raise ValueError(f"Backup would break Hosts Manager references: {', '.join(missing_references[:20])}")
        safety = self.create_backup(actor, "Automatic safety backup before restore")
        temporary = self.root / f".restore-{secrets.token_hex(8)}.sqlite3"
        shutil.copy2(source, temporary)
        os.chmod(temporary, 0o600)
        with self._lock:
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{self.path}{suffix}")
                if sidecar.parent == self.root and sidecar.exists():
                    sidecar.unlink()
            os.replace(temporary, self.path)
            self._initialize()
        with self.connect() as connection:
            self._history(connection, None, "apmid_restore", actor, backup_id, {"safety_backup": safety["id"]})
        return {"ok": True, "backup_id": backup_id, "safety_backup": safety["id"]}


@lru_cache
def _service() -> ApmidService:
    return ApmidService()


def service() -> ApmidService:
    instance = _service()
    if not instance.path.is_file():
        instance._initialize()
        instance.migrate_hosts_manager()
    return instance
