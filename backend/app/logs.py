from __future__ import annotations

import asyncio
import base64
import csv
import gzip
import grp
import hashlib
import io
import json
import os
import pwd
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .activity import ActivityCategory, ActivityStatus, record_activity, repository as activity_repository
from .config import get_config
from .identity.permissions import Permission, authorize, has_permission
from .modules.ansible_controller.security import redact, redact_text
from .security import SessionUser, get_session_user, require_csrf


router = APIRouter(prefix="/api/logs", tags=["logs"])

MAX_MESSAGE = 16 * 1024
MAX_FIELD_VALUE = 4096
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_COMMAND_BYTES = 12 * 1024 * 1024
MAX_REGEX_LENGTH = 180
MAX_EXPORT = 5000
LOG_PRIORITIES = {
    0: "emergency", 1: "alert", 2: "critical", 3: "error",
    4: "warning", 5: "notice", 6: "info", 7: "debug",
}
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.(?:service|socket|timer|mount|target|scope)$")
CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.@:/-]{1,128}$")
ACCOUNT_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}\$?$")
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9_.:-]{0,251}[A-Za-z0-9])?$")
BOOT_RE = re.compile(r"^[a-fA-F0-9]{32}$")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9:_.@/-]{0,180}$")
UNSAFE_REGEX_RE = re.compile(r"(\([^)]*[+*][^)]*\)[+*]|\.\*[+*]|\.\+\+|\{\d+,\d*\}[+*])")
PYTHON_TRACEBACK_RE = re.compile(r"(?m)^Traceback \(most recent call last\):\s*$")
PYTHON_EXCEPTION_RE = re.compile(
    r"(?m)^(?:[\w.]+\.)?[A-Za-z_]\w*(?:Error|Exception|Fault|Failure):(?:\s|$)"
)
PYTHON_TRACEBACK_LINE_RE = re.compile(
    r'^(?:\s+File ".+", line \d+(?:, in .+)?|\s+.*|\s*\^+\s*|'
    r'During handling of the above exception.*|The above exception was the direct cause.*)$'
)
ERROR_SIGNAL_RE = re.compile(
    r"(?im)(?:^|\b)(?:Exception in ASGI application|Unhandled exception|Uncaught exception|"
    r"Segmentation fault|core dumped|panic|failed with result|process exited with status)(?:\b|$)"
)
UPPERCASE_ERROR_RE = re.compile(r"(?m)(?:^|[\s:\[])(?:ERROR|FATAL)(?:[\s:\]]|$)")
BENIGN_ERROR_RE = re.compile(
    r"(?i)\b(?:0 errors?|no errors?(?: detected)?|errors?\s+(?:count|rate)\s*:\s*0|"
    r"without error|ignore_errors|error handling enabled|documentation about error handling)\b"
)

CLASSIC_LOGS: dict[str, tuple[str, str, Permission]] = {
    "syslog": ("/var/log/syslog", "System log", Permission.LOGS_VIEW_SYSTEM),
    "messages": ("/var/log/messages", "System messages", Permission.LOGS_VIEW_SYSTEM),
    "auth": ("/var/log/auth.log", "Authentication", Permission.LOGS_VIEW_SECURITY),
    "secure": ("/var/log/secure", "Security", Permission.LOGS_VIEW_SECURITY),
    "kern": ("/var/log/kern.log", "Kernel", Permission.LOGS_VIEW_KERNEL),
    "daemon": ("/var/log/daemon.log", "Daemons", Permission.LOGS_VIEW_SYSTEM),
    "dpkg": ("/var/log/dpkg.log", "DPKG", Permission.LOGS_VIEW_SYSTEM),
    "apt-history": ("/var/log/apt/history.log", "APT history", Permission.LOGS_VIEW_SYSTEM),
    "apt-term": ("/var/log/apt/term.log", "APT terminal", Permission.LOGS_VIEW_SYSTEM),
    "yum": ("/var/log/yum.log", "YUM", Permission.LOGS_VIEW_SYSTEM),
    "dnf": ("/var/log/dnf.log", "DNF", Permission.LOGS_VIEW_SYSTEM),
    "audit": ("/var/log/audit/audit.log", "Linux audit", Permission.LOGS_VIEW_SECURITY),
    "nginx-access": ("/var/log/nginx/access.log", "Nginx access", Permission.LOGS_VIEW_SYSTEM),
    "nginx-error": ("/var/log/nginx/error.log", "Nginx errors", Permission.LOGS_VIEW_SYSTEM),
}


def infer_effective_priority(message: object, original_priority: object, fields: dict[str, Any] | None = None) -> tuple[int, str | None]:
    """Return a content-aware priority without ever weakening the source priority."""
    priority = _int(original_priority)
    priority = priority if priority in LOG_PRIORITIES else 6
    text = str(message or "")
    relevant_fields = fields if isinstance(fields, dict) else {}
    for key in ("TRACEBACK", "STACKTRACE", "EXCEPTION", "ERROR"):
        value = relevant_fields.get(key)
        if isinstance(value, str) and value:
            text = f"{text}\n{value}"
    inferred: int | None = None
    reason: str | None = None
    signal_text = BENIGN_ERROR_RE.sub("", text)
    if PYTHON_TRACEBACK_RE.search(text):
        inferred, reason = 3, "python_traceback"
    elif PYTHON_EXCEPTION_RE.search(text):
        inferred, reason = 3, "python_exception"
    elif ERROR_SIGNAL_RE.search(signal_text) or UPPERCASE_ERROR_RE.search(signal_text):
        inferred, reason = 3, "error_signal"
    effective = min(priority, inferred) if inferred is not None else priority
    return effective, reason if effective < priority else None


class LogEntry(BaseModel):
    id: str
    timestamp: str | None = None
    original_priority: int | None = None
    original_severity: str | None = None
    priority: int = 6
    severity: str = "info"
    severity_inferred: bool = False
    severity_reason: str | None = None
    source: str
    unit: str = ""
    identifier: str = ""
    hostname: str = ""
    pid: int | None = None
    uid: int | None = None
    message: str
    cursor: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def effective_severity(self) -> "LogEntry":
        original = self.original_priority if self.original_priority in LOG_PRIORITIES else self.priority
        original = original if original in LOG_PRIORITIES else 6
        effective, reason = infer_effective_priority(self.message, original, self.fields)
        self.original_priority = original
        self.original_severity = LOG_PRIORITIES[original]
        self.priority = effective
        self.severity = LOG_PRIORITIES[effective]
        self.severity_inferred = effective < original
        self.severity_reason = reason if self.severity_inferred else None
        return self


class SavedViewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    source: str = Field(default="journal", max_length=180)
    query: str = Field(default="", max_length=500)
    filters: dict[str, str | int | bool | list[int]] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=lambda: ["timestamp", "severity", "source", "unit", "pid", "hostname", "message"], max_length=16)
    sort: Literal["newest", "oldest"] = "newest"
    view_mode: Literal["compact", "table"] = "compact"

    @field_validator("source")
    @classmethod
    def valid_source(cls, value: str) -> str:
        if not SOURCE_RE.fullmatch(value):
            raise ValueError("invalid log source")
        return value

    @field_validator("columns")
    @classmethod
    def valid_columns(cls, values: list[str]) -> list[str]:
        allowed = {"timestamp", "severity", "source", "unit", "identifier", "pid", "uid", "hostname", "message"}
        if len(values) != len(set(values)) or any(value not in allowed for value in values):
            raise ValueError("invalid log columns")
        return values

    @field_validator("filters")
    @classmethod
    def valid_filters(cls, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "priority", "unit", "pid", "uid", "identifier", "transport", "boot_id",
            "container_id", "since", "until", "case_sensitive", "regex", "negate",
            "message_only", "hostname", "device", "username", "group",
        }
        if any(key not in allowed for key in values) or len(json.dumps(values)) > 8000:
            raise ValueError("invalid saved log filters")
        return values


class SavedView(SavedViewPayload):
    id: str
    builtin: bool = False


class ExportRequest(BaseModel):
    format: Literal["txt", "json", "jsonl", "csv"]
    source: str = Field(default="journal", max_length=180)
    query: str = Field(default="", max_length=500)
    regex: bool = False
    case_sensitive: bool = False
    negate: bool = False
    message_only: bool = False
    priority: list[int] = Field(default_factory=list, max_length=8)
    unit: str = Field(default="", max_length=128)
    pid: int | None = Field(default=None, ge=0)
    uid: int | None = Field(default=None, ge=0)
    identifier: str = Field(default="", max_length=128)
    transport: str = Field(default="", max_length=64)
    hostname: str = Field(default="", max_length=253)
    device: str = Field(default="", max_length=128)
    username: str = Field(default="", max_length=32)
    group: str = Field(default="", max_length=32)
    boot_id: str = Field(default="", max_length=32)
    container_id: str = Field(default="", max_length=128)
    since: float | None = Field(default=None, ge=0)
    until: float | None = Field(default=None, ge=0)
    limit: int = Field(default=1000, ge=1, le=MAX_EXPORT)

    @model_validator(mode="after")
    def valid_range(self) -> "ExportRequest":
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("since must be before until")
        return self


def _current_user(request: Request) -> SessionUser:
    return get_session_user(request)


