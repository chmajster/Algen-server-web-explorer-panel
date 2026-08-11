from __future__ import annotations

import hashlib
import os
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ...package_center.executor import SAFE_ENV, redact
from .models import CronJob, CronJobSource, CronJobStatus
from .schedule import CronExpression, CronSyntaxError, next_occurrence


MANAGED_HEADER = "# Managed by WebNAS Cron Manager. Manual changes may be replaced."
JOB_MARKER = "# WebNAS Cron Job"
ID_RE = re.compile(r"^# id: ([0-9a-f-]{36})$")
NAME_RE = re.compile(r"^# name: (.*)$")
ENABLED_RE = re.compile(r"^# enabled: (true|false)$")
SERVICE_NAMES = ("cron", "crond")
CLASSIC_LOGS = (Path("/var/log/syslog"), Path("/var/log/cron"))
SYSTEM_SCHEDULES = {
    "/etc/cron.hourly": "0 * * * *",
    "/etc/cron.daily": "0 0 * * *",
    "/etc/cron.weekly": "0 0 * * 0",
    "/etc/cron.monthly": "0 0 1 * *",
}


def _escape_percent(value: str) -> str:
    result: list[str] = []
    escaped = False
    for character in value:
        if character == "%" and not escaped:
            result.append("\\")
        result.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    return "".join(result)


def rendered_command(job: CronJob) -> str:
    inner = job.command
    if job.working_directory:
        inner = f"cd -- {shlex.quote(job.working_directory)} && {inner}"
    runner = f"/bin/sh -c {shlex.quote(inner)}"
    if job.timeout_seconds:
        runner = f"/usr/bin/timeout --signal=TERM {job.timeout_seconds}s {runner}"
    if job.environment:
        assignments = " ".join(f"{item.name}={shlex.quote(item.value)}" for item in job.environment)
        runner = f"/usr/bin/env {assignments} {runner}"
    return _escape_percent(runner)


def render_entry(job: CronJob) -> str:
    command = rendered_command(job)
    schedule = job.schedule
    if schedule == "@reboot":
        line = f"@reboot {job.user} {command}"
    else:
        line = f"{schedule} {job.user} {command}"
    if not job.enabled:
        line = f"# disabled: {line}"
    safe_name = job.name.replace("\r", " ").replace("\n", " ")
    return f"{JOB_MARKER}\n# id: {job.id}\n# name: {safe_name}\n# enabled: {'true' if job.enabled else 'false'}\n{line}"


def render_config(jobs: Iterable[CronJob]) -> str:
    entries = "\n\n".join(render_entry(job) for job in sorted(jobs, key=lambda item: item.id))
    suffix = f"\n\n{entries}" if entries else ""
    return f"{MANAGED_HEADER}\nSHELL=/bin/sh\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin{suffix}\n"


def parse_managed_config(content: str) -> list[dict[str, str | bool]]:
    if not content.startswith(MANAGED_HEADER + "\n"):
        raise ValueError("managed cron file header is missing")
    lines = content.splitlines()
    result: list[dict[str, str | bool]] = []
    index = 0
    while index < len(lines):
        if lines[index] != JOB_MARKER:
            index += 1
            continue
        if index + 4 >= len(lines):
            raise ValueError("managed cron marker is incomplete")
        id_match = ID_RE.fullmatch(lines[index + 1])
        name_match = NAME_RE.fullmatch(lines[index + 2])
        enabled_match = ENABLED_RE.fullmatch(lines[index + 3])
        if not id_match or not name_match or not enabled_match:
            raise ValueError("managed cron metadata is invalid")
        enabled = enabled_match.group(1) == "true"
        entry = lines[index + 4]
        if enabled and entry.startswith("# disabled: "):
            raise ValueError("managed cron enabled marker does not match its entry")
        if not enabled:
            if not entry.startswith("# disabled: "):
                raise ValueError("disabled managed cron entry is not commented")
            entry = entry.removeprefix("# disabled: ")
        _split_cron_line(entry, system=True)
        result.append({"id": id_match.group(1), "name": name_match.group(1), "enabled": enabled, "entry": entry})
        index += 5
    if len({str(item["id"]) for item in result}) != len(result):
        raise ValueError("managed cron file contains duplicate ids")
    return result


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    existed: bool
    content: bytes = b""
    mode: int = 0o644
    uid: int = 0
    gid: int = 0


