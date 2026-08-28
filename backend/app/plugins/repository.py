from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

from ..sqlite_utils import ClosingConnection
from .models import PluginTrust, StorePlugin


class PluginRepository:
    def __init__(self, path: Path, *, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path
        self._lock = threading.RLock()
        self._initialize()
        self._migrate_legacy()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plugins (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, github_url TEXT NOT NULL, branch TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, codex_instructions TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1, version TEXT NOT NULL DEFAULT '0.0.0',
                    installed_version TEXT, available_version TEXT, publisher TEXT NOT NULL DEFAULT 'unknown', description TEXT NOT NULL DEFAULT '',
                    min_algen_version TEXT NOT NULL DEFAULT '0.1.0', entrypoint TEXT NOT NULL DEFAULT '', capabilities_json TEXT NOT NULL DEFAULT '[]',
                    permissions_json TEXT NOT NULL DEFAULT '[]', source_ref TEXT NOT NULL DEFAULT 'main', resolved_commit TEXT, checksum_sha256 TEXT,
                    trust TEXT NOT NULL DEFAULT 'unverified', credential_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_plugins_enabled ON plugins(enabled, name);
                CREATE INDEX IF NOT EXISTS idx_plugins_trust ON plugins(trust, name);
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _plugin(row: sqlite3.Row) -> StorePlugin:
        raw = dict(row)
        raw["enabled"] = bool(raw["enabled"])
        raw["capabilities"] = json.loads(raw.pop("capabilities_json") or "[]")
        raw["permissions"] = json.loads(raw.pop("permissions_json") or "[]")
        return StorePlugin.model_validate(raw)

    def list(self) -> list[StorePlugin]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM plugins ORDER BY name COLLATE NOCASE, id").fetchall()
        return [self._plugin(row) for row in rows]

    def get(self, plugin_id: str) -> StorePlugin | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM plugins WHERE id=?", (plugin_id,)).fetchone()
        return self._plugin(row) if row else None

    def upsert(self, plugin: StorePlugin) -> StorePlugin:
        payload = plugin.model_dump(mode="json")
        capabilities = json.dumps(payload.pop("capabilities"), ensure_ascii=False, separators=(",", ":"))
        permissions = json.dumps(payload.pop("permissions"), ensure_ascii=False, separators=(",", ":"))
        payload["enabled"] = int(plugin.enabled)
        payload["trust"] = plugin.trust.value
        columns = [*payload.keys(), "capabilities_json", "permissions_json"]
        values = [*payload.values(), capabilities, permissions]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{column}=excluded.{column}" for column in columns if column != "id")
        with self._lock, self._connect() as connection:
            connection.execute(
                f"INSERT INTO plugins ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}",  # nosec B608
                values,
            )
        stored = self.get(plugin.id)
        if stored is None:
            raise RuntimeError("plugin could not be read after persistence")
        return stored

    def delete(self, plugin_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM plugins WHERE id=?", (plugin_id,))
        return cursor.rowcount > 0

    def _migrate_legacy(self) -> None:
        if not self.legacy_path or not self.legacy_path.exists() or self.list():
            return
        try:
            raw = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return
        entries = raw.get("plugins", []) if isinstance(raw, dict) else []
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                plugin = StorePlugin.model_validate({
                    **entry,
                    "schema_version": 1,
                    "version": entry.get("version") or "0.0.0",
                    "available_version": entry.get("available_version") or entry.get("version") or "0.0.0",
                    "source_ref": entry.get("source_ref") or entry.get("branch") or "main",
                    "trust": entry.get("trust") or PluginTrust.unverified.value,
                })
                self.upsert(plugin)
            except Exception:
                continue