def _mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def _run_bounded(args: list[str], *, timeout: float = 12, max_bytes: int = MAX_COMMAND_BYTES) -> tuple[int, str, str]:
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
    except OSError as error:
        raise HTTPException(503, "The log source is unavailable") from error
    output = [bytearray(), bytearray()]
    overflow = threading.Event()

    def drain(index: int, stream: Any, limit: int) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = limit - len(output[index])
            if remaining > 0:
                output[index].extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return

    readers = [
        threading.Thread(target=drain, args=(0, process.stdout, max_bytes), daemon=True),
        threading.Thread(target=drain, args=(1, process.stderr, 64 * 1024), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise HTTPException(504, "The log source did not respond in time") from error
    finally:
        for reader in readers:
            reader.join(timeout=1)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
    if overflow.is_set():
        raise HTTPException(413, "The log source exceeded the response safety limit")
    stdout = bytes(output[0]).decode("utf-8", errors="replace")
    stderr = bytes(output[1]).decode("utf-8", errors="replace")
    return code, stdout, redact_text(stderr, limit=64 * 1024)


def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in list(fields.items())[:120]:
        normalized_key = str(key)[:128]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = redact_text(value, limit=MAX_FIELD_VALUE) if isinstance(value, str) else value
    return redact(safe)


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


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
        fields=_safe_fields(fields),
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
        fields = _safe_fields(value)
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
    """Merge safe, adjacent Python traceback records while preserving source order."""
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
            if (
                _traceback_context(candidate) != context
                or not _traceback_continuation(candidate.message)
            ):
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
            {
                "id": item.id,
                "timestamp": item.timestamp,
                "original_priority": item.original_priority,
                "message": redact_text(item.message, limit=MAX_MESSAGE),
            }
            for item in candidates
        ]
        stable = hashlib.sha256(
            ("traceback|" + "|".join(item.id for item in candidates)).encode("utf-8", errors="replace")
        ).hexdigest()
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


def _encode_cursor(source: str, timestamp: str | None, cursor: str = "", offset: int | None = None) -> str:
    raw = json.dumps({"source": source, "timestamp": timestamp, "cursor": cursor, "offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str, source: str) -> dict[str, str]:
    if not value:
        return {}
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(400, "Invalid continuation token") from error
    if not isinstance(data, dict) or data.get("source") != source:
        raise HTTPException(400, "Continuation token does not match the source")
    return {str(key): str(item) for key, item in data.items() if item is not None}


def _validate_regex(query: str) -> re.Pattern[str]:
    if len(query) > MAX_REGEX_LENGTH:
        raise HTTPException(400, f"Regular expression can contain at most {MAX_REGEX_LENGTH} characters")
    if UNSAFE_REGEX_RE.search(query):
        raise HTTPException(400, "The regular expression is too expensive")
    try:
        return re.compile(query)
    except re.error as error:
        raise HTTPException(400, f"Invalid regular expression: {error.msg}") from error


def _matches(entry: LogEntry, *, query: str, regex: bool, case_sensitive: bool, negate: bool, message_only: bool) -> bool:
    if not query:
        return True
    haystack = (entry.message if message_only else f"{entry.message}\n{entry.unit}\n{entry.identifier}\n{entry.hostname}\n{json.dumps(entry.fields, ensure_ascii=False)}")[:64 * 1024]
    if regex:
        pattern = _validate_regex(query if case_sensitive else query.casefold())
        found = pattern.search(haystack if case_sensitive else haystack.casefold()) is not None
    else:
        needle = query if case_sensitive else query.casefold()
        target = haystack if case_sensitive else haystack.casefold()
        phrases = re.findall(r'"([^"]+)"|(\S+)', needle)
        terms = [first or second for first, second in phrases]
        found = all(term in target for term in terms)
    return not found if negate else found


def _permission_for_source(source: str) -> Permission:
    if source in {"kernel", "dmesg"} or source.startswith("file:kern"):
        return Permission.LOGS_VIEW_KERNEL
    if source.startswith("service:"):
        return Permission.LOGS_VIEW_SERVICES
    if source.startswith("container:"):
        return Permission.LOGS_VIEW_CONTAINERS
    if source in {"activity-own"}:
        return Permission.LOGS_VIEW_OWN
    if source in {"webnas", "activity", "packages"} or source.startswith("webnas-file:"):
        return Permission.LOGS_VIEW_WEBNAS
    if source.startswith(("file:auth", "file:secure", "file:audit")):
        return Permission.LOGS_VIEW_SECURITY
    return Permission.LOGS_VIEW_SYSTEM


def _security_entry(entry: LogEntry) -> bool:
    marker = f"{entry.unit} {entry.identifier}".casefold()
    identifiers = {"sshd", "ssh", "sudo", "su", "login", "polkitd", "audit", "auditd", "pam"}
    return (
        any(token in marker for token in identifiers)
        or str(entry.fields.get("SYSLOG_FACILITY", "")) in {"4", "10"}
        or "_AUDIT_TYPE" in entry.fields
        or "AUDIT_TYPE" in entry.fields
    )


def _has_log_permission(user: SessionUser, permission: Permission) -> bool:
    if has_permission(user.username, permission):
        return True
    return permission in {Permission.LOGS_VIEW_SYSTEM, Permission.LOGS_VIEW_KERNEL, Permission.LOGS_VIEW_SERVICES, Permission.LOGS_VIEW_WEBNAS} and has_permission(user.username, Permission.SYSTEM_LOGS)


def _authorize_source(user: SessionUser, source: str) -> None:
    permission = _permission_for_source(source)
    if not _has_log_permission(user, permission):
        authorize(user, permission)
    if source == "activity" and not has_permission(user.username, Permission.AUDIT_VIEW_ALL):
        raise HTTPException(403, "Global Activity Center access is required")


def _source_known(source: str) -> bool:
    return (
        source in {"journal", "current-boot", "kernel", "dmesg", "webnas", "activity", "activity-own", "packages"}
        or (source.startswith("service:") and UNIT_RE.fullmatch(source.removeprefix("service:")) is not None)
        or (source.startswith("container:") and CONTAINER_RE.fullmatch(source.removeprefix("container:")) is not None)
        or source in _available_files()
    )


def _available_files() -> dict[str, tuple[Path, str, Permission]]:
    result: dict[str, tuple[Path, str, Permission]] = {}
    for key, (raw, label, permission) in CLASSIC_LOGS.items():
        path = Path(raw)
        if path.is_file():
            result[f"file:{key}"] = (path, label, permission)
        for index in range(1, 6):
            rotated = Path(f"{raw}.{index}")
            compressed = Path(f"{raw}.{index}.gz")
            if rotated.is_file():
                result[f"file:{key}@{index}"] = (rotated, f"{label} · {index}", permission)
            if compressed.is_file():
                result[f"file:{key}@{index}.gz"] = (compressed, f"{label} · {index}.gz", permission)
    samba = Path("/var/log/samba")
    if samba.is_dir():
        for path in sorted(samba.glob("log.*"))[:100]:
            if path.is_file() and not path.is_symlink() and re.fullmatch(r"log\.[A-Za-z0-9_.-]{1,100}(?:\.\d+)?(?:\.gz)?", path.name):
                result[f"file:samba/{path.name}"] = (path, f"Samba · {path.name}", Permission.LOGS_VIEW_SYSTEM)
    log_dir = Path(get_config().paths.log_dir)
    if log_dir.is_dir():
        for path in sorted(log_dir.glob("*.log"))[:100]:
            if path.is_file() and not path.is_symlink() and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}\.log", path.name):
                result[f"webnas-file:{path.name}"] = (path, f"WebNAS · {path.name}", Permission.LOGS_VIEW_WEBNAS)
    return result


def _read_tail(path: Path, max_lines: int) -> list[str]:
    started = time.monotonic()
    if path.suffix == ".gz":
        if path.stat().st_size > 64 * 1024 * 1024:
            raise HTTPException(413, "Compressed log file is too large")
        output = bytearray()
        try:
            with gzip.open(path, "rb") as handle:
                while len(output) <= 4 * 1024 * 1024 and time.monotonic() - started < 3:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    output.extend(chunk)
        except (OSError, EOFError) as error:
            raise HTTPException(422, "Compressed log file could not be read") from error
        return output.decode("utf-8", errors="replace").splitlines()[-max_lines:]
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        block = min(size, 2 * 1024 * 1024)
        handle.seek(max(0, size - block))
        data = handle.read(block)
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > block and lines:
        lines = lines[1:]
    return lines[-max_lines:]


def _file_entries(source: str, limit: int) -> list[LogEntry]:
    available = _available_files()
    if source not in available:
        raise HTTPException(404, "Log file source is unavailable")
    path, _, _ = available[source]
    entries: list[LogEntry] = []
    for index, line in enumerate(reversed(_read_tail(path, min(limit, 5000)))):
        message = redact_text(line, limit=MAX_MESSAGE)
        stable = hashlib.sha256(f"{path.name}|{path.stat().st_ino}|{index}|{message}".encode()).hexdigest()
        entries.append(LogEntry(id=stable, source=source, identifier=path.name, message=message, fields={"file": path.name, "line_from_end": index + 1}))
    return entries


def _journal_entries(
    source: str,
    *,
    limit: int,
    priority: list[int],
    unit: str,
    pid: int | None,
    uid: int | None,
    identifier: str,
    transport: str,
    hostname: str,
    device: str,
    username: str,
    group: str,
    boot_id: str,
    since: float | None,
    until: float | None,
    continuation: dict[str, str],
    direction: str,
) -> list[LogEntry]:
    executable = shutil.which("journalctl")
    if not executable:
        raise HTTPException(503, "journalctl is not installed")
    args = [executable, "--output=json", "--no-pager", "-n", str(min(5000, max(limit * 5, limit + 1)))]
    if direction == "older":
        args.append("--reverse")
    selected_unit = "webnas.service" if source == "webnas" else source.removeprefix("service:") if source.startswith("service:") else unit
    if selected_unit:
        if not UNIT_RE.fullmatch(selected_unit):
            raise HTTPException(400, "Invalid systemd unit")
        args.extend(["--unit", selected_unit])
    if source in {"kernel", "dmesg"}:
        args.append("--dmesg")
    if source == "current-boot":
        args.extend(["--boot", "0"])
    if priority:
        if any(value not in LOG_PRIORITIES for value in priority):
            raise HTTPException(400, "Invalid log priority")
    if pid is not None:
        args.append(f"_PID={pid}")
    if uid is not None:
        args.append(f"_UID={uid}")
    if identifier:
        if not IDENTIFIER_RE.fullmatch(identifier):
            raise HTTPException(400, "Invalid syslog identifier")
        args.append(f"SYSLOG_IDENTIFIER={identifier}")
    if transport:
        if not IDENTIFIER_RE.fullmatch(transport):
            raise HTTPException(400, "Invalid journal transport")
        args.append(f"_TRANSPORT={transport}")
    if hostname:
        if not HOST_RE.fullmatch(hostname):
            raise HTTPException(400, "Invalid hostname")
        args.append(f"_HOSTNAME={hostname}")
    if device:
        if not IDENTIFIER_RE.fullmatch(device):
            raise HTTPException(400, "Invalid kernel device")
        args.append(f"_KERNEL_DEVICE={device}")
    if username:
        if not ACCOUNT_RE.fullmatch(username):
            raise HTTPException(400, "Invalid username")
        try:
            args.append(f"_UID={pwd.getpwnam(username).pw_uid}")
        except KeyError as error:
            raise HTTPException(400, "Unknown username") from error
    if group:
        if not ACCOUNT_RE.fullmatch(group):
            raise HTTPException(400, "Invalid group")
        try:
            args.append(f"_GID={grp.getgrnam(group).gr_gid}")
        except KeyError as error:
            raise HTTPException(400, "Unknown group") from error
    if boot_id:
        if not BOOT_RE.fullmatch(boot_id):
            raise HTTPException(400, "Invalid boot identifier")
        args.append(f"_BOOT_ID={boot_id.lower()}")
    if since is not None:
        args.extend(["--since", f"@{since:.3f}"])
    if until is not None:
        args.extend(["--until", f"@{until:.3f}"])
    if continuation.get("timestamp"):
        try:
            marker = datetime.fromisoformat(continuation["timestamp"]).timestamp()
        except ValueError as error:
            raise HTTPException(400, "Invalid continuation timestamp") from error
        args.extend(["--until" if direction == "older" else "--since", f"@{marker:.6f}"])
    code, stdout, stderr = _run_bounded(args)
    if code != 0:
        if "permission" in stderr.casefold() or "access" in stderr.casefold():
            raise HTTPException(403, "The WebNAS service cannot read this journal")
        raise HTTPException(502, stderr.strip() or "journalctl could not read logs")
    return [entry for entry in (parse_journal_record(line) for line in stdout.splitlines()) if entry]


def _dmesg_entries(limit: int) -> list[LogEntry]:
    executable = shutil.which("dmesg")
    if not executable:
        raise HTTPException(503, "dmesg is not installed")
    code, stdout, stderr = _run_bounded([executable, "--json"], timeout=8)
    if code != 0:
        code, stdout, stderr = _run_bounded([executable, "--time-format", "iso"], timeout=8)
    if code != 0:
        raise HTTPException(403 if "permission" in stderr.casefold() else 502, stderr or "dmesg could not be read")
    return [entry for entry in (parse_dmesg_record(line) for line in stdout.splitlines()) if entry][-limit:][::-1]


def _activity_entries(user: SessionUser, global_scope: bool, limit: int, since: float | None, until: float | None) -> list[LogEntry]:
    events, _ = activity_repository().list(actor=None if global_scope else user.username, since=since, until=until, page=1, page_size=min(limit, 1000))
    return [
        LogEntry(
            id=f"activity:{event.id}",
            timestamp=datetime.fromtimestamp(event.created_at, UTC).isoformat(timespec="milliseconds"),
            priority=3 if event.status == ActivityStatus.failure else 6,
            severity="error" if event.status == ActivityStatus.failure else "info",
            source="activity",
            identifier=event.source,
            message=redact_text(event.summary or f"{event.action}: {event.target}", limit=MAX_MESSAGE),
            fields=_safe_fields(event.model_dump(mode="json")),
        )
        for event in events
    ]


def _container_entries(source: str, limit: int, since: float | None, until: float | None) -> list[LogEntry]:
    target = source.removeprefix("container:")
    if not CONTAINER_RE.fullmatch(target):
        raise HTTPException(400, "Invalid container identifier")
    docker = shutil.which("docker")
    if not docker:
        raise HTTPException(503, "Docker is not installed")
    args = [docker, "logs", "--timestamps", "--tail", str(min(limit, 1000))]
    if since is not None:
        args.extend(["--since", datetime.fromtimestamp(since, UTC).isoformat()])
    if until is not None:
        args.extend(["--until", datetime.fromtimestamp(until, UTC).isoformat()])
    args.append(target)
    code, stdout, stderr = _run_bounded(args, timeout=15)
    if code != 0:
        raise HTTPException(502, stderr or "Container logs could not be read")
    entries = []
    output = stdout if not stderr else f"{stdout}\n{stderr}"
    for index, line in enumerate(reversed(output.splitlines())):
        timestamp, _, message = line.partition(" ")
        stable = hashlib.sha256(f"{target}|{timestamp}|{index}|{message}".encode()).hexdigest()
        entries.append(LogEntry(id=stable, timestamp=timestamp or None, source=source, identifier=target, message=redact_text(message or line, limit=MAX_MESSAGE), fields={"container": target}))
    return entries


def _package_entries(limit: int) -> list[LogEntry]:
    from .package_center.service import repository

    entries: list[LogEntry] = []
    try:
        jobs = repository().list_jobs(limit=min(200, max(20, limit)))
    except Exception as error:
        raise HTTPException(503, "Package Center history is unavailable") from error
    for job in jobs:
        for line in reversed(job.get("log_tail") or []):
            created_at = float(line.get("created_at") or job.get("created_at") or 0)
            timestamp = datetime.fromtimestamp(created_at, UTC).isoformat(timespec="milliseconds") if created_at else None
            message = redact_text(line.get("line") or "", limit=MAX_MESSAGE)
            identifier = str(job.get("module_id") or "package-center")[:128]
            stable = f"package:{job.get('id')}:{line.get('id') or hashlib.sha256(message.encode()).hexdigest()}"
            entries.append(LogEntry(
                id=stable, timestamp=timestamp, priority=3 if str(line.get("stream")) == "stderr" or job.get("status") == "failed" else 6,
                severity="error" if str(line.get("stream")) == "stderr" or job.get("status") == "failed" else "info",
                source="packages", identifier=identifier, message=message,
                fields=_safe_fields({"job_id": job.get("id"), "module_id": job.get("module_id"), "action": job.get("action"), "status": job.get("status"), "stream": line.get("stream"), "actor": job.get("created_by")}),
            ))
            if len(entries) >= limit:
                return entries
    return entries


def query_entries(
    user: SessionUser,
    *,
    source: str,
    query: str = "",
    regex: bool = False,
    case_sensitive: bool = False,
    negate: bool = False,
    message_only: bool = False,
    priority: list[int] | None = None,
    unit: str = "",
    pid: int | None = None,
    uid: int | None = None,
    identifier: str = "",
    transport: str = "",
    hostname: str = "",
    device: str = "",
    username: str = "",
    group: str = "",
    boot_id: str = "",
    container_id: str = "",
    since: float | None = None,
    until: float | None = None,
    cursor: str = "",
    direction: str = "older",
    limit: int = 200,
) -> dict[str, Any]:
    source = source.strip() or "journal"
    if not SOURCE_RE.fullmatch(source):
        raise HTTPException(400, "Invalid log source")
    if container_id:
        source = f"container:{container_id}"
    if not _source_known(source):
        raise HTTPException(404, "Unknown or unavailable log source")
    _authorize_source(user, source)
    if since is not None and until is not None and since > until:
        raise HTTPException(400, "Start time must be before end time")
    if query and regex:
        _validate_regex(query)
    continuation = _decode_cursor(cursor, source)
    fetch_limit = min(5000, max(limit * 5, limit + 1))
    journal_source = source in {"journal", "current-boot", "kernel", "webnas"} or source.startswith("service:")
    try:
        offset = max(0, int(continuation.get("offset", "0"))) if not journal_source else 0
    except ValueError as error:
        raise HTTPException(400, "Invalid continuation offset") from error
    provider_limit = fetch_limit if journal_source else 5000
    if source.startswith(("file:", "webnas-file:")):
        entries = _file_entries(source, provider_limit)
    elif source == "dmesg":
        entries = _dmesg_entries(provider_limit)
    elif source in {"activity", "activity-own"}:
        entries = _activity_entries(user, source == "activity", provider_limit, since, until)
    elif source.startswith("container:"):
        entries = _container_entries(source, provider_limit, since, until)
    elif source == "packages":
        entries = _package_entries(provider_limit)
    else:
        entries = _journal_entries(
            source, limit=fetch_limit, priority=priority or [], unit=unit, pid=pid, uid=uid,
            identifier=identifier, transport=transport, hostname=hostname, device=device, username=username, group=group,
            boot_id=boot_id, since=since, until=until,
            continuation=continuation, direction=direction,
        )
    entries = group_traceback_entries(entries)
    if not has_permission(user.username, Permission.LOGS_VIEW_SECURITY):
        entries = [item for item in entries if not _security_entry(item)]
    filtered: list[LogEntry] = []
    search_started = time.monotonic()
    for item in entries:
        if time.monotonic() - search_started > 0.5:
            raise HTTPException(408, "Log search exceeded its execution limit")
        if (not priority or item.priority in priority) and _matches(item, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate, message_only=message_only):
            filtered.append(item)
    selected = filtered[offset : offset + limit + 1]
    has_more = len(selected) > limit
    selected = selected[:limit]
    encoded_size = 0
    bounded: list[LogEntry] = []
    for item in selected:
        size = len(item.model_dump_json().encode())
        if encoded_size + size > MAX_RESPONSE_BYTES:
            has_more = True
            break
        bounded.append(item)
        encoded_size += size
    marker = bounded[-1] if bounded else None
    return {
        "items": [item.model_dump(mode="json") for item in bounded],
        "next_cursor": _encode_cursor(source, marker.timestamp, marker.cursor, offset + len(bounded) if not journal_source else None) if marker and has_more else None,
        "has_more": has_more,
        "direction": direction,
        "limit": limit,
        "truncated": len(bounded) < len(selected),
    }


@router.get("/sources")
def log_sources(user: SessionUser = Depends(_current_user)):
    groups: list[dict[str, Any]] = []

    def add(group: str, identifier: str, label: str, permission: Permission, available: bool, status: str = "available") -> None:
        if not _has_log_permission(user, permission):
            return
        target = next((item for item in groups if item["id"] == group), None)
        if target is None:
            target = {"id": group, "label": group, "items": []}
            groups.append(target)
        target["items"].append({"id": identifier, "label": label, "available": available, "status": status, "permission": permission.value})

    journal = shutil.which("journalctl") is not None
    add("journal", "journal", "System journal", Permission.LOGS_VIEW_SYSTEM, journal, "available" if journal else "missing_program")
    add("journal", "current-boot", "Current boot", Permission.LOGS_VIEW_SYSTEM, journal, "available" if journal else "missing_program")
    add("kernel", "kernel", "Kernel journal", Permission.LOGS_VIEW_KERNEL, journal, "available" if journal else "missing_program")
    add("kernel", "dmesg", "dmesg", Permission.LOGS_VIEW_KERNEL, shutil.which("dmesg") is not None, "available" if shutil.which("dmesg") else "missing_program")
    add("webnas", "webnas", "WebNAS service", Permission.LOGS_VIEW_WEBNAS, journal, "available" if journal else "missing_program")
    add("webnas", "activity-own", "My Activity Center", Permission.LOGS_VIEW_OWN, True)
    add("webnas", "activity", "Activity Center", Permission.LOGS_VIEW_WEBNAS, has_permission(user.username, Permission.AUDIT_VIEW_ALL), "available" if has_permission(user.username, Permission.AUDIT_VIEW_ALL) else "permission_denied")
    add("packages", "packages", "Packages and modules", Permission.LOGS_VIEW_WEBNAS, True)
    if _has_log_permission(user, Permission.LOGS_VIEW_SERVICES):
        groups.append({"id": "services", "label": "services", "items": []})
    for identifier, (path, label, permission) in _available_files().items():
        add("files" if identifier.startswith("file:") else "webnas", identifier, label, permission, path.is_file())
    docker = shutil.which("docker") is not None
    if has_permission(user.username, Permission.LOGS_VIEW_CONTAINERS):
        groups.append({"id": "containers", "label": "containers", "items": [] if docker else [{"id": "containers-unavailable", "label": "Docker containers", "available": False, "status": "missing_program", "permission": Permission.LOGS_VIEW_CONTAINERS.value}]})
    return {"groups": groups, "capabilities": {"journal": journal, "docker": docker, "live": has_permission(user.username, Permission.LOGS_LIVE), "export": has_permission(user.username, Permission.LOGS_EXPORT)}}


@router.get("/entries")
def log_entries(
    source: str = Query(default="journal", max_length=180),
    query: str = Query(default="", max_length=500),
    regex: bool = False,
    case_sensitive: bool = False,
    negate: bool = False,
    message_only: bool = False,
    priority: list[int] = Query(default=[]),
    unit: str = Query(default="", max_length=128),
    pid: int | None = Query(default=None, ge=0),
    uid: int | None = Query(default=None, ge=0),
    identifier: str = Query(default="", max_length=128),
    transport: str = Query(default="", max_length=64),
    hostname: str = Query(default="", max_length=253),
    device: str = Query(default="", max_length=128),
    username: str = Query(default="", max_length=32),
    group: str = Query(default="", max_length=32),
    boot_id: str = Query(default="", max_length=32),
    container_id: str = Query(default="", max_length=128),
    since: float | None = Query(default=None, ge=0),
    until: float | None = Query(default=None, ge=0),
    cursor: str = Query(default="", max_length=4096),
    direction: Literal["older", "newer"] = "older",
    limit: int = Query(default=200, ge=1, le=1000),
    user: SessionUser = Depends(_current_user),
):
    result = query_entries(
        user, source=source, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate,
        message_only=message_only, priority=priority, unit=unit, pid=pid, uid=uid, identifier=identifier,
        transport=transport, hostname=hostname, device=device, username=username, group=group,
        boot_id=boot_id, container_id=container_id, since=since, until=until,
        cursor=cursor, direction=direction, limit=limit,
    )
    record_activity(ActivityCategory.administration, "logs_view", user.username, status=ActivityStatus.info, details={"source": source, "count": len(result["items"]), "filtered": bool(query or priority or unit or pid is not None or uid is not None or identifier or transport or hostname or device or username or group)}, source="logs")
    return result


def _normalize_boot_record(value: dict[str, Any]) -> dict[str, Any] | None:
    raw_boot_id = value.get("boot_id") or value.get("boot-id") or value.get("bootId")
    boot_id = raw_boot_id if isinstance(raw_boot_id, str) else ""
    if not BOOT_RE.fullmatch(boot_id):
        return None
    raw_index = _int(value.get("index"))
    index = raw_index if raw_index is not None else 0
    first = value.get("first_entry") if "first_entry" in value else value.get("first")
    last = value.get("last_entry") if "last_entry" in value else value.get("last")
    first_value = first if isinstance(first, (str, int, float)) and not isinstance(first, bool) else None
    last_value = last if isinstance(last, (str, int, float)) and not isinstance(last, bool) else None
    first_number, last_number = _int(first_value), _int(last_value)
    duration = (
        max(0, (last_number - first_number) / 1_000_000)
        if first_number is not None and last_number is not None
        else None
    )
    return {
        "id": boot_id,
        "index": index,
        "first": first_value,
        "last": last_value,
        "duration_seconds": duration,
        "current": index == 0,
    }


def parse_journal_boots(stdout: str) -> list[dict[str, Any]]:
    """Parse all JSON shapes emitted by different journalctl releases."""
    records: list[dict[str, Any]] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            records.append(value)
        elif isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))

    stripped = stdout.strip()
    if not stripped:
        return []
    try:
        collect(json.loads(stripped))
    except (TypeError, json.JSONDecodeError):
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                collect(json.loads(line))
            except (TypeError, json.JSONDecodeError):
                continue
    return [item for item in (_normalize_boot_record(record) for record in records) if item is not None]


