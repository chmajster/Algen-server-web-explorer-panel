from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from ..modules.ansible_controller.security import redact, redact_text
from .models import (
    LOG_PRIORITIES,
    MAX_FIELD_VALUE,
    MAX_MESSAGE,
    PYTHON_EXCEPTION_RE,
    PYTHON_TRACEBACK_LINE_RE,
    PYTHON_TRACEBACK_RE,
    LogEntry,
    _int,
)


def safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in list(fields.items())[:120]:
        normalized_key = str(key)[:128]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = redact_text(value, limit=MAX_FIELD_VALUE) if isinstance(value, str) else value
    return redact(safe)


def _timestamp(value: object) -> tuple[str | None, float | None]:
    raw = _int(value)
    if raw is None:
        return None, None
    seconds = raw / 1_000_000
    try:
        return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="milliseconds"), seconds
    except (OSError, OverflowError, ValueError):
        return None, None


def parse_journal_record(raw: str | dict[str, Any]) -> LogEntry | None:
    try:
        fields = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(fields, dict):
        return None
    message = fields.get("MESSAGE", "")
    if isinstance(message, list):
        message = bytes(item for item in message if isinstance(item, int) and 0 <= item <= 255).decode("utf-8", errors="replace")
    message = redact_text(message, limit=MAX_MESSAGE).replace("\x00", "")
    timestamp, _ = _timestamp(fields.get("__REALTIME_TIMESTAMP") or fields.get("_SOURCE_REALTIME_TIMESTAMP"))
    priority = _int(fields.get("PRIORITY"))
    priority = priority if priority in LOG_PRIORITIES else 6
    cursor = str(fields.get("__CURSOR") or "")[:2048]
    stable = cursor or hashlib.sha256(f"{timestamp}|{fields.get('_PID')}|{message}".encode("utf-8", errors="replace")).hexdigest()
    return LogEntry(
        id=stable,
        timestamp=timestamp,
        priority=priority,
        severity=LOG_PRIORITIES[priority],
        source="journal",
        unit=str(fields.get("_SYSTEMD_UNIT") or fields.get("_SYSTEMD_USER_UNIT") or "")[:128],
        identifier=str(fields.get("SYSLOG_IDENTIFIER") or fields.get("_COMM") or "")[:128],
        hostname=str(fields.get("_HOSTNAME") or "")[:255],
        pid=_int(fields.get("_PID") or fields.get("SYSLOG_PID")),
        uid=_int(fields.get("_UID")),
        message=message,
        cursor=cursor,
        fields=safe_fields(fields),
    )


def parse_dmesg_record(raw: str | dict[str, Any]) -> LogEntry | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw.lstrip().startswith("{") else raw
    except json.JSONDecodeError:
        value = raw
    if isinstance(value, dict):
        message = redact_text(value.get("msg") or value.get("message") or "", limit=MAX_MESSAGE)
        priority = _int(value.get("pri"))
        timestamp = str(value.get("time") or value.get("timestamp") or "")[:64] or None
        fields = safe_fields(value)
    else:
        message = redact_text(value, limit=MAX_MESSAGE)
        priority = None
        timestamp = None
        fields = {}
    if not message:
        return None
    priority = priority if priority in LOG_PRIORITIES else 6
    stable = hashlib.sha256(f"{timestamp}|{message}".encode()).hexdigest()
    return LogEntry(id=stable, timestamp=timestamp, priority=priority, severity=LOG_PRIORITIES[priority], source="kernel", identifier="kernel", message=message, fields=fields)


def _entry_seconds(entry: LogEntry) -> float | None:
    if not entry.timestamp:
        return None
    try:
        return datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _traceback_context(entry: LogEntry) -> tuple[str, int | None, str]:
    boot_id = entry.fields.get("_BOOT_ID") if isinstance(entry.fields, dict) else ""
    return entry.unit, entry.pid, str(boot_id or "")


def _traceback_continuation(message: str) -> bool:
    return bool(PYTHON_TRACEBACK_LINE_RE.fullmatch(message) or PYTHON_EXCEPTION_RE.search(message))


def group_traceback_entries(entries: list[LogEntry]) -> list[LogEntry]:
    if len(entries) < 2:
        return entries
    timed = [_entry_seconds(entry) for entry in entries]
    descending = timed[0] is not None and timed[-1] is not None and timed[0] > timed[-1]
    ordered = list(reversed(entries)) if descending else list(entries)
    grouped: list[LogEntry] = []
    index = 0
    while index < len(ordered):
        first = ordered[index]
        if not PYTHON_TRACEBACK_RE.search(first.message):
            grouped.append(first)
            index += 1
            continue
        first_time = _entry_seconds(first)
        context = _traceback_context(first)
        candidates = [first]
        cursor = index + 1
        terminal = False
        safe_time = first_time is not None
        while cursor < len(ordered):
            candidate = ordered[cursor]
            candidate_time = _entry_seconds(candidate)
            if _traceback_context(candidate) != context or not _traceback_continuation(candidate.message):
                break
            if first_time is not None and candidate_time is not None:
                if candidate_time - first_time > 2 or candidate_time < first_time:
                    break
            else:
                safe_time = False
            candidates.append(candidate)
            cursor += 1
            if PYTHON_EXCEPTION_RE.search(candidate.message):
                terminal = True
                break
        if len(candidates) < 2 or not terminal:
            grouped.append(first)
            index += 1
            continue
        if not safe_time:
            for candidate in candidates:
                marked = candidate.model_copy(deep=True)
                original = marked.original_priority if marked.original_priority in LOG_PRIORITIES else marked.priority
                marked.priority = min(original, 3)
                marked.severity = LOG_PRIORITIES[marked.priority]
                marked.severity_inferred = marked.priority < original
                marked.severity_reason = "python_traceback" if marked.severity_inferred else None
                grouped.append(marked)
            index = cursor
            continue
        message = redact_text("\n".join(item.message for item in candidates), limit=MAX_MESSAGE)
        originals = [
            {"id": item.id, "timestamp": item.timestamp, "original_priority": item.original_priority, "message": redact_text(item.message, limit=MAX_MESSAGE)}
            for item in candidates
        ]
        stable = hashlib.sha256(("traceback|" + "|".join(item.id for item in candidates)).encode("utf-8", errors="replace")).hexdigest()
        fields = dict(first.fields)
        fields.update({"traceback_records": originals, "traceback_lines": message.splitlines(), "merged_count": len(candidates)})
        original_priority = min(item.original_priority if item.original_priority in LOG_PRIORITIES else item.priority for item in candidates)
        grouped.append(LogEntry(
            id=stable,
            timestamp=first.timestamp,
            original_priority=original_priority,
            source=first.source,
            unit=first.unit,
            identifier=first.identifier,
            hostname=first.hostname,
            pid=first.pid,
            uid=first.uid,
            message=message,
            cursor=first.cursor,
            fields=redact(fields),
        ))
        index = cursor
    return list(reversed(grouped)) if descending else grouped
