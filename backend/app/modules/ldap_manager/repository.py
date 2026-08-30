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

from ...config import get_config
from ..secrets_manager import SecretInput, service as secrets_service
from ...sqlite_utils import ClosingConnection
from .models import ConnectionInput


SECRET_MODULE = "ldap-manager"


class LdapManagerRepository:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(get_config().paths.data_dir).resolve(strict=False)
        self.path = path or root / "ldap-manager.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ldap_manager_connections(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    directory_type TEXT NOT NULL,
                    servers_json TEXT NOT NULL DEFAULT '[]',
                    security_mode TEXT NOT NULL DEFAULT 'starttls',
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    ca_certificate TEXT NOT NULL DEFAULT '',
                    base_dn TEXT NOT NULL,
                    bind_dn TEXT NOT NULL,
                    bind_secret_id TEXT NOT NULL DEFAULT '',
                    connect_timeout REAL NOT NULL DEFAULT 5,
                    operation_timeout REAL NOT NULL DEFAULT 15,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ldap_manager_connections_name ON ldap_manager_connections(name);
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _decode_servers(raw: str) -> list[dict[str, Any]]:
        try:
            value = json.loads(raw)
        except ValueError:
            return []
        return value if isinstance(value, list) else []

    @classmethod
    def _public(cls, row: sqlite3.Row, *, include_secret_id: bool = False) -> dict[str, Any]:
        value = {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "directory_type": str(row["directory_type"]),
            "servers": cls._decode_servers(str(row["servers_json"])),
            "security_mode": str(row["security_mode"]),
            "verify_tls": bool(row["verify_tls"]),
            "ca_certificate": str(row["ca_certificate"]),
            "base_dn": str(row["base_dn"]),
            "bind_dn": str(row["bind_dn"]),
            "bind_password_configured": bool(row["bind_secret_id"]),
            "connect_timeout": float(row["connect_timeout"]),
            "operation_timeout": float(row["operation_timeout"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "updated_by": str(row["updated_by"]),
        }
        if include_secret_id:
            value["bind_secret_id"] = str(row["bind_secret_id"])
        return value

    def list(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM ldap_manager_connections ORDER BY name COLLATE NOCASE,id").fetchall()
        return [self._public(row) for row in rows]

    def get(self, connection_id: str, *, include_secret_id: bool = False) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM ldap_manager_connections WHERE id=?", (connection_id,)).fetchone()
        if not row:
            raise LookupError("LDAP Manager connection not found")
        return self._public(row, include_secret_id=include_secret_id)

    def save(self, payload: ConnectionInput, actor: str, connection_id: str | None = None) -> dict[str, Any]:
        identifier = connection_id or str(uuid.uuid4())
        now = time.time()
        existing: dict[str, Any] | None = None
        if connection_id:
            existing = self.get(connection_id, include_secret_id=True)
        secret_id = str(existing.get("bind_secret_id") or "") if existing else ""
        if payload.clear_bind_password:
            if secret_id:
                secrets_service().delete(secret_id, actor)
                secret_id = ""
        elif payload.bind_password:
            saved = secrets_service().save(
                SecretInput(
                    name=f"ldap-manager-connection-{identifier}-bind-password",
                    type="generic_secret",
                    secret=payload.bind_password,
                    description=f"LDAP Manager bind credential for {payload.name}",
                    shared_with=[SECRET_MODULE],
                ),
                actor,
                secret_id or None,
            )
            secret_id = str(saved["id"])
        elif secret_id:
            secrets_service().save(
                SecretInput(
                    name=f"ldap-manager-connection-{identifier}-bind-password",
                    type="generic_secret",
                    description=f"LDAP Manager bind credential for {payload.name}",
                    shared_with=[SECRET_MODULE],
                ),
                actor,
                secret_id,
            )
        if not secret_id:
            raise ValueError("LDAP Manager connection requires its own bind password")
        created_at = float(existing["created_at"]) if existing else now
        servers = [item.model_dump(mode="json") for item in payload.servers]
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO ldap_manager_connections(
                    id,name,directory_type,servers_json,security_mode,verify_tls,ca_certificate,base_dn,bind_dn,
                    bind_secret_id,connect_timeout,operation_timeout,created_at,updated_at,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,directory_type=excluded.directory_type,servers_json=excluded.servers_json,
                    security_mode=excluded.security_mode,verify_tls=excluded.verify_tls,ca_certificate=excluded.ca_certificate,
                    base_dn=excluded.base_dn,bind_dn=excluded.bind_dn,bind_secret_id=excluded.bind_secret_id,
                    connect_timeout=excluded.connect_timeout,operation_timeout=excluded.operation_timeout,
                    updated_at=excluded.updated_at,updated_by=excluded.updated_by
                """,
                (
                    identifier, payload.name, payload.directory_type.value, json.dumps(servers), payload.security_mode.value,
                    int(payload.verify_tls), payload.ca_certificate, payload.base_dn, payload.bind_dn, secret_id,
                    payload.connect_timeout, payload.operation_timeout, created_at, now, actor,
                ),
            )
        return self.get(identifier)

    def delete(self, connection_id: str, actor: str) -> dict[str, Any]:
        value = self.get(connection_id, include_secret_id=True)
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM ldap_manager_connections WHERE id=?", (connection_id,))
        secret_id = str(value.get("bind_secret_id") or "")
        if secret_id:
            secrets_service().delete(secret_id, actor)
        value.pop("bind_secret_id", None)
        return value


@lru_cache(maxsize=1)
def repository() -> LdapManagerRepository:
    return LdapManagerRepository()
