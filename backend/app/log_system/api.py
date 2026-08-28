from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..identity.permissions import Permission, authorize, has_permission
from ..security import SessionUser, get_session_user, require_csrf
from .execution import run_bounded
from .files import available_files
from .models import BOOT_RE, CONTAINER_RE, UNIT_RE, ExportRequest, SavedView, SavedViewPayload, _int
from .service import query_entries
from .sources import has_log_permission, permission_for_source, source_known
from .storage import read_views, write_views

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _current_user(request: Request) -> SessionUser:
    return get_session_user(request)


def _mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def parse_journal_boots(stdout: str) -> list[dict[str, Any]]:
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
    items: list[dict[str, Any]] = []
    for value in records:
        raw_boot_id = value.get("boot_id") or value.get("boot-id") or value.get("bootId")
        boot_id = raw_boot_id if isinstance(raw_boot_id, str) else ""
        if not BOOT_RE.fullmatch(boot_id):
            continue
        raw_index = _int(value.get("index"))
        index = raw_index if raw_index is not None else 0
        first = value.get("first_entry") if "first_entry" in value else value.get("first")
        last = value.get("last_entry") if "last_entry" in value else value.get("last")
        first_value = first if isinstance(first, (str, int, float)) and not isinstance(first, bool) else None
        last_value = last if isinstance(last, (str, int, float)) and not isinstance(last, bool) else None
        first_number, last_number = _int(first_value), _int(last_value)
        duration = max(0, (last_number - first_number) / 1_000_000) if first_number is not None and last_number is not None else None
        items.append({"id": boot_id, "index": index, "first": first_value, "last": last_value, "duration_seconds": duration, "current": index == 0})
    return items


