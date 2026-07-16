from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .audit import logger
from .config import get_config
from .package_center.executor import redact


class ActivityCategory(StrEnum):
    login = "login"
    file = "file"
    configuration = "configuration"
    administration = "administration"
    module = "module"


class ActivityStatus(StrEnum):
    success = "success"
    failure = "failure"
    info = "info"
    queued = "queued"
    cancelled = "cancelled"


class ActivityEvent(BaseModel):
    id: int
    created_at: float
    actor: str = Field(max_length=128)
    category: ActivityCategory
    action: str = Field(max_length=96)
    target: str = Field(default="", max_length=1000)
    status: ActivityStatus
    summary: str = Field(default="", max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="webnas", max_length=64)


_SENSITIVE_MARKERS = ("password", "passwd", "secret", "token", "authorization", "credential", "cookie", "private_key")
_MAX_EVENTS = 20_000
_MAX_DETAILS_BYTES = 16 * 1024


def _text(value: object, limit: int) -> str:
    return redact(str(value)).strip()[:limit]


def _sensitive_key(key: object) -> bool:
    normalized = str(key).casefold()
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in list(value.items())[:50]:
            safe_key = _text(key, 80)
            result[safe_key] = "[REDACTED]" if _sensitive_key(key) else _sanitize(nested, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return _text(value, 1000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _text(value, 1000)


def sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    sanitized = _sanitize(details or {})
    if not isinstance(sanitized, dict):
        return {}
    encoded = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= _MAX_DETAILS_BYTES:
        return sanitized
    return {"truncated": True}


class ActivityRepository:
    def __init__(self, path: Path, *, max_events: int = _MAX_EVENTS) -> None:
        self.path = path
        self.max_events = max(100, max_events)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    actor TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'webnas'
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_events(created_at DESC, id DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_actor_time ON activity_events(actor, created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_activity_category_time ON activity_events(category, created_at DESC)")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _event(row: sqlite3.Row) -> ActivityEvent:
        try:
            details = json.loads(row["details_json"])
        except (TypeError, ValueError):
            details = {}
        return ActivityEvent(
            id=row["id"],
            created_at=row["created_at"],
            actor=row["actor"],
            category=row["category"],
            action=row["action"],
            target=row["target"],
            status=row["status"],
            summary=row["summary"],
            details=details if isinstance(details, dict) else {},
            source=row["source"],
        )

    def add(
        self,
        *,
        actor: str,
        category: ActivityCategory,
        action: str,
        target: str = "",
        status: ActivityStatus = ActivityStatus.success,
        summary: str = "",
        details: Mapping[str, Any] | None = None,
        source: str = "webnas",
        created_at: float | None = None,
    ) -> ActivityEvent:
        safe_details = sanitize_details(details)
        values = (
            created_at or time.time(),
            _text(actor, 128) or "system",
            category.value,
            _text(action, 96) or "unknown",
            _text(target, 1000),
            status.value,
            _text(summary, 500),
            json.dumps(safe_details, ensure_ascii=False, separators=(",", ":")),
            _text(source, 64) or "webnas",
        )
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO activity_events
                    (created_at, actor, category, action, target, status, summary, details_json, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Activity event did not receive an id")
            event_id = cursor.lastrowid
            if event_id % 100 == 0:
                connection.execute(
                    "DELETE FROM activity_events WHERE id IN (SELECT id FROM activity_events ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?)",
                    (self.max_events,),
                )
            row = connection.execute("SELECT * FROM activity_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise RuntimeError("Activity event could not be read after insertion")
        return self._event(row)

    @staticmethod
    def _filter_values(
        *,
        actor: str | None = None,
        category: ActivityCategory | None = None,
        status: ActivityStatus | None = None,
        search: str = "",
        since: float | None = None,
        until: float | None = None,
    ) -> list[Any]:
        category_value = category.value if category else None
        status_value = status.value if status else None
        clipped_search = search[:200]
        pattern = f"%{clipped_search}%"
        return [
            actor, actor,
            category_value, category_value,
            status_value, status_value,
            clipped_search, pattern, pattern, pattern, pattern,
            since, since,
            until, until,
        ]

    def list(
        self,
        *,
        actor: str | None = None,
        category: ActivityCategory | None = None,
        status: ActivityStatus | None = None,
        search: str = "",
        since: float | None = None,
        until: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ActivityEvent], int]:
        values = self._filter_values(actor=actor, category=category, status=status, search=search, since=since, until=until)
        with self._lock, self._connect() as connection:
            total = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM activity_events
                    WHERE (? IS NULL OR actor = ?)
                      AND (? IS NULL OR category = ?)
                      AND (? IS NULL OR status = ?)
                      AND (? = '' OR action LIKE ? OR target LIKE ? OR summary LIKE ? OR actor LIKE ?)
                      AND (? IS NULL OR created_at >= ?)
                      AND (? IS NULL OR created_at <= ?)
                    """,
                    values,
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT * FROM activity_events
                WHERE (? IS NULL OR actor = ?)
                  AND (? IS NULL OR category = ?)
                  AND (? IS NULL OR status = ?)
                  AND (? = '' OR action LIKE ? OR target LIKE ? OR summary LIKE ? OR actor LIKE ?)
                  AND (? IS NULL OR created_at >= ?)
                  AND (? IS NULL OR created_at <= ?)
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        return [self._event(row) for row in rows], total

    def summary(self, *, actor: str | None = None) -> dict[str, Any]:
        values = [actor, actor]
        with self._lock, self._connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM activity_events WHERE (? IS NULL OR actor = ?)", values).fetchone()[0])
            categories = {
                row["category"]: int(row["amount"])
                for row in connection.execute("SELECT category, COUNT(*) AS amount FROM activity_events WHERE (? IS NULL OR actor = ?) GROUP BY category", values).fetchall()
            }
            statuses = {
                row["status"]: int(row["amount"])
                for row in connection.execute("SELECT status, COUNT(*) AS amount FROM activity_events WHERE (? IS NULL OR actor = ?) GROUP BY status", values).fetchall()
            }
            latest = connection.execute("SELECT MAX(created_at) FROM activity_events WHERE (? IS NULL OR actor = ?)", values).fetchone()[0]
        return {
            "total": total,
            "categories": {item.value: categories.get(item.value, 0) for item in ActivityCategory},
            "statuses": {item.value: statuses.get(item.value, 0) for item in ActivityStatus},
            "latest_at": latest,
        }


@lru_cache
def _repository_for(path: str) -> ActivityRepository:
    return ActivityRepository(Path(path))


def repository() -> ActivityRepository:
    return _repository_for(str(Path(get_config().paths.data_dir) / "activity.sqlite3"))


def record_activity(
    category: ActivityCategory,
    action: str,
    actor: str,
    *,
    target: str = "",
    status: ActivityStatus = ActivityStatus.success,
    summary: str = "",
    details: Mapping[str, Any] | None = None,
    source: str = "webnas",
) -> ActivityEvent | None:
    """Persist an activity event without ever breaking the primary operation."""
    try:
        return repository().add(
            actor=actor,
            category=category,
            action=action,
            target=target,
            status=status,
            summary=summary,
            details=details,
            source=source,
        )
    except Exception:  # noqa: BLE001
        logger.exception("activity_record_failed category=%s action=%s actor=%s", category.value, action, actor)
        return None
