from __future__ import annotations

import gzip
import hashlib
import os
import re
import time
from pathlib import Path

from fastapi import HTTPException

from ..config import get_config
from ..core.redaction import redact_text
from ..identity.permissions import Permission
from .models import MAX_MESSAGE, LogEntry

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


def available_files() -> dict[str, tuple[Path, str, Permission]]:
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


def read_tail(path: Path, max_lines: int) -> list[str]:
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


def file_entries(source: str, limit: int, *, available=None) -> list[LogEntry]:
    sources = (available or available_files)()
    if source not in sources:
        raise HTTPException(404, "Log file source is unavailable")
    path, _, _ = sources[source]
    entries: list[LogEntry] = []
    for index, line in enumerate(reversed(read_tail(path, min(limit, 5000)))):
        message = redact_text(line, limit=MAX_MESSAGE)
        stable = hashlib.sha256(f"{path.name}|{path.stat().st_ino}|{index}|{message}".encode()).hexdigest()
        entries.append(LogEntry(id=stable, source=source, identifier=path.name, message=message, fields={"file": path.name, "line_from_end": index + 1}))
    return entries
