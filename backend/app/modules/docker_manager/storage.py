from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ...config import get_config
from ...package_center.models import api_error


TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
ARTIFACT_RE = re.compile(r"^[a-f0-9]{24}$")


class DockerManagerStore:
    """Private metadata, credentials and bounded telemetry for Containers Manager."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(get_config().paths.data_dir) / "docker-manager"
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.inputs_dir = self.root / "inputs"
        self.artifacts_dir = self.root / "artifacts"
        self.secrets_dir = self.root / "secrets"
        for path in (self.inputs_dir, self.artifacts_dir, self.secrets_dir):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)
        self.path = self.root / "manager.sqlite3"
        self._lock = threading.RLock()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _migrate(self) -> None:
        purge_plaintext = False
        with self._lock, self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version < 1:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS registries (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        provider TEXT NOT NULL,
                        server TEXT NOT NULL,
                        username TEXT NOT NULL,
                        password TEXT NOT NULL,
                        tls INTEGER NOT NULL DEFAULT 1,
                        ca_certificate TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS stats_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        captured_at REAL NOT NULL,
                        container_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        cpu_percent REAL NOT NULL,
                        memory_bytes INTEGER NOT NULL,
                        network_input_bytes INTEGER NOT NULL,
                        network_output_bytes INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS ix_docker_stats_container_time
                    ON stats_history(container_id, captured_at DESC);
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        filename TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        created_by TEXT NOT NULL,
                        metadata TEXT NOT NULL
                    );
                    PRAGMA user_version=1;
                    """
                )
                version = 1
            if version < 2:
                columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(registries)").fetchall()}
                if "tls" not in columns:
                    connection.execute("ALTER TABLE registries ADD COLUMN tls INTEGER NOT NULL DEFAULT 1")
                if "ca_certificate" not in columns:
                    connection.execute("ALTER TABLE registries ADD COLUMN ca_certificate TEXT NOT NULL DEFAULT ''")
                legacy_credentials = connection.execute("SELECT id,password FROM registries WHERE password<>''").fetchall()
                for row in legacy_credentials:
                    self._write_registry_secret(str(row["id"]), str(row["password"]))
                connection.execute("UPDATE registries SET password='' WHERE password<>''")
                connection.execute("PRAGMA user_version=2")
                purge_plaintext = bool(legacy_credentials)
        if purge_plaintext:
            with self._lock, self._connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if self.path.exists():
            os.chmod(self.path, 0o600)

    def stage_input(self, payload: dict[str, Any]) -> str:
        token = secrets.token_hex(16)
        target = self.inputs_dir / f"{token}.json"
        temp = self.inputs_dir / f"{token}.tmp"
        value = {"created_at": time.time(), "payload": payload}
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, target)
        return token

    def consume_input(self, token: str, *, max_age: int = 3600) -> dict[str, Any]:
        if not TOKEN_RE.fullmatch(token):
            api_error(400, "INVALID_INPUT_REFERENCE", "Invalid private input reference")
        target = self.inputs_dir / f"{token}.json"
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("Private operation input is missing or invalid") from error
        finally:
            target.unlink(missing_ok=True)
        if time.time() - float(raw.get("created_at") or 0) > max_age:
            raise RuntimeError("Private operation input expired")
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("Private operation input is invalid")
        return payload

    def discard_input(self, token: str) -> None:
        if TOKEN_RE.fullmatch(token):
            (self.inputs_dir / f"{token}.json").unlink(missing_ok=True)

    def _registry_secret_path(self, registry_id: str) -> Path:
        if not ARTIFACT_RE.fullmatch(registry_id):
            api_error(400, "INVALID_REGISTRY_ID", "Invalid registry identifier")
        return self.secrets_dir / f"registry-{registry_id}.secret"

    def _write_registry_secret(self, registry_id: str, password: str) -> None:
        target = self._registry_secret_path(registry_id)
        temp = target.with_suffix(f".{secrets.token_hex(6)}.tmp")
        with temp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(password)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, target)
        os.chmod(target, 0o600)

    def save_registry(
        self,
        *,
        registry_id: str | None,
        name: str,
        provider: str,
        server: str,
        username: str,
        password: str | None,
        tls: bool = True,
        ca_certificate: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT * FROM registries WHERE id=?", (registry_id,)).fetchone() if registry_id else None
            value_id = str(existing["id"]) if existing else secrets.token_hex(12)
            has_stored_password = self._registry_secret_path(value_id).is_file()
            if password is None and not has_stored_password:
                api_error(422, "REGISTRY_PASSWORD_REQUIRED", "Registry password or token is required")
            stored_ca = "" if not tls else ca_certificate if ca_certificate is not None else str(existing["ca_certificate"] or "") if existing else ""
            try:
                connection.execute(
                    """INSERT INTO registries(id,name,provider,server,username,password,tls,ca_certificate,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,provider=excluded.provider,server=excluded.server,
                    username=excluded.username,password='',tls=excluded.tls,ca_certificate=excluded.ca_certificate,updated_at=excluded.updated_at""",
                    (value_id, name, provider, server, username, "", int(tls), stored_ca, float(existing["created_at"]) if existing else now, now),
                )
            except sqlite3.IntegrityError:
                api_error(409, "REGISTRY_NAME_EXISTS", "A registry with this name already exists")
            if password is not None:
                self._write_registry_secret(value_id, password)
        return self.public_registry(value_id)

    def _public_registry(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "name": row["name"], "provider": row["provider"], "server": row["server"],
            "username": row["username"], "tls": bool(row["tls"]), "ca_certificate_configured": bool(row["ca_certificate"]),
            "secret_configured": self._registry_secret_path(str(row["id"])).is_file(), "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def list_registries(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM registries ORDER BY name COLLATE NOCASE").fetchall()
        return [self._public_registry(row) for row in rows]

    def public_registry(self, registry_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM registries WHERE id=?", (registry_id,)).fetchone()
        if not row:
            api_error(404, "REGISTRY_NOT_FOUND", "Registry not found")
        return self._public_registry(row)

    def registry_credentials(self, registry_id: str) -> dict[str, str]:
        with self._connect() as connection:
            row = connection.execute("SELECT server,username,tls,ca_certificate FROM registries WHERE id=?", (registry_id,)).fetchone()
        if not row:
            api_error(404, "REGISTRY_NOT_FOUND", "Registry not found")
        try:
            password = self._registry_secret_path(registry_id).read_text(encoding="utf-8")
        except OSError:
            api_error(409, "REGISTRY_SECRET_MISSING", "Registry credential is missing")
        return {
            "server": str(row["server"]), "username": str(row["username"]), "password": password,
            "tls": "true" if bool(row["tls"]) else "false", "ca_certificate": str(row["ca_certificate"] or ""),
        }

    def delete_registry(self, registry_id: str) -> dict[str, Any]:
        value = self.public_registry(registry_id)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM registries WHERE id=?", (registry_id,))
        self._registry_secret_path(registry_id).unlink(missing_ok=True)
        return value

    def add_stats(self, items: list[dict[str, Any]]) -> None:
        cutoff = time.time() - 7 * 86400
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO stats_history(captured_at,container_id,name,cpu_percent,memory_bytes,network_input_bytes,network_output_bytes) VALUES(?,?,?,?,?,?,?)",
                [(float(item["captured_at"]), str(item["container_id"]), str(item["name"]), float(item["cpu_percent"]), int(item["memory_bytes"]), int(item["network_input_bytes"]), int(item["network_output_bytes"])) for item in items],
            )
            connection.execute("DELETE FROM stats_history WHERE captured_at<?", (cutoff,))

    def stats(self, container_id: str, *, since: float, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT captured_at,container_id,name,cpu_percent,memory_bytes,network_input_bytes,network_output_bytes FROM stats_history WHERE container_id=? AND captured_at>=? ORDER BY captured_at DESC LIMIT ?",
                (container_id, since, min(max(limit, 1), 5000)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def register_artifact(self, path: Path, *, kind: str, display_name: str, actor: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.artifacts_dir.resolve())
        except ValueError:
            api_error(422, "INVALID_ARTIFACT_PATH", "Artifact must be stored in the private Docker directory")
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        artifact_id = secrets.token_hex(12)
        payload = {
            "id": artifact_id, "kind": kind, "filename": resolved.name, "display_name": display_name[:200],
            "checksum": digest.hexdigest(), "size": resolved.stat().st_size, "created_at": time.time(), "created_by": actor,
            "metadata": metadata or {},
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts(id,kind,filename,display_name,checksum,size,created_at,created_by,metadata) VALUES(?,?,?,?,?,?,?,?,?)",
                (payload["id"], payload["kind"], payload["filename"], payload["display_name"], payload["checksum"], payload["size"], payload["created_at"], payload["created_by"], json.dumps(payload["metadata"], ensure_ascii=False)),
            )
        return payload

    def list_artifacts(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM artifacts WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall() if kind else connection.execute("SELECT * FROM artifacts ORDER BY created_at DESC").fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]

    def artifact(self, artifact_id: str) -> tuple[Path, dict[str, Any]]:
        if not ARTIFACT_RE.fullmatch(artifact_id):
            api_error(400, "INVALID_ARTIFACT_ID", "Invalid artifact identifier")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if not row:
            api_error(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
        metadata = {**dict(row), "metadata": json.loads(row["metadata"])}
        path = self.artifacts_dir / str(row["filename"])
        digest = hashlib.sha256()
        if path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        if not path.is_file() or digest.hexdigest() != row["checksum"]:
            api_error(409, "ARTIFACT_CHECKSUM_MISMATCH", "Artifact checksum verification failed")
        return path, metadata


_store: DockerManagerStore | None = None
_store_root: Path | None = None
_store_lock = threading.Lock()


def store() -> DockerManagerStore:
    global _store, _store_root
    root = Path(get_config().paths.data_dir) / "docker-manager"
    with _store_lock:
        if _store is None or _store_root != root:
            _store = DockerManagerStore(root)
            _store_root = root
        return _store
