from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LOG_PRIORITIES = {0: "emergency", 1: "alert", 2: "critical", 3: "error", 4: "warning", 5: "notice", 6: "info", 7: "debug"}
MAX_MESSAGE = 16 * 1024
MAX_FIELD_VALUE = 4096
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_COMMAND_BYTES = 12 * 1024 * 1024
MAX_REGEX_LENGTH = 180
MAX_EXPORT = 5000
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.(?:service|socket|timer|mount|target|scope)$")
CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.@:/-]{1,128}$")
ACCOUNT_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}\$?$")
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9_.:-]{0,251}[A-Za-z0-9])?$")
BOOT_RE = re.compile(r"^[a-fA-F0-9]{32}$")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9:_.@/-]{0,180}$")
UNSAFE_REGEX_RE = re.compile(r"(\([^)]*[+*][^)]*\)[+*]|\.\*[+*]|\.\+\+|\{\d+,\d*\}[+*])")
PYTHON_TRACEBACK_RE = re.compile(r"(?m)^Traceback \(most recent call last\):\s*$")
PYTHON_EXCEPTION_RE = re.compile(r"(?m)^(?:[\w.]+\.)?[A-Za-z_]\w*(?:Error|Exception|Fault|Failure):(?:\s|$)")
PYTHON_TRACEBACK_LINE_RE = re.compile(r'^(?:\s+File ".+", line \d+(?:, in .+)?|\s+.*|\s*\^+\s*|During handling of the above exception.*|The above exception was the direct cause.*)$')
ERROR_SIGNAL_RE = re.compile(r"(?im)(?:^|\b)(?:Exception in ASGI application|Unhandled exception|Uncaught exception|Segmentation fault|core dumped|panic|failed with result|process exited with status)(?:\b|$)")
UPPERCASE_ERROR_RE = re.compile(r"(?m)(?:^|[\s:\[])(?:ERROR|FATAL)(?:[\s:\]]|$)")
BENIGN_ERROR_RE = re.compile(r"(?i)\b(?:0 errors?|no errors?(?: detected)?|errors?\s+(?:count|rate)\s*:\s*0|without error|ignore_errors|error handling enabled|documentation about error handling)\b")


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def infer_effective_priority(message: object, original_priority: object, fields: dict[str, Any] | None = None) -> tuple[int, str | None]:
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
        allowed = {"priority", "unit", "pid", "uid", "identifier", "transport", "boot_id", "container_id", "since", "until", "case_sensitive", "regex", "negate", "message_only", "hostname", "device", "username", "group"}
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
