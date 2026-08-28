from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException

from ..identity.permissions import Permission, has_permission
from ..security import SessionUser
from .adapters import resolve_log_source
from .filtering import decode_cursor, encode_cursor, matches, validate_regex
from .models import MAX_RESPONSE_BYTES, SOURCE_RE, LogEntry
from .parsing import group_traceback_entries
from .sources import authorize_source as _authorize_source, security_entry, source_known as _source_known


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
        validate_regex(query)

    continuation = decode_cursor(cursor, source)
    fetch_limit = min(5000, max(limit * 5, limit + 1))
    journal_source = source in {"journal", "current-boot", "kernel", "webnas"} or source.startswith("service:")
    try:
        offset = max(0, int(continuation.get("offset", "0"))) if not journal_source else 0
    except ValueError as error:
        raise HTTPException(400, "Invalid continuation offset") from error

    provider = resolve_log_source(user, source, since=since, until=until)
    entries = provider.read(
        limit=fetch_limit if journal_source else 5000,
        priority=priority or [],
        unit=unit,
        pid=pid,
        uid=uid,
        identifier=identifier,
        transport=transport,
        hostname=hostname,
        device=device,
        username=username,
        group=group,
        boot_id=boot_id,
        since=since,
        until=until,
        continuation=continuation,
        direction=direction,
    )
    entries = group_traceback_entries(entries)
    if not has_permission(user.username, Permission.LOGS_VIEW_SECURITY):
        entries = [item for item in entries if not security_entry(item)]

    filtered: list[LogEntry] = []
    search_started = time.monotonic()
    for item in entries:
        if time.monotonic() - search_started > 0.5:
            raise HTTPException(408, "Log search exceeded its execution limit")
        if (not priority or item.priority in priority) and matches(item, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate, message_only=message_only):
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
        "next_cursor": encode_cursor(source, marker.timestamp, marker.cursor, offset + len(bounded) if not journal_source else None) if marker and has_more else None,
        "has_more": has_more,
        "direction": direction,
        "limit": limit,
        "truncated": len(bounded) < len(selected),
    }
