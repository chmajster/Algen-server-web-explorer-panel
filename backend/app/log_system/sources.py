from __future__ import annotations

import grp
import hashlib
import pwd
import shutil
from datetime import UTC, datetime
from typing import Protocol

from fastapi import HTTPException

from ..activity import ActivityStatus, repository as activity_repository
from ..identity.permissions import Permission, has_permission
from ..modules.ansible_controller.security import redact_text
from ..security import SessionUser
from .execution import run_bounded
from .files import available_files, file_entries
from .models import (
    ACCOUNT_RE,
    BOOT_RE,
    CONTAINER_RE,
    HOST_RE,
    IDENTIFIER_RE,
    LOG_PRIORITIES,
    MAX_MESSAGE,
    UNIT_RE,
    LogEntry,
)
from .parsing import parse_dmesg_record, parse_journal_record, safe_fields

WEBNAS_SERVICE_UNITS = (
    "webnas-backend-blue.service",
    "webnas-backend-green.service",
    "webnas.service",
)


class LogSource(Protocol):
    def read(self, *, limit: int, **kwargs) -> list[LogEntry]: ...


class JournalLogSource:
    def __init__(self, source: str) -> None:
        self.source = source

    def read(self, *, limit: int, **kwargs) -> list[LogEntry]:
        return journal_entries(self.source, limit=limit, **kwargs)


class FileLogSource:
    def __init__(self, source: str) -> None:
        self.source = source

    def read(self, *, limit: int, **kwargs) -> list[LogEntry]:
        return file_entries(self.source, limit)


def permission_for_source(source: str) -> Permission:
    if source in {"kernel", "dmesg"} or source.startswith("file:kern"):
        return Permission.LOGS_VIEW_KERNEL
    if source.startswith("service:"):
        return Permission.LOGS_VIEW_SERVICES
    if source.startswith("container:"):
        return Permission.LOGS_VIEW_CONTAINERS
    if source == "activity-own":
        return Permission.LOGS_VIEW_OWN
    if source in {"webnas", "activity", "packages"} or source.startswith("webnas-file:"):
        return Permission.LOGS_VIEW_WEBNAS
    if source.startswith(("file:auth", "file:secure", "file:audit")):
        return Permission.LOGS_VIEW_SECURITY
    return Permission.LOGS_VIEW_SYSTEM


def security_entry(entry: LogEntry) -> bool:
    marker = f"{entry.unit} {entry.identifier}".casefold()
    identifiers = {"sshd", "ssh", "sudo", "su", "login", "polkitd", "audit", "auditd", "pam"}
    return any(token in marker for token in identifiers) or str(entry.fields.get("SYSLOG_FACILITY", "")) in {"4", "10"} or "_AUDIT_TYPE" in entry.fields or "AUDIT_TYPE" in entry.fields


def has_log_permission(user: SessionUser, permission: Permission) -> bool:
    if has_permission(user.username, permission):
        return True
    return permission in {Permission.LOGS_VIEW_SYSTEM, Permission.LOGS_VIEW_KERNEL, Permission.LOGS_VIEW_SERVICES, Permission.LOGS_VIEW_WEBNAS} and has_permission(user.username, Permission.SYSTEM_LOGS)


def authorize_source(user: SessionUser, source: str) -> None:
    permission = permission_for_source(source)
    if not has_log_permission(user, permission):
        from ..identity.permissions import authorize
        authorize(user, permission)
    if source == "activity" and not has_permission(user.username, Permission.AUDIT_VIEW_ALL):
        raise HTTPException(403, "Global Activity Center access is required")


def source_known(source: str) -> bool:
    return (
        source in {"journal", "current-boot", "kernel", "dmesg", "webnas", "activity", "activity-own", "packages"}
        or (source.startswith("service:") and UNIT_RE.fullmatch(source.removeprefix("service:")) is not None)
        or (source.startswith("container:") and CONTAINER_RE.fullmatch(source.removeprefix("container:")) is not None)
        or source in available_files()
    )