class AtomicCronWriter:
    def __init__(self, path: Path, backup_root: Path, *, enforce_permissions: bool | None = None) -> None:
        self.path = path
        self.backup_root = backup_root
        self.enforce_permissions = path.parent == Path("/etc/cron.d") if enforce_permissions is None else enforce_permissions

    def snapshot(self) -> FileSnapshot:
        try:
            metadata = self.path.stat()
            return FileSnapshot(True, self.path.read_bytes(), stat.S_IMODE(metadata.st_mode), metadata.st_uid, metadata.st_gid)
        except FileNotFoundError:
            return FileSnapshot(False)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _atomic_write(self, content: bytes, mode: int, uid: int, gid: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, mode)
            if hasattr(os, "fchown"):
                try:
                    os.fchown(descriptor, uid, gid)
                except PermissionError:
                    if self.path.parent == Path("/etc/cron.d"):
                        raise
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            descriptor = -1
            os.replace(temporary, self.path)
            self._fsync_directory(self.path.parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _backup(self, snapshot: FileSnapshot) -> Path | None:
        if not snapshot.existed:
            return None
        self.backup_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.backup_root, 0o700)
        digest = hashlib.sha256(snapshot.content).hexdigest()[:12]
        path = self.backup_root / f"webnas-{time.time_ns()}-{digest}.cron.bak"
        descriptor, name = tempfile.mkstemp(prefix=".backup-", dir=self.backup_root)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(snapshot.content)
                handle.flush()
                os.fsync(handle.fileno())
            descriptor = -1
            os.replace(temporary, path)
            self._fsync_directory(self.backup_root)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        for stale in sorted(self.backup_root.glob("*.cron.bak"), key=lambda item: item.stat().st_mtime, reverse=True)[20:]:
            stale.unlink(missing_ok=True)
        return path

    def verify(self, expected: str) -> None:
        actual = self.path.read_text(encoding="utf-8")
        if actual != expected:
            raise RuntimeError("managed cron file verification failed")
        parse_managed_config(actual)
        metadata = self.path.stat()
        if self.enforce_permissions and stat.S_IMODE(metadata.st_mode) != 0o644:
            raise RuntimeError("managed cron file must have mode 0644")
        if self.enforce_permissions and metadata.st_uid != 0:
            raise RuntimeError("managed cron file must be owned by root")

    def apply(self, content: str) -> FileSnapshot:
        encoded = content.encode("utf-8")
        parse_managed_config(content)
        snapshot = self.snapshot()
        self._backup(snapshot)
        uid = 0 if os.geteuid() == 0 else os.geteuid()
        gid = 0 if os.geteuid() == 0 else os.getegid()
        try:
            self._atomic_write(encoded, 0o644, uid, gid)
            self.verify(content)
        except Exception:
            self.restore(snapshot)
            raise
        return snapshot

    def restore(self, snapshot: FileSnapshot) -> None:
        if snapshot.existed:
            self._atomic_write(snapshot.content, snapshot.mode, snapshot.uid, snapshot.gid)
        else:
            try:
                self.path.unlink()
                self._fsync_directory(self.path.parent)
            except FileNotFoundError:
                pass


