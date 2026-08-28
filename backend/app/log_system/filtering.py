from __future__ import annotations

import base64
import json
import re

from fastapi import HTTPException

from .models import MAX_REGEX_LENGTH, UNSAFE_REGEX_RE, LogEntry


def encode_cursor(source: str, timestamp: str | None, cursor: str = "", offset: int | None = None) -> str:
    raw = json.dumps({"source": source, "timestamp": timestamp, "cursor": cursor, "offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str, source: str) -> dict[str, str]:
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


def validate_regex(query: str) -> re.Pattern[str]:
    if len(query) > MAX_REGEX_LENGTH:
        raise HTTPException(400, f"Regular expression can contain at most {MAX_REGEX_LENGTH} characters")
    if UNSAFE_REGEX_RE.search(query):
        raise HTTPException(400, "The regular expression is too expensive")
    try:
        return re.compile(query)
    except re.error as error:
        raise HTTPException(400, f"Invalid regular expression: {error.msg}") from error


def matches(entry: LogEntry, *, query: str, regex: bool, case_sensitive: bool, negate: bool, message_only: bool) -> bool:
    if not query:
        return True
    haystack = (entry.message if message_only else f"{entry.message}\n{entry.unit}\n{entry.identifier}\n{entry.hostname}\n{json.dumps(entry.fields, ensure_ascii=False)}")[:64 * 1024]
    if regex:
        pattern = validate_regex(query if case_sensitive else query.casefold())
        found = pattern.search(haystack if case_sensitive else haystack.casefold()) is not None
    else:
        needle = query if case_sensitive else query.casefold()
        target = haystack if case_sensitive else haystack.casefold()
        phrases = re.findall(r'"([^"]+)"|(\S+)', needle)
        terms = [first or second for first, second in phrases]
        found = all(term in target for term in terms)
    return not found if negate else found