def _parse_journal_boots_text(stdout: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        match = re.match(r"\s*(-?\d+)\s+([a-fA-F0-9]{32})\s+(.*?)\s+(?:—|--)\s+(.*?)\s*$", line)
        if match:
            index = int(match.group(1))
            items.append({"index": index, "id": match.group(2), "first": match.group(3), "last": match.group(4), "duration_seconds": None, "current": index == 0})
    return items


@router.get("/sources")
def log_sources(user: SessionUser = Depends(_current_user)):
    groups: list[dict[str, Any]] = []

    def add(group: str, identifier: str, label: str, permission: Permission, available: bool, status: str = "available") -> None:
        if not has_log_permission(user, permission):
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
    dmesg = shutil.which("dmesg") is not None
    add("kernel", "dmesg", "dmesg", Permission.LOGS_VIEW_KERNEL, dmesg, "available" if dmesg else "missing_program")
    add("webnas", "webnas", "WebNAS service", Permission.LOGS_VIEW_WEBNAS, journal, "available" if journal else "missing_program")
    add("webnas", "activity-own", "My Activity Center", Permission.LOGS_VIEW_OWN, True)
    global_activity = has_permission(user.username, Permission.AUDIT_VIEW_ALL)
    add("webnas", "activity", "Activity Center", Permission.LOGS_VIEW_WEBNAS, global_activity, "available" if global_activity else "permission_denied")
    add("packages", "packages", "Packages and modules", Permission.LOGS_VIEW_WEBNAS, True)
    if has_log_permission(user, Permission.LOGS_VIEW_SERVICES):
        groups.append({"id": "services", "label": "services", "items": []})
    for identifier, (path, label, permission) in available_files().items():
        add("files" if identifier.startswith("file:") else "webnas", identifier, label, permission, path.is_file())
    docker = shutil.which("docker") is not None
    if has_permission(user.username, Permission.LOGS_VIEW_CONTAINERS):
        groups.append({"id": "containers", "label": "containers", "items": [] if docker else [{"id": "containers-unavailable", "label": "Docker containers", "available": False, "status": "missing_program", "permission": Permission.LOGS_VIEW_CONTAINERS.value}]})
    return {"groups": groups, "capabilities": {"journal": journal, "docker": docker, "live": has_permission(user.username, Permission.LOGS_LIVE), "export": has_permission(user.username, Permission.LOGS_EXPORT)}}


@router.get("/entries")
def log_entries(
    source: str = Query(default="journal", max_length=180), query: str = Query(default="", max_length=500), regex: bool = False,
    case_sensitive: bool = False, negate: bool = False, message_only: bool = False, priority: list[int] = Query(default=[]),
    unit: str = Query(default="", max_length=128), pid: int | None = Query(default=None, ge=0), uid: int | None = Query(default=None, ge=0),
    identifier: str = Query(default="", max_length=128), transport: str = Query(default="", max_length=64), hostname: str = Query(default="", max_length=253),
    device: str = Query(default="", max_length=128), username: str = Query(default="", max_length=32), group: str = Query(default="", max_length=32),
    boot_id: str = Query(default="", max_length=32), container_id: str = Query(default="", max_length=128), since: float | None = Query(default=None, ge=0),
    until: float | None = Query(default=None, ge=0), cursor: str = Query(default="", max_length=4096), direction: Literal["older", "newer"] = "older",
    limit: int = Query(default=200, ge=1, le=1000), user: SessionUser = Depends(_current_user),
):
    result = query_entries(user, source=source, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate, message_only=message_only, priority=priority, unit=unit, pid=pid, uid=uid, identifier=identifier, transport=transport, hostname=hostname, device=device, username=username, group=group, boot_id=boot_id, container_id=container_id, since=since, until=until, cursor=cursor, direction=direction, limit=limit)
    record_activity(ActivityCategory.administration, "logs_view", user.username, status=ActivityStatus.info, details={"source": source, "count": len(result["items"]), "filtered": bool(query or priority or unit or pid is not None or uid is not None or identifier or transport or hostname or device or username or group)}, source="logs")
    return result


@router.get("/boots")
def log_boots(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_SYSTEM)
    executable = shutil.which("journalctl")
    if not executable:
        return {"items": [], "status": "missing_program"}
    code, stdout, _ = run_bounded([executable, "--list-boots", "--no-pager", "--output=json"], timeout=8)
    parsed_items = parse_journal_boots(stdout) if code == 0 else []
    if parsed_items:
        return {"items": parsed_items, "status": "available", "error": ""}
    code, stdout, _ = run_bounded([executable, "--list-boots", "--no-pager"], timeout=8)
    parsed_items = _parse_journal_boots_text(stdout) if code == 0 else []
    return {"items": parsed_items, "status": "available" if code == 0 else "error", "error": "" if code == 0 else "journalctl could not list system boots"}


@router.get("/services")
def log_services(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_SERVICES)
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {"items": [], "status": "missing_program"}
    code, stdout, stderr = run_bounded([systemctl, "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"], timeout=10)
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
    code, stdout, stderr = run_bounded([systemctl, "show", unit, f"--property={properties}", "--no-pager"], timeout=8)
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
    code, stdout, stderr = run_bounded([docker, "ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=10)
    items = []
    for line in stdout.splitlines()[:1000]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        identifier, name = str(value.get("ID") or ""), str(value.get("Names") or "")
        if CONTAINER_RE.fullmatch(identifier) and CONTAINER_RE.fullmatch(name):
            items.append({"id": identifier, "name": name, "image": str(value.get("Image") or ""), "state": str(value.get("State") or ""), "status": str(value.get("Status") or "")})
    return {"items": items, "status": "available" if code == 0 else "error", "error": "" if code == 0 else stderr}


@router.get("/fields")
def log_fields(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_OWN)
    return {"items": ["MESSAGE", "PRIORITY", "_SYSTEMD_UNIT", "_SYSTEMD_USER_UNIT", "_PID", "_UID", "_GID", "_HOSTNAME", "SYSLOG_IDENTIFIER", "_TRANSPORT", "_BOOT_ID", "_EXE", "_CMDLINE", "_KERNEL_DEVICE", "__CURSOR"]}


@router.get("/stream")
async def log_stream(
    request: Request, source: str = Query(default="journal", max_length=180), query: str = Query(default="", max_length=500), regex: bool = False,
    case_sensitive: bool = False, negate: bool = False, message_only: bool = False, priority: list[int] = Query(default=[]), unit: str = Query(default="", max_length=128),
    pid: int | None = Query(default=None, ge=0), uid: int | None = Query(default=None, ge=0), identifier: str = Query(default="", max_length=128),
    transport: str = Query(default="", max_length=64), hostname: str = Query(default="", max_length=253), device: str = Query(default="", max_length=128),
    username: str = Query(default="", max_length=32), group: str = Query(default="", max_length=32), boot_id: str = Query(default="", max_length=32), container_id: str = Query(default="", max_length=128),
    user: SessionUser = Depends(_current_user),
):
    authorize(user, Permission.LOGS_LIVE)
    from .sources import authorize_source
    authorize_source(user, source)
    record_activity(ActivityCategory.administration, "logs_live_start", user.username, status=ActivityStatus.info, details={"source": source}, source="logs")

    async def events():
        seen: set[str] = set()
        try:
            while not await request.is_disconnected():
                result = await asyncio.to_thread(query_entries, user, source=source, query=query, regex=regex, case_sensitive=case_sensitive, negate=negate, message_only=message_only, priority=priority, unit=unit, pid=pid, uid=uid, identifier=identifier, transport=transport, hostname=hostname, device=device, username=username, group=group, boot_id=boot_id, container_id=container_id, limit=100, direction="newer")
                fresh = [item for item in reversed(result["items"]) if item["id"] not in seen]
                for item in fresh:
                    seen.add(item["id"])
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if len(seen) > 2000:
                    seen = set(list(seen)[-1000:])
                if not fresh:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1.25)
        except asyncio.CancelledError:
            return
        except Exception:
            yield "event: source-error\ndata: {\"error\":\"Log stream is temporarily unavailable\"}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/export")
def log_export(payload: ExportRequest, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_EXPORT)
    result = query_entries(user, **payload.model_dump(exclude={"format"}))
    items = result["items"]
    if payload.format == "json":
        content, media = json.dumps({"items": items, "truncated": result["has_more"]}, ensure_ascii=False, indent=2), "application/json"
    elif payload.format == "jsonl":
        content, media = "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n", "application/x-ndjson"
    elif payload.format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["timestamp", "priority", "severity", "original_priority", "original_severity", "severity_inferred", "severity_reason", "source", "unit", "identifier", "pid", "uid", "hostname", "message"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)
        content, media = output.getvalue(), "text/csv"
    else:
        content = "\n".join(f"{item.get('timestamp') or '-'} [{item['severity'].upper()} priority={item['priority']}; original={item['original_severity']}/{item['original_priority']}{'; inferred=' + str(item.get('severity_reason')) if item.get('severity_inferred') else ''}] {item.get('unit') or item.get('identifier') or item['source']}: {item['message']}" for item in items) + "\n"
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


@router.get("/saved-views")
def saved_views(user: SessionUser = Depends(_current_user)):
    authorize(user, Permission.LOGS_VIEW_OWN)
    builtins = [item for item in BUILTIN_VIEWS if has_log_permission(user, permission_for_source(item.source)) and (item.id != "failed-logins" or has_permission(user.username, Permission.LOGS_VIEW_SECURITY))]
    return {"items": [item.model_dump(mode="json") for item in [*builtins, *read_views(user.username)]]}


@router.post("/saved-views")
def create_saved_view(payload: SavedViewPayload, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_SAVED_VIEWS_MANAGE)
    if not source_known(payload.source):
        raise HTTPException(400, "Unknown or unavailable log source")
    from .sources import authorize_source
    authorize_source(user, payload.source)
    values = read_views(user.username)
    if len(values) >= 50:
        raise HTTPException(409, "At most 50 saved log views are allowed")
    item = SavedView(id=uuid.uuid4().hex, **payload.model_dump())
    write_views(user.username, [item, *values])
    record_activity(ActivityCategory.configuration, "logs_saved_view_create", user.username, details={"view_id": item.id}, source="logs")
    return item


@router.patch("/saved-views/{view_id}")
def update_saved_view(view_id: str, payload: SavedViewPayload, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_SAVED_VIEWS_MANAGE)
    if not source_known(payload.source):
        raise HTTPException(400, "Unknown or unavailable log source")
    if not re.fullmatch(r"[a-f0-9]{32}", view_id):
        raise HTTPException(404, "Saved view not found")
    values = read_views(user.username)
    if not any(item.id == view_id for item in values):
        raise HTTPException(404, "Saved view not found")
    updated = SavedView(id=view_id, **payload.model_dump())
    write_views(user.username, [updated if item.id == view_id else item for item in values])
    record_activity(ActivityCategory.configuration, "logs_saved_view_update", user.username, details={"view_id": view_id}, source="logs")
    return updated


@router.delete("/saved-views/{view_id}")
def delete_saved_view(view_id: str, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.LOGS_SAVED_VIEWS_MANAGE)
    if not re.fullmatch(r"[a-f0-9]{32}", view_id):
        raise HTTPException(404, "Saved view not found")
    values = read_views(user.username)
    remaining = [item for item in values if item.id != view_id]
    if len(remaining) == len(values):
        raise HTTPException(404, "Saved view not found")
    write_views(user.username, remaining)
    record_activity(ActivityCategory.configuration, "logs_saved_view_delete", user.username, details={"view_id": view_id}, source="logs")
    return {"ok": True}