def parse_journal_boots_text(stdout: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        match = re.match(r"\s*(-?\d+)\s+([a-fA-F0-9]{32})\s+(.*?)\s+(?:—|--)\s+(.*?)\s*$", line)
        if not match:
            continue
        index = int(match.group(1))
        items.append({
            "index": index,
            "id": match.group(2),
            "first": match.group(3),
            "last": match.group(4),
            "duration_seconds": None,
            "current": index == 0,
        })
    return items


@router.get("/boots")
def log_boots(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_SYSTEM)
    executable = shutil.which("journalctl")
    if not executable:
        return {"items": [], "status": "missing_program"}
    code, stdout, _ = _run_bounded([executable, "--list-boots", "--no-pager", "--output=json"], timeout=8)
    parsed_items = parse_journal_boots(stdout) if code == 0 else []
    if parsed_items:
        return {"items": parsed_items, "status": "available", "error": ""}
    code, stdout, _ = _run_bounded([executable, "--list-boots", "--no-pager"], timeout=8)
    parsed_items = parse_journal_boots_text(stdout) if code == 0 else []
    return {
        "items": parsed_items,
        "status": "available" if code == 0 else "error",
        "error": "" if code == 0 else "journalctl could not list system boots",
    }


@router.get("/services")
def log_services(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_SERVICES)
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {"items": [], "status": "missing_program"}
    code, stdout, stderr = _run_bounded([systemctl, "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"], timeout=10)
    items = []
    for line in stdout.splitlines()[:2000]:
        parts = line.split(None, 4)
        if len(parts) >= 4 and UNIT_RE.fullmatch(parts[0]):
            items.append({"unit": parts[0], "load": parts[1], "active": parts[2], "sub": parts[3], "description": parts[4] if len(parts) > 4 else ""})
    return {"items": items, "status": "available" if code == 0 else "error", "error": "" if code == 0 else stderr}


@router.get("/services/{unit}")
def log_service(unit: str, user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_SERVICES)
    if not UNIT_RE.fullmatch(unit):
        raise HTTPException(400, "Invalid systemd unit")
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise HTTPException(503, "systemctl is not installed")
    properties = "Id,Description,ActiveState,SubState,MainPID,ActiveEnterTimestamp"
    code, stdout, stderr = _run_bounded([systemctl, "show", unit, f"--property={properties}", "--no-pager"], timeout=8)
    if code != 0:
        raise HTTPException(404, stderr or "Systemd unit was not found")
    values = dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)
    recent = query_entries(user, source=f"service:{unit}", limit=20)
    return {"unit": unit, "description": values.get("Description", ""), "active": values.get("ActiveState", ""), "sub": values.get("SubState", ""), "pid": _int(values.get("MainPID")), "started_at": values.get("ActiveEnterTimestamp", ""), "entries": recent["items"]}