def _split_cron_line(line: str, *, system: bool) -> tuple[str, str, str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        raise ValueError("not a cron entry")
    if stripped.startswith("@"):
        parts = stripped.split(None, 2 if system else 1)
        expected = 3 if system else 2
        if len(parts) != expected:
            raise ValueError("invalid cron macro entry")
        CronExpression.parse(parts[0])
        return parts[0], parts[1] if system else "", parts[2] if system else parts[1]
    parts = stripped.split(None, 6 if system else 5)
    expected = 7 if system else 6
    if len(parts) != expected:
        raise ValueError("invalid cron entry")
    schedule = " ".join(parts[:5])
    CronExpression.parse(schedule)
    return schedule, parts[5] if system else "", parts[6] if system else parts[5]


def _external_id(source: str, line_number: int, line: str) -> str:
    digest = hashlib.sha256(f"{source}\0{line_number}\0{line}".encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"external-{digest}"


def parse_external_config(content: str, *, source: CronJobSource, source_label: str, system: bool, username: str = "") -> list[CronJob]:
    jobs: list[CronJob] = []
    for line_number, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ("=" in stripped and not stripped.startswith("@") and len(stripped.split()) == 1):
            continue
        try:
            schedule, entry_user, command = _split_cron_line(stripped, system=system)
            user = entry_user or username
            following = next_occurrence(schedule)
            jobs.append(CronJob(
                id=_external_id(source_label, line_number, stripped),
                name=f"{Path(source_label).name}:{line_number}",
                description="External cron entry; read only",
                user=user or "unknown",
                schedule=schedule,
                command=redact(command),
                enabled=True,
                status=CronJobStatus.external,
                source=source,
                source_label=source_label,
                read_only=True,
                next_run_at=following.timestamp() if following else None,
            ))
        except (ValueError, CronSyntaxError):
            jobs.append(CronJob(
                id=_external_id(source_label, line_number, stripped),
                name=f"{Path(source_label).name}:{line_number}",
                description="Invalid external cron entry; read only",
                user=username or "unknown",
                schedule="@reboot",
                command=redact(stripped),
                enabled=False,
                status=CronJobStatus.invalid,
                source=source,
                source_label=source_label,
                read_only=True,
            ))
    return jobs


class CronSystem:
    def __init__(
        self,
        managed_path: Path = Path("/etc/cron.d/webnas"),
        etc_crontab: Path = Path("/etc/crontab"),
        cron_d: Path = Path("/etc/cron.d"),
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.managed_path = managed_path
        self.etc_crontab = etc_crontab
        self.cron_d = cron_d
        self.runner = runner

    @staticmethod
    def _safe_regular_file(path: Path) -> bool:
        try:
            metadata = path.lstat()
        except OSError:
            return False
        return stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)

    def daemon(self) -> str | None:
        systemctl = shutil.which("systemctl")
        if systemctl:
            for service in SERVICE_NAMES:
                try:
                    result = self.runner([systemctl, "show", f"{service}.service", "--property=LoadState", "--value"], capture_output=True, text=True, timeout=5, check=False, shell=False)
                except (OSError, subprocess.SubprocessError):
                    continue
                if result.returncode == 0 and result.stdout.strip() not in {"", "not-found"}:
                    return service
        for process in SERVICE_NAMES:
            if shutil.which(process):
                return process
        return None

    def service_state(self, service: str | None) -> tuple[str, bool | None]:
        systemctl = shutil.which("systemctl")
        if not service or not systemctl:
            return "unavailable", None
        try:
            active = self.runner([systemctl, "is-active", service], capture_output=True, text=True, timeout=5, check=False, shell=False)
            enabled = self.runner([systemctl, "is-enabled", service], capture_output=True, text=True, timeout=5, check=False, shell=False)
        except (OSError, subprocess.SubprocessError):
            return "unknown", None
        return (active.stdout.strip() or "inactive"), enabled.returncode == 0

    def external_jobs(self) -> list[CronJob]:
        jobs: list[CronJob] = []
        if self._safe_regular_file(self.etc_crontab):
            jobs.extend(parse_external_config(self.etc_crontab.read_text(encoding="utf-8", errors="replace")[:1_048_576], source=CronJobSource.system_crontab, source_label=str(self.etc_crontab), system=True))
        if self.cron_d.is_dir():
            for path in sorted(self.cron_d.iterdir())[:500]:
                if path.resolve(strict=False) == self.managed_path.resolve(strict=False) or not self._safe_regular_file(path):
                    continue
                jobs.extend(parse_external_config(path.read_text(encoding="utf-8", errors="replace")[:1_048_576], source=CronJobSource.cron_d, source_label=str(path), system=True))
        executable = shutil.which("crontab")
        if executable:
            try:
                users = [item.pw_name for item in pwd.getpwall() if item.pw_uid == 0 or item.pw_uid >= 1000][:200]
            except (OSError, KeyError):
                users = []
            for username in users:
                try:
                    result = self.runner([executable, "-u", username, "-l"], capture_output=True, text=True, timeout=5, check=False, shell=False, env=SAFE_ENV)
                except (OSError, subprocess.SubprocessError):
                    continue
                if result.returncode == 0:
                    jobs.extend(parse_external_config(result.stdout[:1_048_576], source=CronJobSource.user_crontab, source_label=f"crontab:{username}", system=False, username=username))
        for directory_name, schedule in SYSTEM_SCHEDULES.items():
            directory = Path(directory_name)
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir())[:200]:
                if not self._safe_regular_file(path):
                    continue
                following = next_occurrence(schedule)
                jobs.append(CronJob(
                    id=_external_id(directory_name, 0, path.name), name=path.name, description="Periodic system script; read only",
                    user="root", schedule=schedule, command=str(path), enabled=True, status=CronJobStatus.external,
                    source=CronJobSource.system, source_label=directory_name, read_only=True,
                    next_run_at=following.timestamp() if following else None,
                ))
        return jobs[:2000]

    def log_sources(self) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        if shutil.which("journalctl"):
            for service in SERVICE_NAMES:
                sources.append({"id": f"journal:{service}", "label": f"journalctl · {service}"})
        for path in CLASSIC_LOGS:
            if self._safe_regular_file(path):
                sources.append({"id": f"file:{path.name}", "label": str(path)})
        return sources

    def logs(self, source: str, limit: int) -> list[str]:
        limit = min(max(limit, 1), 1000)
        allowed = {item["id"] for item in self.log_sources()}
        if source not in allowed:
            raise ValueError("unsupported cron log source")
        if source.startswith("journal:"):
            service = source.split(":", 1)[1]
            executable = shutil.which("journalctl")
            if not executable or service not in SERVICE_NAMES:
                return []
            result = self.runner([executable, "-u", service, "-n", str(limit), "--no-pager", "--output=short-iso"], capture_output=True, text=True, timeout=15, check=False, shell=False, env=SAFE_ENV)
            return [redact(line) for line in result.stdout.splitlines()][-limit:]
        name = source.split(":", 1)[1]
        path = next((item for item in CLASSIC_LOGS if item.name == name), None)
        if not path or not self._safe_regular_file(path):
            return []
        with path.open("rb") as handle:
            try:
                handle.seek(-512 * 1024, os.SEEK_END)
            except OSError:
                handle.seek(0)
            content = handle.read(512 * 1024).decode("utf-8", errors="replace")
        return [redact(line) for line in content.splitlines()][-limit:]