def journal_entries(
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
    if source == "webnas":
        selected_units = WEBNAS_SERVICE_UNITS
    else:
        selected_unit = source.removeprefix("service:") if source.startswith("service:") else unit
        selected_units = (selected_unit,) if selected_unit else ()
    for selected_unit in selected_units:
        if not UNIT_RE.fullmatch(selected_unit):
            raise HTTPException(400, "Invalid systemd unit")
        args.extend(["--unit", selected_unit])
    if source in {"kernel", "dmesg"}:
        args.append("--dmesg")
    if source == "current-boot":
        args.extend(["--boot", "0"])
    if priority and any(value not in LOG_PRIORITIES for value in priority):
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
    code, stdout, stderr = run_bounded(args)
    if code != 0:
        if "permission" in stderr.casefold() or "access" in stderr.casefold():
            raise HTTPException(403, "The WebNAS service cannot read this journal")
        raise HTTPException(502, stderr.strip() or "journalctl could not read logs")
    return [entry for entry in (parse_journal_record(line) for line in stdout.splitlines()) if entry]


def dmesg_entries(limit: int) -> list[LogEntry]:
    executable = shutil.which("dmesg")
    if not executable:
        raise HTTPException(503, "dmesg is not installed")
    code, stdout, stderr = run_bounded([executable, "--json"], timeout=8)
    if code != 0:
        code, stdout, stderr = run_bounded([executable, "--time-format", "iso"], timeout=8)
    if code != 0:
        raise HTTPException(403 if "permission" in stderr.casefold() else 502, stderr or "dmesg could not be read")
    return [entry for entry in (parse_dmesg_record(line) for line in stdout.splitlines()) if entry][-limit:][::-1]


def activity_entries(user: SessionUser, global_scope: bool, limit: int, since: float | None, until: float | None) -> list[LogEntry]:
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
            fields=safe_fields(event.model_dump(mode="json")),
        )
        for event in events
    ]


def container_entries(source: str, limit: int, since: float | None, until: float | None) -> list[LogEntry]:
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
    code, stdout, stderr = run_bounded(args, timeout=15)
    if code != 0:
        raise HTTPException(502, stderr or "Container logs could not be read")
    entries: list[LogEntry] = []
    output = stdout if not stderr else f"{stdout}\n{stderr}"
    for index, line in enumerate(reversed(output.splitlines())):
        timestamp, _, message = line.partition(" ")
        stable = hashlib.sha256(f"{target}|{timestamp}|{index}|{message}".encode()).hexdigest()
        entries.append(LogEntry(id=stable, timestamp=timestamp or None, source=source, identifier=target, message=redact_text(message or line, limit=MAX_MESSAGE), fields={"container": target}))
    return entries


def package_entries(limit: int) -> list[LogEntry]:
    from ..package_center.service import repository
    try:
        jobs = repository().list_jobs(limit=min(200, max(20, limit)))
    except Exception as error:
        raise HTTPException(503, "Package Center history is unavailable") from error
    entries: list[LogEntry] = []
    for job in jobs:
        for line in reversed(job.get("log_tail") or []):
            created_at = float(line.get("created_at") or job.get("created_at") or 0)
            timestamp = datetime.fromtimestamp(created_at, UTC).isoformat(timespec="milliseconds") if created_at else None
            message = redact_text(line.get("line") or "", limit=MAX_MESSAGE)
            identifier = str(job.get("module_id") or "package-center")[:128]
            stable = f"package:{job.get('id')}:{line.get('id') or hashlib.sha256(message.encode()).hexdigest()}"
            entries.append(LogEntry(id=stable, timestamp=timestamp, priority=3 if str(line.get("stream")) == "stderr" or job.get("status") == "failed" else 6, source="packages", identifier=identifier, message=message, fields=safe_fields({"job_id": job.get("id"), "module_id": job.get("module_id"), "action": job.get("action"), "status": job.get("status"), "stream": line.get("stream"), "actor": job.get("created_by")})))
            if len(entries) >= limit:
                return entries
    return entries