@router.get("/containers")
def log_containers(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_CONTAINERS)
    docker = shutil.which("docker")
    if not docker:
        return {"items": [], "status": "missing_program"}
    code, stdout, stderr = _run_bounded([docker, "ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=10)
    items = []
    for line in stdout.splitlines()[:1000]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        identifier = str(value.get("ID") or "")
        name = str(value.get("Names") or "")
        if CONTAINER_RE.fullmatch(identifier) and CONTAINER_RE.fullmatch(name):
            items.append({"id": identifier, "name": name, "image": str(value.get("Image") or ""), "state": str(value.get("State") or ""), "status": str(value.get("Status") or "")})
    return {"items": items, "status": "available" if code == 0 else "error", "error": "" if code == 0 else stderr}


@router.get("/fields")
def log_fields(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_OWN)
    return {"items": ["MESSAGE", "PRIORITY", "_SYSTEMD_UNIT", "_SYSTEMD_USER_UNIT", "_PID", "_UID", "_GID", "_HOSTNAME", "SYSLOG_IDENTIFIER", "_TRANSPORT", "_BOOT_ID", "_EXE", "_CMDLINE", "_KERNEL_DEVICE", "__CURSOR"]}


@router.get("/stream")
async def log_stream(
    request: Request,
    source: str = Query(default="journal", max_length=180),
    query: str = Query(default="", max_length=500),
    regex: bool = False,
    case_sensitive: bool = False,
    negate: bool = False,
    message_only: bool = False,
    priority: list[int] = Query(default=[]),
    unit: str = Query(default="", max_length=128),
    pid: int | None = Query(default=None, ge=0),
    uid: int | None = Query(default=None, ge=0),
    identifier: str = Query(default="", max_length=128),
    transport: str = Query(default="", max_length=64),
    hostname: str = Query(default="", max_length=253),
    device: str = Query(default="", max_length=128),
    username: str = Query(default="", max_length=32),
    group: str = Query(default="", max_length=32),
    boot_id: str = Query(default="", max_length=32),
    container_id: str = Query(default="", max_length=128),
    user: SessionUser = Depends(_current_user),
):
    authorize(user, Permission.LOGS_LIVE)
    _authorize_source(user, source)
    record_activity(ActivityCategory.administration, "logs_live_start", user.username, status=ActivityStatus.info, details={"source": source, "filtered": bool(query or priority or unit or pid is not None or uid is not None or identifier or transport or hostname or device or username or group or boot_id or container_id)}, source="logs")

    async def events():
        seen: set[str] = set()
        try:
            initial = await asyncio.to_thread(query_entries, user, source=source, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate, message_only=message_only, priority=priority, unit=unit, pid=pid, uid=uid, identifier=identifier, transport=transport, hostname=hostname, device=device, username=username, group=group, boot_id=boot_id, container_id=container_id, limit=100, direction="newer")
            for item in reversed(initial["items"]):
                seen.add(item["id"])
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                await asyncio.sleep(1.25)
                result = await asyncio.to_thread(query_entries, user, source=source, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate, message_only=message_only, priority=priority, unit=unit, pid=pid, uid=uid, identifier=identifier, transport=transport, hostname=hostname, device=device, username=username, group=group, boot_id=boot_id, container_id=container_id, limit=100, direction="newer")
                fresh = [item for item in reversed(result["items"]) if item["id"] not in seen]
                for item in fresh:
                    seen.add(item["id"])
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if len(seen) > 2000:
                    seen = set(list(seen)[-1000:])
                if not fresh:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return
        except Exception:
            yield "event: source-error\ndata: {\"error\":\"Log stream is temporarily unavailable\"}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/export")
def log_export(payload: ExportRequest, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_EXPORT)
    result = query_entries(
        user, source=payload.source, query=payload.query, regex=payload.regex, case_sensitive=payload.case_sensitive,
        negate=payload.negate, message_only=payload.message_only, priority=payload.priority, unit=payload.unit,
        pid=payload.pid, uid=payload.uid, identifier=payload.identifier, transport=payload.transport,
        hostname=payload.hostname, device=payload.device, username=payload.username, group=payload.group,
        boot_id=payload.boot_id, container_id=payload.container_id, since=payload.since, until=payload.until,
        limit=payload.limit,
    )
    items = result["items"]
    if payload.format == "json":
        content = json.dumps({"items": items, "truncated": result["has_more"]}, ensure_ascii=False, indent=2)
        media = "application/json"
    elif payload.format == "jsonl":
        content = "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n"
        media = "application/x-ndjson"
    elif payload.format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "timestamp", "priority", "severity", "original_priority", "original_severity",
                "severity_inferred", "severity_reason", "source", "unit", "identifier", "pid",
                "uid", "hostname", "message",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(items)
        content = output.getvalue()
        media = "text/csv"
    else:
        content = "\n".join(
            f"{item.get('timestamp') or '-'} "
            f"[{item['severity'].upper()} priority={item['priority']}; "
            f"original={item['original_severity']}/{item['original_priority']}"
            f"{'; inferred=' + str(item.get('severity_reason')) if item.get('severity_inferred') else ''}] "
            f"{item.get('unit') or item.get('identifier') or item['source']}: {item['message']}"
            for item in items
        ) + "\n"
        media = "text/plain"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"webnas-logs-{re.sub(r'[^a-z0-9-]', '-', payload.source.casefold())[:40]}-{stamp}.{payload.format}"
    record_activity(ActivityCategory.administration, "logs_export", user.username, status=ActivityStatus.info, details={"source": payload.source, "format": payload.format, "count": len(items), "truncated": result["has_more"]}, source="logs")
    return Response(content.encode("utf-8"), media_type=f"{media}; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-WebNAS-Truncated": str(result["has_more"]).lower()})


