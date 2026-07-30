from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from app.modules.apmid.models import (
    ApmidInput, ApmidMemberCreate, ApmidPermissionUpdate, ApmidResourcePermission, ApmidRole,
)
from app.modules.apmid.service import (
    ApmidConflictError, ApmidService, LastOwnerError,
)
from app.modules.apmid import service as apmid_module


def store(tmp_path: Path, legacy: Path | None = None) -> ApmidService:
    return ApmidService(tmp_path / "apmid" / "apmid.sqlite3", legacy or tmp_path / "missing.sqlite3")


def permit_admin_only(monkeypatch) -> None:
    monkeypatch.setattr(apmid_module, "has_permission", lambda username, permission: username == "admin")
    monkeypatch.setattr(ApmidService, "_validate_user", staticmethod(lambda username: None))


def test_crud_normalizes_code_and_rejects_case_insensitive_duplicate(monkeypatch, tmp_path: Path):
    permit_admin_only(monkeypatch)
    registry = store(tmp_path)
    created = registry.create(ApmidInput(code=" app_one ", name="Application one"), "admin")
    assert created["code"] == "APP_ONE"
    assert created["created_by"] == "admin"
    updated = registry.update(created["id"], ApmidInput(code="app_one", name="Renamed", active=False), "admin")
    assert updated["name"] == "Renamed" and updated["active"] is False
    with pytest.raises(ApmidConflictError):
        registry.create(ApmidInput(code="APP_ONE", name="Duplicate"), "admin")
    with pytest.raises(ValueError):
        ApmidInput(code="bad code!", name="Bad")


def test_members_roles_allow_deny_and_last_owner_protection(monkeypatch, tmp_path: Path):
    permit_admin_only(monkeypatch)
    registry = store(tmp_path)
    item = registry.create(ApmidInput(code="CRM", name="CRM"), "admin")
    registry.add_members(item["id"], ApmidMemberCreate(usernames=["alice"], role=ApmidRole.manager), "admin")
    assert registry.can("alice", item["id"], ApmidResourcePermission.update)
    result = registry.set_permissions(
        item["id"], "alice",
        ApmidPermissionUpdate(
            allow=[ApmidResourcePermission.delete],
            deny=[ApmidResourcePermission.update],
        ),
        "admin",
    )
    assert "delete" in result["effective"]
    assert "update" not in result["effective"]
    assert result["sources"]["update"] == "deny"
    with pytest.raises(ApmidConflictError):
        registry.add_members(item["id"], ApmidMemberCreate(usernames=["alice"]), "admin")
    with pytest.raises(LastOwnerError):
        registry.remove_member(item["id"], "admin", "admin")
    with pytest.raises(LastOwnerError):
        registry.set_permissions(
            item["id"], "admin",
            ApmidPermissionUpdate(deny=[ApmidResourcePermission.permissions_manage]),
            "admin",
        )


def test_user_without_global_permission_only_sees_member_resources(monkeypatch, tmp_path: Path):
    permit_admin_only(monkeypatch)
    registry = store(tmp_path)
    first = registry.create(ApmidInput(code="ONE", name="One"), "admin")
    registry.create(ApmidInput(code="TWO", name="Two"), "admin")
    registry.add_members(first["id"], ApmidMemberCreate(usernames=["alice"], role=ApmidRole.viewer), "admin")
    visible = registry.list_items("alice")
    assert [item["code"] for item in visible["items"]] == ["ONE"]
    assert registry.has_access("alice") is True
    assert registry.can("alice", first["id"], ApmidResourcePermission.update) is False


def test_hosts_manager_migration_is_idempotent_and_keeps_ids_and_backup(tmp_path: Path):
    legacy = tmp_path / "hosts-manager" / "hosts.sqlite3"
    legacy.parent.mkdir(parents=True)
    now = time.time()
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            """CREATE TABLE apmids(
               id TEXT PRIMARY KEY,code TEXT,description TEXT,active INTEGER,
               created_at REAL,updated_at REAL,created_by TEXT,updated_by TEXT
            )"""
        )
        connection.execute("INSERT INTO apmids VALUES(?,?,?,?,?,?,?,?)", ("stable-id", "erp", "Legacy", 1, now, now, "root", "root"))
    registry = store(tmp_path, legacy)
    assert registry.get("stable-id")["code"] == "ERP"
    assert registry.migrate_hosts_manager()["already_applied"] is True
    marker = registry.migrations_root / "hosts-manager-apmids-v1.sqlite3.bak"
    assert marker.is_file()
    with sqlite3.connect(legacy) as connection:
        assert connection.execute("SELECT COUNT(*) FROM apmids").fetchone()[0] == 1


def test_backup_checksum_and_restore(monkeypatch, tmp_path: Path):
    permit_admin_only(monkeypatch)
    registry = store(tmp_path)
    item = registry.create(ApmidInput(code="BACKUP", name="Before"), "admin")
    backup = registry.create_backup("admin", "test")
    registry.update(item["id"], ApmidInput(code="BACKUP", name="After"), "admin")
    restored = registry.restore(backup["id"], "admin", "APMID")
    assert restored["ok"] is True
    assert registry.get(item["id"])["name"] == "Before"
    with pytest.raises(ValueError, match="confirmation"):
        registry.restore(backup["id"], "admin", "wrong")
