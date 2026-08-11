from __future__ import annotations

import json
import os
import pwd
import secrets
import shlex
import shutil
import stat
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from ...activity import ActivityCategory, record_activity
from ...audit import logger
from ...config import get_config
from ...package_center.executor import redact
from .models import (
    CronDashboard,
    CronDiagnostic,
    CronJob,
    CronJobCreate,
    CronJobDefinition,
    CronJobStatus,
    CronJobUpdate,
    CronLogEntry,
    CronValidationResult,
)
from .repository import CronRepository
from .schedule import CronExpression, CronSyntaxError, next_occurrence
from .system import AtomicCronWriter, CronSystem, parse_managed_config, render_config, render_entry


SENSITIVE_ENV_MARKERS = ("password", "passwd", "token", "secret", "credential", "private_key")


class CronNotFoundError(KeyError):
    pass


class CronReadOnlyError(PermissionError):
    pass


class CronService:
    def __init__(
        self,
        database_path: Path | None = None,
        config_path: Path = Path("/etc/cron.d/webnas"),
        *,
        system: CronSystem | None = None,
        user_lookup: Callable[[str], Any] = pwd.getpwnam,
        enforce_permissions: bool | None = None,
    ) -> None:
        root = database_path.parent if database_path else Path(get_config().paths.data_dir) / "cron"
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.root = root
        self.repository = CronRepository(database_path or root / "cron.sqlite3")
        self.config_path = config_path
        self.system = system or CronSystem(managed_path=config_path)
        self.enforce_permissions = config_path.parent == Path("/etc/cron.d") if enforce_permissions is None else enforce_permissions
        self.writer = AtomicCronWriter(config_path, root / "backups", enforce_permissions=self.enforce_permissions)
        self.inputs_root = root / "inputs"
        self.inputs_root.mkdir(exist_ok=True)
        os.chmod(self.inputs_root, 0o700)
        self.user_lookup = user_lookup
        self._lock = threading.RLock()
        self._external_cache: tuple[float, list[CronJob]] = (0, [])

    @staticmethod
    def _public_job(job: CronJob) -> CronJob:
        following = next_occurrence(job.schedule) if job.enabled else None
        return job.model_copy(update={"next_run_at": following.timestamp() if following else None})

    def _managed(self) -> list[CronJob]:
        return [self._public_job(job) for job in self.repository.list()]

    def _external(self, ttl: float = 15.0) -> list[CronJob]:
        now = time.monotonic()
        if now - self._external_cache[0] < ttl:
            return self._external_cache[1]
        try:
            values = self.system.external_jobs()
        except OSError:
            values = []
        self._external_cache = (now, values)
        return values

    def list_jobs(
        self,
        *,
        search: str = "",
        username: str = "",
        status: str = "",
        include_external: bool = True,
        limit: int = 2000,
    ) -> list[CronJob]:
        jobs = self._managed() + (self._external() if include_external else [])
        needle = search.strip().casefold()[:200]
        if needle:
            jobs = [job for job in jobs if needle in f"{job.name} {job.description} {job.command} {job.schedule} {job.user} {job.source_label}".casefold()]
        if username:
            jobs = [job for job in jobs if job.user == username]
        if status:
            jobs = [job for job in jobs if job.status.value == status]
        return jobs[:min(max(limit, 1), 2000)]

    def get(self, job_id: str, *, include_external: bool = True) -> CronJob:
        try:
            UUID(job_id)
        except ValueError:
            if not job_id.startswith("external-"):
                raise CronNotFoundError(job_id) from None
        managed = self.repository.get(job_id)
        if managed:
            return self._public_job(managed)
        if include_external:
            external = next((job for job in self._external() if job.id == job_id), None)
            if external:
                return external
        raise CronNotFoundError(job_id)

    def validate_definition(self, definition: CronJobDefinition) -> tuple[CronValidationResult, CronJobDefinition]:
        definition = CronJobDefinition.model_validate({
            name: getattr(definition, name) for name in CronJobDefinition.model_fields
        })
        CronExpression.parse(definition.schedule)
        try:
            self.user_lookup(definition.user)
        except KeyError as error:
            raise ValueError(f"Linux user does not exist: {definition.user}") from error
        warnings: list[str] = []
        if definition.working_directory and not Path(definition.working_directory).is_dir():
            warnings.append("The working directory does not currently exist")
        if definition.timeout_seconds and not Path("/usr/bin/timeout").is_file():
            warnings.append("/usr/bin/timeout is unavailable; the job cannot run with a timeout")
        if any(any(marker in item.name.casefold() for marker in SENSITIVE_ENV_MARKERS) for item in definition.environment):
            warnings.append("Environment contains a secret-like variable; cron stores environment values as plain text")
        preview = CronJob(
            id=str(uuid4()),
            **definition.model_dump(mode="python"),
            status=CronJobStatus.enabled if definition.enabled else CronJobStatus.disabled,
        )
        return CronValidationResult.for_definition(definition, render_entry(preview), warnings), definition

    def config_valid(self) -> bool:
        jobs = self.repository.list()
        if not self.config_path.exists():
            return not jobs
        try:
            content = self.config_path.read_text(encoding="utf-8")
            parsed = parse_managed_config(content)
            expected = render_config(jobs)
            return content == expected and {str(item["id"]) for item in parsed} == {job.id for job in jobs}
        except (OSError, ValueError):
            return False

    def _apply_candidate(self, jobs: list[CronJob], database_operation: Callable[[], CronJob | None]) -> CronJob | None:
        content = render_config(jobs)
        snapshot = self.writer.apply(content)
        try:
            result = database_operation()
            if not self.config_valid():
                raise RuntimeError("cron database and managed configuration do not match")
            return result
        except Exception:
            self.writer.restore(snapshot)
            raise

    @staticmethod
    def _audit(action: str, actor: str, job: CronJob, **details: Any) -> None:
        safe = {"job_id": job.id, "name": job.name, "user": job.user, "schedule": job.schedule, **details}
        logger.info("cron_audit action=%s actor=%s job=%s", action, actor, job.id)
        record_activity(ActivityCategory.module, action, actor, target=job.id, details=safe, source="cron")

    def create(self, payload: CronJobCreate, actor: str) -> CronJob:
        definition = CronJobDefinition.model_validate(payload.model_dump(exclude={"id"}))
        self.validate_definition(definition)
        job_id = payload.id or str(uuid4())
        created_payload = CronJobCreate(id=job_id, **definition.model_dump(mode="python"))
        candidate = CronJob(id=job_id, **definition.model_dump(mode="python"), status=CronJobStatus.enabled if definition.enabled else CronJobStatus.disabled)
        with self._lock:
            jobs = self.repository.list()
            if any(job.id == job_id for job in jobs):
                raise ValueError("cron job id already exists")
            created = self._apply_candidate([*jobs, candidate], lambda: self.repository.create(created_payload, actor))
        assert created is not None
        self._audit("cron.job.created", actor, created)
        return self._public_job(created)

    def update(self, job_id: str, payload: CronJobUpdate, actor: str, *, action: str = "cron.job.updated") -> CronJob:
        self.validate_definition(payload)
        with self._lock:
            existing = self.repository.get(job_id)
            if not existing:
                if any(job.id == job_id for job in self._external()):
                    raise CronReadOnlyError(job_id)
                raise CronNotFoundError(job_id)
            candidate = CronJob(
                id=job_id,
                **payload.model_dump(mode="python"),
                status=CronJobStatus.enabled if payload.enabled else CronJobStatus.disabled,
                created_at=existing.created_at,
                created_by=existing.created_by,
                updated_by=actor,
            )
            jobs = [candidate if job.id == job_id else job for job in self.repository.list()]
            updated = self._apply_candidate(jobs, lambda: self.repository.update(job_id, payload, actor, action))
        assert updated is not None
        self._audit(action, actor, updated)
        return self._public_job(updated)

    def set_enabled(self, job_id: str, enabled: bool, actor: str) -> CronJob:
        existing = self.get(job_id)
        if existing.read_only:
            raise CronReadOnlyError(job_id)
        payload = CronJobUpdate.model_validate({
            **existing.model_dump(mode="python", exclude={"id", "source", "status", "read_only", "created_at", "updated_at", "created_by", "updated_by", "last_run_at", "last_run_status", "next_run_at", "source_label"}),
            "enabled": enabled,
        })
        return self.update(job_id, payload, actor, action="cron.job.enabled" if enabled else "cron.job.disabled")

    def delete(self, job_id: str, actor: str) -> None:
        with self._lock:
            existing = self.get(job_id)
            if existing.read_only:
                raise CronReadOnlyError(job_id)
            jobs = [job for job in self.repository.list() if job.id != job_id]
            self._apply_candidate(jobs, lambda: self.repository.delete(job_id, actor, existing.name))
        self._audit("cron.job.deleted", actor, existing)

    def duplicate(self, job_id: str, actor: str, *, new_id: str | None = None) -> CronJob:
        existing = self.get(job_id)
        if existing.read_only:
            raise CronReadOnlyError(job_id)
        return self.create(CronJobCreate(
            id=new_id,
            name=f"{existing.name} (copy)"[:120],
            description=existing.description,
            user=existing.user,
            schedule=existing.schedule,
            command=existing.command,
            working_directory=existing.working_directory,
            environment=existing.environment,
            timeout_seconds=existing.timeout_seconds,
            enabled=False,
        ), actor)

    def dashboard(self) -> CronDashboard:
        managed = self._managed()
        errors = 0 if self.config_valid() else 1
        return CronDashboard(
            active=sum(job.enabled for job in managed),
            inactive=sum(not job.enabled for job in managed),
            errors=errors,
            recently_run=sum(bool(job.last_run_at and job.last_run_at > time.time() - 86_400) for job in managed),
            total=len(managed),
        )

    def history(self, job_id: str, limit: int = 200) -> dict[str, Any]:
        job = self.get(job_id)
        if job.read_only:
            return {"available": False, "reason": "Execution history is unavailable for external cron entries", "entries": []}
        return {
            "available": False,
            "reason": "Cron does not provide reliable exit codes or execution history without changing job semantics",
            "entries": self.repository.history(job_id, limit),
        }

    def diagnostics(self, *, blocked_by_proxmox: bool = False) -> list[CronDiagnostic]:
        diagnostics: list[CronDiagnostic] = []

        def add(code: str, ok: bool, title: str, detail: str, recommendation: str = "") -> None:
            diagnostics.append(CronDiagnostic(code=code, status="ok" if ok else "warning", title=title, detail=redact(detail), recommendation=recommendation if not ok else ""))

        executable = shutil.which("crontab")
        add("crontab", bool(executable), "crontab command", executable or "Not found", "Install the distribution cron/cronie package")
        daemon = self.system.daemon()
        add("daemon", bool(daemon), "Cron daemon", daemon or "cron/crond was not detected", "Install or enable cron/crond")
        state, enabled = self.system.service_state(daemon)
        add("service-active", state == "active", "Cron service state", state, "Start the detected cron/crond service")
        add("service-enabled", enabled is True, "Cron service autostart", "enabled" if enabled else "disabled or unavailable", "Enable cron/crond at boot")
        valid = self.config_valid()
        add("managed-config", valid, "WebNAS cron configuration", "valid" if valid else "missing, modified, or inconsistent with the WebNAS database", "Review the managed file and re-save a WebNAS job")
        if self.config_path.exists():
            try:
                metadata = self.config_path.stat()
                mode = stat.S_IMODE(metadata.st_mode)
                add("config-mode", mode == 0o644, "Managed file permissions", oct(mode), "Set mode 0644")
                add("config-owner", metadata.st_uid == 0 if self.config_path.parent == Path("/etc/cron.d") else True, "Managed file owner", str(metadata.st_uid), "Set owner to root")
            except OSError as error:
                add("config-stat", False, "Managed file metadata", str(error), "Review filesystem permissions")
        managed = self.repository.list()
        duplicate_keys: dict[tuple[str, str, str], int] = {}
        for job in managed:
            key = (job.user, job.schedule, job.command)
            duplicate_keys[key] = duplicate_keys.get(key, 0) + 1
            try:
                CronExpression.parse(job.schedule)
            except CronSyntaxError as error:
                add(f"schedule-{job.id}", False, f"Invalid schedule: {job.name}", str(error), "Edit the schedule")
            try:
                self.user_lookup(job.user)
            except KeyError:
                add(f"user-{job.id}", False, f"Missing user: {job.name}", job.user, "Choose an existing Linux user")
            try:
                tokens = shlex.split(job.command)
            except ValueError:
                tokens = []
            if tokens and tokens[0].startswith("/"):
                path = Path(tokens[0])
                add(f"executable-{job.id}", path.is_file() and os.access(path, os.X_OK), f"Executable: {job.name}", str(path), "Install the executable or correct the command")
            if job.working_directory:
                add(f"cwd-{job.id}", Path(job.working_directory).is_dir(), f"Working directory: {job.name}", job.working_directory, "Create the directory or correct the path")
        duplicates = sum(count - 1 for count in duplicate_keys.values() if count > 1)
        add("duplicates", duplicates == 0, "Duplicate jobs", str(duplicates), "Review duplicate user/schedule/command combinations")
        add("proxmox-safe-mode", not blocked_by_proxmox, "Proxmox Safe Mode", "mutations blocked" if blocked_by_proxmox else "not blocking Cron Manager", "Use a VM/LXC or explicitly disable Safe Mode after reviewing risk")
        return diagnostics

    def log_sources(self) -> list[dict[str, str]]:
        return self.system.log_sources()

    def logs(self, source: str, *, limit: int = 200, search: str = "", username: str = "", job_id: str = "") -> dict[str, Any]:
        lines = self.system.logs(source, limit)
        needles = [value.casefold() for value in (search.strip()[:200], username.strip()[:32]) if value]
        job_needles: list[str] = []
        if job_id:
            job = self.get(job_id)
            job_needles = [job.name.casefold(), job.command.casefold()]
        if needles:
            lines = [line for line in lines if all(needle in line.casefold() for needle in needles)]
        if job_needles:
            lines = [line for line in lines if any(needle in line.casefold() for needle in job_needles)]
        entries = [CronLogEntry(source=source, message=redact(line)) for line in lines[-limit:]]
        return {"source": source, "sources": self.log_sources(), "entries": [item.model_dump(mode="json") for item in entries], "truncated": len(lines) >= limit}

    def stage_input(self, value: dict[str, Any]) -> str:
        reference = secrets.token_hex(24)
        target = self.inputs_root / f"{reference}.json"
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 128 * 1024:
            raise ValueError("cron operation payload is too large")
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return reference

    def read_input(self, reference: str) -> dict[str, Any]:
        if len(reference) != 48 or any(character not in "0123456789abcdef" for character in reference):
            raise ValueError("invalid cron input reference")
        path = self.inputs_root / f"{reference}.json"
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or (self.enforce_permissions and stat.S_IMODE(metadata.st_mode) & 0o077):
            raise ValueError("cron input file permissions are unsafe")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("cron input must be an object")
        return value

    def discard_input(self, reference: str) -> None:
        if len(reference) == 48 and all(character in "0123456789abcdef" for character in reference):
            (self.inputs_root / f"{reference}.json").unlink(missing_ok=True)


@lru_cache
def service() -> CronService:
    return CronService()
