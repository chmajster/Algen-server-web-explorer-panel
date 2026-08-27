from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ...config import get_config

SCHEMA_VERSION = 1


class DcstRepository:
    def __init__(self, path: Path | None = None) -> None:
        root = (path.parent if path else Path(get_config().paths.data_dir) / "dcst").resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        self.path = path or root / "dcst.sqlite3"
        self._lock = threading.RLock()
        self._migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _migrate(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
            applied = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
            if 1 not in applied:
                connection.executescript(
                    """
                    CREATE TABLE dcst_tags(
                        id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,apmid TEXT NOT NULL,environment TEXT NOT NULL,
                        provider_name TEXT NOT NULL UNIQUE,type TEXT NOT NULL DEFAULT 'dynamic',managed_by TEXT NOT NULL DEFAULT 'DCST',
                        sync_status TEXT NOT NULL DEFAULT 'PENDING',last_error TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,updated_at REAL NOT NULL);
                    CREATE TABLE dcst_ipsets(
                        id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '',type TEXT NOT NULL,
                        provider_name TEXT NOT NULL UNIQUE,managed_by TEXT NOT NULL DEFAULT 'DCST',sync_status TEXT NOT NULL DEFAULT 'PENDING',
                        last_error TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,updated_at REAL NOT NULL,created_by TEXT NOT NULL,updated_by TEXT NOT NULL);
                    CREATE TABLE dcst_ipset_entries(
                        id TEXT PRIMARY KEY,ipset_id TEXT NOT NULL,address TEXT NOT NULL,comment TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,
                        UNIQUE(ipset_id,address),FOREIGN KEY(ipset_id) REFERENCES dcst_ipsets(id) ON DELETE CASCADE);
                    CREATE TABLE dcst_ports(
                        id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,protocol TEXT NOT NULL,port_from INTEGER,port_to INTEGER,description TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,updated_at REAL NOT NULL,created_by TEXT NOT NULL,updated_by TEXT NOT NULL);
                    CREATE TABLE dcst_services(
                        id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '',direction TEXT NOT NULL,action TEXT NOT NULL,
                        source_type TEXT NOT NULL,source_value TEXT NOT NULL DEFAULT '',destination_type TEXT NOT NULL,destination_value TEXT NOT NULL DEFAULT '',
                        enabled INTEGER NOT NULL DEFAULT 1,blocked INTEGER NOT NULL DEFAULT 0,logging INTEGER NOT NULL DEFAULT 0,comment TEXT NOT NULL DEFAULT '',
                        system_service INTEGER NOT NULL DEFAULT 0,managed_by TEXT NOT NULL DEFAULT 'DCST',sync_status TEXT NOT NULL DEFAULT 'PENDING',
                        last_error TEXT NOT NULL DEFAULT '',created_by TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,updated_by TEXT NOT NULL);
                    CREATE TABLE dcst_service_ports(
                        service_id TEXT NOT NULL,port_id TEXT NOT NULL,PRIMARY KEY(service_id,port_id),
                        FOREIGN KEY(service_id) REFERENCES dcst_services(id) ON DELETE CASCADE,
                        FOREIGN KEY(port_id) REFERENCES dcst_ports(id) ON DELETE RESTRICT);
                    CREATE TABLE dcst_audit(
                        id TEXT PRIMARY KEY,timestamp REAL NOT NULL,user TEXT NOT NULL,operation TEXT NOT NULL,object_type TEXT NOT NULL,object_id TEXT NOT NULL,
                        before_json TEXT NOT NULL DEFAULT '{}',after_json TEXT NOT NULL DEFAULT '{}',provider_response_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL,error TEXT NOT NULL DEFAULT '');
                    CREATE INDEX idx_dcst_audit_time ON dcst_audit(timestamp DESC);
                    CREATE TABLE dcst_state(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at REAL NOT NULL);
                    """
                )
                connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)", (1, time.time()))

    def audit(self, actor: str, operation: str, object_type: str, object_id: str, *, before: Any = None, after: Any = None, provider_response: Any = None, status: str = "success", error: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO dcst_audit VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (secrets.token_hex(16), time.time(), actor, operation, object_type, object_id, json.dumps(before or {}, default=str), json.dumps(after or {}, default=str), json.dumps(provider_response or {}, default=str), status, error[:2000]),
            )

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM dcst_audit ORDER BY timestamp DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field in ("before_json", "after_json", "provider_response_json"):
                item[field[:-5]] = json.loads(item.pop(field) or "{}")
            result.append(item)
        return result

    def tags(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM dcst_tags ORDER BY name COLLATE NOCASE")]

    def upsert_dynamic_tag(self, name: str, apmid: str, environment: str, provider_name: str) -> dict[str, Any]:
        now = time.time()
        with self.connect() as connection:
            row = connection.execute("SELECT id,created_at FROM dcst_tags WHERE name=?", (name,)).fetchone()
            item_id = str(row["id"]) if row else secrets.token_hex(16)
            created_at = float(row["created_at"]) if row else now
            connection.execute(
                """INSERT INTO dcst_tags(id,name,apmid,environment,provider_name,type,managed_by,sync_status,last_error,created_at,updated_at)
                VALUES(?,?,?,?,?,'dynamic','DCST','PENDING','',?,?)
                ON CONFLICT(name) DO UPDATE SET apmid=excluded.apmid,environment=excluded.environment,provider_name=excluded.provider_name,updated_at=excluded.updated_at""",
                (item_id, name, apmid, environment, provider_name, created_at, now),
            )
        return next(item for item in self.tags() if item["id"] == item_id)

    def delete_missing_dynamic_tags(self, names: set[str]) -> None:
        with self.connect() as connection:
            rows = connection.execute("SELECT id,name FROM dcst_tags WHERE type='dynamic'").fetchall()
            for row in rows:
                if str(row["name"]) not in names:
                    connection.execute("DELETE FROM dcst_tags WHERE id=?", (row["id"],))

    def ipsets(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            sets = [dict(row) for row in connection.execute("SELECT * FROM dcst_ipsets ORDER BY name COLLATE NOCASE")]
            entries = connection.execute("SELECT * FROM dcst_ipset_entries ORDER BY address").fetchall()
        by_id: dict[str, list[dict[str, Any]]] = {}
        for row in entries:
            by_id.setdefault(str(row["ipset_id"]), []).append(dict(row))
        for item in sets:
            item["entries"] = by_id.get(str(item["id"]), [])
        return sets

    def ipset(self, item_id: str) -> dict[str, Any] | None:
        return next((item for item in self.ipsets() if item["id"] == item_id), None)

    def save_ipset(self, name: str, description: str, entries: list[str], actor: str, *, item_id: str | None = None, item_type: str = "manual", provider_name: str = "") -> dict[str, Any]:
        now = time.time()
        item_id = item_id or secrets.token_hex(16)
        provider_name = provider_name or name
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM dcst_ipsets WHERE id=?", (item_id,)).fetchone()
            created_at = float(old["created_at"]) if old else now
            created_by = str(old["created_by"]) if old else actor
            connection.execute(
                """INSERT INTO dcst_ipsets(id,name,description,type,provider_name,managed_by,sync_status,last_error,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,'DCST','PENDING','',?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,provider_name=excluded.provider_name,sync_status='PENDING',last_error='',updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, name, description, item_type, provider_name, created_at, now, created_by, actor),
            )
            connection.execute("DELETE FROM dcst_ipset_entries WHERE ipset_id=?", (item_id,))
            connection.executemany(
                "INSERT INTO dcst_ipset_entries(id,ipset_id,address,comment,created_at) VALUES(?,?,?,?,?)",
                [(secrets.token_hex(16), item_id, address, "", now) for address in entries],
            )
        return self.ipset(item_id) or {}

    def delete_ipset(self, item_id: str) -> bool:
        with self.connect() as connection:
            return bool(connection.execute("DELETE FROM dcst_ipsets WHERE id=? AND type='manual'", (item_id,)).rowcount)

    def ports(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM dcst_ports ORDER BY name COLLATE NOCASE")]

    def port(self, item_id: str) -> dict[str, Any] | None:
        return next((item for item in self.ports() if item["id"] == item_id), None)

    def save_port(self, value: dict[str, Any], actor: str, item_id: str | None = None) -> dict[str, Any]:
        now = time.time()
        item_id = item_id or secrets.token_hex(16)
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM dcst_ports WHERE id=?", (item_id,)).fetchone()
            created_at = float(old["created_at"]) if old else now
            created_by = str(old["created_by"]) if old else actor
            connection.execute(
                """INSERT INTO dcst_ports(id,name,protocol,port_from,port_to,description,created_at,updated_at,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,protocol=excluded.protocol,port_from=excluded.port_from,port_to=excluded.port_to,description=excluded.description,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, value["name"], value["protocol"], value.get("port_from"), value.get("port_to"), value.get("description", ""), created_at, now, created_by, actor),
            )
        return self.port(item_id) or {}

    def port_dependencies(self, item_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT s.id,s.name FROM dcst_services s JOIN dcst_service_ports sp ON sp.service_id=s.id WHERE sp.port_id=? ORDER BY s.name", (item_id,))]

    def delete_port(self, item_id: str) -> bool:
        if self.port_dependencies(item_id):
            raise ValueError("Port is referenced by one or more Services")
        with self.connect() as connection:
            return bool(connection.execute("DELETE FROM dcst_ports WHERE id=?", (item_id,)).rowcount)

    def services(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute("SELECT * FROM dcst_services ORDER BY name COLLATE NOCASE")]
            links = connection.execute("SELECT service_id,port_id FROM dcst_service_ports ORDER BY service_id,port_id").fetchall()
        by_service: dict[str, list[str]] = {}
        for row in links:
            by_service.setdefault(str(row["service_id"]), []).append(str(row["port_id"]))
        for item in rows:
            for key in ("enabled", "blocked", "logging", "system_service"):
                item[key] = bool(item[key])
            item["port_ids"] = by_service.get(str(item["id"]), [])
            item["state"] = "BLOCKED" if item["blocked"] else "DISABLED" if not item["enabled"] else "ERROR" if item["sync_status"] == "ERROR" else "ACTIVE"
        return rows

    def service(self, item_id: str) -> dict[str, Any] | None:
        return next((item for item in self.services() if item["id"] == item_id), None)

    def save_service(self, value: dict[str, Any], actor: str, item_id: str | None = None, *, system_service: bool = False) -> dict[str, Any]:
        now = time.time()
        item_id = item_id or secrets.token_hex(16)
        with self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by,system_service FROM dcst_services WHERE id=?", (item_id,)).fetchone()
            created_at = float(old["created_at"]) if old else now
            created_by = str(old["created_by"]) if old else actor
            system_service = bool(old["system_service"]) if old else system_service
            connection.execute(
                """INSERT INTO dcst_services(id,name,description,direction,action,source_type,source_value,destination_type,destination_value,enabled,blocked,logging,comment,system_service,managed_by,sync_status,last_error,created_by,created_at,updated_at,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'DCST','PENDING','',?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,direction=excluded.direction,action=excluded.action,source_type=excluded.source_type,source_value=excluded.source_value,destination_type=excluded.destination_type,destination_value=excluded.destination_value,enabled=excluded.enabled,logging=excluded.logging,comment=excluded.comment,sync_status='PENDING',last_error='',updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (item_id, value["name"], value.get("description", ""), value["direction"], value["action"], value["source_type"], value.get("source_value", ""), value["destination_type"], value.get("destination_value", ""), int(value.get("enabled", True)), 0, int(value.get("logging", False)), value.get("comment", ""), int(system_service), created_by, created_at, now, actor),
            )
            connection.execute("DELETE FROM dcst_service_ports WHERE service_id=?", (item_id,))
            connection.executemany("INSERT INTO dcst_service_ports(service_id,port_id) VALUES(?,?)", [(item_id, port_id) for port_id in value.get("port_ids", [])])
        return self.service(item_id) or {}

    def set_service_state(self, item_id: str, *, enabled: bool | None = None, blocked: bool | None = None, sync_status: str = "PENDING", error: str = "") -> dict[str, Any]:
        changes = []
        params: list[Any] = []
        if enabled is not None:
            changes.append("enabled=?")
            params.append(int(enabled))
        if blocked is not None:
            changes.append("blocked=?")
            params.append(int(blocked))
        changes.extend(["sync_status=?", "last_error=?", "updated_at=?"])
        params.extend([sync_status, error[:2000], time.time(), item_id])
        with self.connect() as connection:
            if not connection.execute(f"UPDATE dcst_services SET {','.join(changes)} WHERE id=?", params).rowcount:
                raise KeyError("Service not found")
        return self.service(item_id) or {}

    def set_object_sync(self, table: str, item_id: str, status: str, error: str = "") -> None:
        if table not in {"dcst_services", "dcst_ipsets", "dcst_tags"}:
            raise ValueError("invalid table")
        with self.connect() as connection:
            connection.execute(f"UPDATE {table} SET sync_status=?,last_error=?,updated_at=? WHERE id=?", (status, error[:2000], time.time(), item_id))

    def delete_service(self, item_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT system_service FROM dcst_services WHERE id=?", (item_id,)).fetchone()
            if row and bool(row["system_service"]):
                raise ValueError("System Service cannot be deleted")
            return bool(connection.execute("DELETE FROM dcst_services WHERE id=?", (item_id,)).rowcount)

    def state(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT value_json FROM dcst_state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_state(self, key: str, value: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO dcst_state(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, json.dumps(value, default=str), time.time()),
            )
