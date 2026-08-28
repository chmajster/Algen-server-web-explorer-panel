from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException

from ..security import SessionUser
from . import files
from .models import LogEntry
from . import sources as source_impl

# Injection points keep the historical app.logs facade/monkeypatch tests stable
# without leaking test hooks into the implementation modules themselves.
def _read_file(source: str, limit: int) -> list[LogEntry]:
    return files.file_entries(source, limit)


journal_reader = source_impl.journal_entries
file_reader: Callable[[str, int], list[LogEntry]] = _read_file
dmesg_reader = source_impl.dmesg_entries
activity_reader = source_impl.activity_entries
container_reader = source_impl.container_entries
package_reader = source_impl.package_entries


class LogSource(Protocol):
    def available(self) -> bool: ...

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]: ...


@dataclass(frozen=True)
class JournalLogSource:
    source: str

    def available(self) -> bool:
        return shutil.which("journalctl") is not None

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]:
        return journal_reader(
            self.source,
            limit=limit,
            priority=list(kwargs.get("priority") or []),
            unit=str(kwargs.get("unit") or ""),
            pid=kwargs.get("pid"),
            uid=kwargs.get("uid"),
            identifier=str(kwargs.get("identifier") or ""),
            transport=str(kwargs.get("transport") or ""),
            hostname=str(kwargs.get("hostname") or ""),
            device=str(kwargs.get("device") or ""),
            username=str(kwargs.get("username") or ""),
            group=str(kwargs.get("group") or ""),
            boot_id=str(kwargs.get("boot_id") or ""),
            since=kwargs.get("since"),
            until=kwargs.get("until"),
            continuation=dict(kwargs.get("continuation") or {}),
            direction=str(kwargs.get("direction") or "older"),
        )


@dataclass(frozen=True)
class FileLogSource:
    source: str

    def available(self) -> bool:
        return self.source in files.available_files()

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]:
        return file_reader(self.source, limit)


@dataclass(frozen=True)
class DmesgLogSource:
    def available(self) -> bool:
        return shutil.which("dmesg") is not None

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]:
        return dmesg_reader(limit)


@dataclass(frozen=True)
class ActivityLogSource:
    user: SessionUser
    global_scope: bool
    since: float | None
    until: float | None

    def available(self) -> bool:
        return True

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]:
        return activity_reader(self.user, self.global_scope, limit, self.since, self.until)


@dataclass(frozen=True)
class ContainerLogSource:
    source: str
    since: float | None
    until: float | None

    def available(self) -> bool:
        return shutil.which("docker") is not None

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]:
        return container_reader(self.source, limit, self.since, self.until)


@dataclass(frozen=True)
class PackageLogSource:
    def available(self) -> bool:
        return True

    def read(self, *, limit: int, **kwargs: Any) -> list[LogEntry]:
        return package_reader(limit)


def resolve_log_source(user: SessionUser, source: str, *, since: float | None, until: float | None) -> LogSource:
    if source.startswith(("file:", "webnas-file:")):
        return FileLogSource(source)
    if source == "dmesg":
        return DmesgLogSource()
    if source in {"activity", "activity-own"}:
        return ActivityLogSource(user, source == "activity", since, until)
    if source.startswith("container:"):
        return ContainerLogSource(source, since, until)
    if source == "packages":
        return PackageLogSource()
    if source in {"journal", "current-boot", "kernel", "webnas"} or source.startswith("service:"):
        return JournalLogSource(source)
    raise HTTPException(404, "Unknown or unavailable log source")
