from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_config
from .models import GroupPolicy, PermissionChange, UserPolicy


SCHEMA_VERSION = 1


class IdentityRepository:
    def __init__(self, path: Path, *, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path or path.with_name("rbac.json")
        self._lock = threading.RLock()
        self._initialize()
        from .migration import migrate_legacy_rbac

        migrate_legacy_rbac(self, self.legacy_path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL, applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migrations (
                    name TEXT PRIMARY KEY, applied_at REAL NOT NULL, details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS user_policies (
                    username TEXT PRIMARY KEY, role TEXT NOT NULL, allow_json TEXT NOT NULL DEFAULT '[]', deny_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS group_policies (
                    groupname TEXT PRIMARY KEY, allow_json TEXT NOT NULL DEFAULT '[]', deny_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS permission_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, actor TEXT NOT NULL,
                    subject_type TEXT NOT NULL, subject TEXT NOT NULL, action TEXT NOT NULL,
                    previous_json TEXT NOT NULL DEFAULT '{}', current_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'success', error_code TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_permission_changes_time ON permission_changes(created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_permission_changes_subject ON permission_changes(subject_type, subject, created_at DESC);
                """
            )
            current = connection.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1").fetchone()
            if not current:
                connection.execute("INSERT INTO schema_version(version,applied_at) VALUES (?,?)", (SCHEMA_VERSION, time.time()))
            elif int(current["version"]) > SCHEMA_VERSION:
                raise RuntimeError("Identity policy database was created by a newer WebNAS version")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _json(value: str) -> list[str]:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @classmethod
    def _user(cls, row: sqlite3.Row) -> UserPolicy:
        return UserPolicy(username=row["username"], role=row["role"], allow=cls._json(row["allow_json"]), deny=cls._json(row["deny_json"]), created_at=row["created_at"], updated_at=row["updated_at"], updated_by=row["updated_by"])

    @classmethod
    def _group(cls, row: sqlite3.Row) -> GroupPolicy:
        return GroupPolicy(groupname=row["groupname"], allow=cls._json(row["allow_json"]), deny=cls._json(row["deny_json"]), created_at=row["created_at"], updated_at=row["updated_at"], updated_by=row["updated_by"])

    def user_policy(self, username: str) -> UserPolicy | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM user_policies WHERE username=?", (username,)).fetchone()
        return self._user(row) if row else None

    def user_policies(self) -> dict[str, UserPolicy]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM user_policies ORDER BY username").fetchall()
        return {row["username"]: self._user(row) for row in rows}

    def group_policy(self, groupname: str) -> GroupPolicy | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM group_policies WHERE groupname=?", (groupname,)).fetchone()
        return self._group(row) if row else None

    def group_policies(self) -> dict[str, GroupPolicy]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM group_policies ORDER BY groupname").fetchall()
        return {row["groupname"]: self._group(row) for row in rows}

    @staticmethod
    def _change(connection: sqlite3.Connection, actor: str, subject_type: str, subject: str, action: str, previous: dict[str, Any], current: dict[str, Any], *, status: str = "success", error_code: str = "") -> None:
        connection.execute(
            "INSERT INTO permission_changes(created_at,actor,subject_type,subject,action,previous_json,current_json,status,error_code) VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), actor, subject_type, subject, action, json.dumps(previous, ensure_ascii=False), json.dumps(current, ensure_ascii=False), status, error_code),
        )

    def save_user_policy(self, policy: UserPolicy, actor: str, *, action: str = "policy_update") -> UserPolicy:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM user_policies WHERE username=?", (policy.username,)).fetchone()
            previous = self._user(row).model_dump(mode="json") if row else {}
            created_at = float(row["created_at"]) if row else now
            connection.execute(
                """INSERT INTO user_policies(username,role,allow_json,deny_json,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET role=excluded.role,allow_json=excluded.allow_json,deny_json=excluded.deny_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (policy.username, policy.role.value, json.dumps(policy.allow), json.dumps(policy.deny), created_at, now, actor),
            )
            current = {**policy.model_dump(mode="json"), "created_at": created_at, "updated_at": now, "updated_by": actor}
            self._change(connection, actor, "user", policy.username, action, previous, current)
        return self.user_policy(policy.username) or policy

    def delete_user_policy(self, username: str, actor: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM user_policies WHERE username=?", (username,)).fetchone()
            previous = self._user(row).model_dump(mode="json") if row else {}
            connection.execute("DELETE FROM user_policies WHERE username=?", (username,))
            self._change(connection, actor, "user", username, "policy_delete", previous, {})

    def rename_user_policy(self, old: str, new: str, actor: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM user_policies WHERE username=?", (old,)).fetchone()
            if not row:
                return
            if connection.execute("SELECT 1 FROM user_policies WHERE username=?", (new,)).fetchone():
                raise ValueError("target user policy already exists")
            previous = self._user(row).model_dump(mode="json")
            connection.execute("UPDATE user_policies SET username=?,updated_at=?,updated_by=? WHERE username=?", (new, time.time(), actor, old))
            self._change(connection, actor, "user", new, "rename", previous, {**previous, "username": new})

    def save_group_policy(self, policy: GroupPolicy, actor: str, *, action: str = "policy_update") -> GroupPolicy:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM group_policies WHERE groupname=?", (policy.groupname,)).fetchone()
            previous = self._group(row).model_dump(mode="json") if row else {}
            created_at = float(row["created_at"]) if row else now
            connection.execute(
                """INSERT INTO group_policies(groupname,allow_json,deny_json,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?)
                ON CONFLICT(groupname) DO UPDATE SET allow_json=excluded.allow_json,deny_json=excluded.deny_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (policy.groupname, json.dumps(policy.allow), json.dumps(policy.deny), created_at, now, actor),
            )
            current = {**policy.model_dump(mode="json"), "created_at": created_at, "updated_at": now, "updated_by": actor}
            self._change(connection, actor, "group", policy.groupname, action, previous, current)
        return self.group_policy(policy.groupname) or policy

    def delete_group_policy(self, groupname: str, actor: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM group_policies WHERE groupname=?", (groupname,)).fetchone()
            previous = self._group(row).model_dump(mode="json") if row else {}
            connection.execute("DELETE FROM group_policies WHERE groupname=?", (groupname,))
            self._change(connection, actor, "group", groupname, "policy_delete", previous, {})

    def rename_group_policy(self, old: str, new: str, actor: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM group_policies WHERE groupname=?", (old,)).fetchone()
            if not row:
                return
            if connection.execute("SELECT 1 FROM group_policies WHERE groupname=?", (new,)).fetchone():
                raise ValueError("target group policy already exists")
            previous = self._group(row).model_dump(mode="json")
            connection.execute("UPDATE group_policies SET groupname=?,updated_at=?,updated_by=? WHERE groupname=?", (new, time.time(), actor, old))
            self._change(connection, actor, "group", new, "rename", previous, {**previous, "groupname": new})

    def migration_applied(self, name: str) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM migrations WHERE name=?", (name,)).fetchone() is not None

    def import_legacy(self, policies: list[UserPolicy], details: dict[str, Any]) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM migrations WHERE name='rbac-json-v1'").fetchone():
                return
            now = time.time()
            for policy in policies:
                connection.execute(
                    "INSERT OR IGNORE INTO user_policies(username,role,allow_json,deny_json,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?,?)",
                    (policy.username, policy.role.value, json.dumps(policy.allow), json.dumps(policy.deny), now, now, "migration"),
                )
            connection.execute("INSERT INTO migrations(name,applied_at,details_json) VALUES (?,?,?)", ("rbac-json-v1", now, json.dumps(details, ensure_ascii=False)))
            self._change(connection, "migration", "migration", "rbac.json", "import", {}, details)

    def changes(self, limit: int = 200) -> list[PermissionChange]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM permission_changes ORDER BY created_at DESC,id DESC LIMIT ?", (min(max(limit, 1), 1000),)).fetchall()
        result: list[PermissionChange] = []
        for row in rows:
            try:
                previous = json.loads(row["previous_json"] or "{}")
                current = json.loads(row["current_json"] or "{}")
            except ValueError:
                previous, current = {}, {}
            result.append(PermissionChange(id=row["id"], created_at=row["created_at"], actor=row["actor"], subject_type=row["subject_type"], subject=row["subject"], action=row["action"], previous=previous, current=current, status=row["status"], error_code=row["error_code"]))
        return result


@lru_cache
def _repository(path: str, legacy_path: str) -> IdentityRepository:
    return IdentityRepository(Path(path), legacy_path=Path(legacy_path))


def repository() -> IdentityRepository:
    root = Path(get_config().paths.data_dir)
    return _repository(str(root / "identity.sqlite3"), str(root / "rbac.json"))