BUILTIN_VIEWS = [
    SavedView(id="my-activity", name="My activity", source="activity-own", builtin=True),
    SavedView(id="system-errors", name="System errors", source="journal", filters={"priority": [0, 1, 2, 3]}, builtin=True),
    SavedView(id="kernel-warnings", name="Kernel warnings", source="kernel", filters={"priority": [0, 1, 2, 3, 4]}, builtin=True),
    SavedView(id="failed-logins", name="Failed logins", source="journal", query="failed password", filters={"identifier": "sshd"}, builtin=True),
    SavedView(id="webnas", name="WebNAS", source="webnas", builtin=True),
    SavedView(id="packages", name="Packages and modules", source="packages", builtin=True),
    SavedView(id="docker", name="Docker", source="service:docker.service", builtin=True),
    SavedView(id="failed-services", name="Failed systemd services", source="journal", query="failed", builtin=True),
    SavedView(id="current-boot", name="Current boot", source="current-boot", builtin=True),
]


def _views_path(username: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", username)[:32]
    identity = hashlib.sha256(username.encode("utf-8", errors="replace")).hexdigest()[:16]
    directory = Path(get_config().paths.data_dir) / "settings" / "log_views"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory / f"{safe}-{identity}.json"


def _read_views(username: str) -> list[SavedView]:
    path = _views_path(username)
    if not path.exists():
        return []
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        return [SavedView.model_validate(value) for value in values[:50] if isinstance(value, dict)]
    except (OSError, ValueError):
        return []


def _write_views(username: str, values: list[SavedView]) -> None:
    path = _views_path(username)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps([item.model_dump(mode="json") for item in values], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


@router.get("/saved-views")
def saved_views(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_OWN)
    builtins = [
        item for item in BUILTIN_VIEWS
        if _has_log_permission(user, _permission_for_source(item.source))
        and (item.id != "failed-logins" or has_permission(user.username, Permission.LOGS_VIEW_SECURITY))
    ]
    return {"items": [item.model_dump(mode="json") for item in [*builtins, *_read_views(user.username)]]}


@router.post("/saved-views")
def create_saved_view(payload: SavedViewPayload, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_SAVED_VIEWS_MANAGE)
    if not _source_known(payload.source):
        raise HTTPException(400, "Unknown or unavailable log source")
    _authorize_source(user, payload.source)
    values = _read_views(user.username)
    if len(values) >= 50:
        raise HTTPException(409, "At most 50 saved log views are allowed")
    item = SavedView(id=uuid.uuid4().hex, **payload.model_dump())
    _write_views(user.username, [item, *values])
    record_activity(ActivityCategory.configuration, "logs_saved_view_create", user.username, details={"view_id": item.id}, source="logs")
    return item


@router.patch("/saved-views/{view_id}")
def update_saved_view(view_id: str, payload: SavedViewPayload, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_SAVED_VIEWS_MANAGE)
    if not _source_known(payload.source):
        raise HTTPException(400, "Unknown or unavailable log source")
    _authorize_source(user, payload.source)
    if not re.fullmatch(r"[a-f0-9]{32}", view_id):
        raise HTTPException(404, "Saved view not found")
    values = _read_views(user.username)
    if not any(item.id == view_id for item in values):
        raise HTTPException(404, "Saved view not found")
    updated = SavedView(id=view_id, **payload.model_dump())
    _write_views(user.username, [updated if item.id == view_id else item for item in values])
    record_activity(ActivityCategory.configuration, "logs_saved_view_update", user.username, details={"view_id": view_id}, source="logs")
    return updated


@router.delete("/saved-views/{view_id}")
def delete_saved_view(view_id: str, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_SAVED_VIEWS_MANAGE)
    if not re.fullmatch(r"[a-f0-9]{32}", view_id):
        raise HTTPException(404, "Saved view not found")
    values = _read_views(user.username)
    remaining = [item for item in values if item.id != view_id]
    if len(remaining) == len(values):
        raise HTTPException(404, "Saved view not found")
    _write_views(user.username, remaining)
    record_activity(ActivityCategory.configuration, "logs_saved_view_delete", user.username, details={"view_id": view_id}, source="logs")
    return {"ok": True}
