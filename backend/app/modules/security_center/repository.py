from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from ...config import get_config
from ...sqlite_utils import ClosingConnection
from .models import FindingStatus


class SecurityStateRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(get_config().paths.data_dir) / "security-center.sqlite3"
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS finding_state (fingerprint TEXT PRIMARY KEY, status TEXT NOT NULL, actor TEXT NOT NULL, updated_at REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def states(self) -> dict[str, str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT fingerprint, status FROM finding_state").fetchall()
        return {str(row["fingerprint"]): str(row["status"]) for row in rows}

    def set_state(self, fingerprint: str, status: FindingStatus, actor: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO finding_state(fingerprint,status,actor,updated_at) VALUES(?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET status=excluded.status, actor=excluded.actor, updated_at=excluded.updated_at",
                (fingerprint, status.value, actor[:128], time.time()),
            )
