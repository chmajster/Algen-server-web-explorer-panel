from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from ..alerts.integrations import job_failed as emit_job_failed
from ..alerts.integrations import job_succeeded as emit_job_succeeded
from ..audit import logger
from ..config import get_config
from .models import TERMINAL_STATUSES, Job, JobPage, JobPriority, JobStatus, JobSummary
from .repository import JobRepository
from .runner import JobRunner

_SENSITIVE = ("password", "passwd", "secret", "token", "authorization", "credential", "cookie", "private_key")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")


def _sensitive_key(key: object) -> bool:
    normalized = str(key).casefold()
    if normalized in {"credential_id", "credential_ref"}:
        return False
    return any(marker in normalized for marker in _SENSITIVE)


def sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "[truncated]"
    if isinstance(value, Mapping):
        return {str(key)[:120]: "[REDACTED]" if _sensitive_key(key) else sanitize(nested, depth=depth + 1) for key, nested in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item, depth=depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return _BEARER_RE.sub("Bearer [REDACTED]", value)[:8000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]


class JobHandler(Protocol):
    def __call__(self, context: "JobContext", metadata: dict[str, Any]) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class HandlerRegistration:
    handler: JobHandler
    retryable: bool = False
    cancellable: bool = False
    max_retries: int = 0
    timeout: float | None = None


class JobContext:
    def __init__(self, service: "JobService", job_id: str) -> None:
        self.service = service
        self.job_id = job_id

    def update_progress(self, progress: int | None, message: str = "", *, current_step: str = "") -> Job | None:
        return self.service.update_progress(self.job_id, progress, message, current_step=current_step)

    def set_progress(self, progress: int | None, message: str = "", *, current_step: str = "") -> Job | None:
        return self.update_progress(progress, message, current_step=current_step)

    def log(self, level: str, message: str, **data: Any) -> None:
        self.service.log(self.job_id, level, message, data)

    def cancellation_requested(self) -> bool:
        job = self.service.get(self.job_id)
        return bool(job and job.cancel_requested)

    def raise_if_cancelled(self) -> None:
        if self.cancellation_requested():
            raise InterruptedError("Operation cancelled")


class JobService:
    def __init__(self, repository: JobRepository, runner: JobRunner | None = None) -> None:
        self.repository = repository
        self.runner = runner or JobRunner()
        self._handlers: dict[str, HandlerRegistration] = {}
        self._lock = threading.RLock()

    def recover(self) -> int:
        recovered = self.repository.recover_interrupted()
        if recovered:
            logger.warning("job_recovery interrupted=%d", recovered)
        return recovered

    def register_handler(self, job_type: str, handler: JobHandler, *, retryable: bool = False, cancellable: bool = False,
                         max_retries: int = 0, timeout: float | None = None) -> None:
        with self._lock:
            self._handlers[job_type] = HandlerRegistration(handler, retryable, cancellable, max(0, max_retries), timeout)

    def create_job(self, *, job_type: str, module: str, created_by: str, metadata: dict[str, Any] | None = None,
                   retryable: bool = False, cancellable: bool = False, parent_job_id: str | None = None,
                   retry_count: int = 0, name: str = "", description: str = "", priority: JobPriority = JobPriority.normal,
                   max_retries: int = 0, timeout: float | None = None, correlation_id: str | None = None,
                   dedup_key: str | None = None, dependencies: list[str] | None = None, total_steps: int | None = None) -> Job:
        if dedup_key:
            existing = self.repository.find_active_by_dedup(dedup_key)
            if existing:
                return existing
        status = JobStatus.waiting if dependencies else JobStatus.queued
        job = self.repository.create(job_type=job_type, module=module, created_by=created_by, metadata=sanitize(metadata or {}),
            retryable=retryable, cancellable=cancellable, parent_job_id=parent_job_id, retry_count=retry_count,
            name=name or job_type, description=description, priority=priority, max_retries=max_retries, timeout=timeout,
            correlation_id=correlation_id or uuid4().hex, dedup_key=dedup_key, status=status, total_steps=total_steps)
        self.repository.add_dependencies(job.id, dependencies or [])
        self.log(job.id, "info", "Job created", {"status": status.value, "priority": priority.value})
        return job

    def submit(self, *, job_type: str, module: str, created_by: str, metadata: dict[str, Any] | None = None,
               priority: JobPriority = JobPriority.normal, name: str = "", description: str = "",
               dependencies: list[str] | None = None, dedup_key: str | None = None,
               correlation_id: str | None = None, total_steps: int | None = None) -> Job:
        registration = self._handlers.get(job_type)
        if registration is None:
            raise KeyError(f"No job handler registered for {job_type}")
        job = self.create_job(job_type=job_type, module=module, created_by=created_by, metadata=metadata,
            retryable=registration.retryable, cancellable=registration.cancellable, priority=priority, name=name,
            description=description, max_retries=registration.max_retries, timeout=registration.timeout,
            dependencies=dependencies, dedup_key=dedup_key, correlation_id=correlation_id, total_steps=total_steps)
        if job.status == JobStatus.waiting:
            self._reconcile_waiting(job.id)
        elif job.status == JobStatus.queued:
            self._dispatch(job.id, registration)
        return self.get(job.id) or job

    def enqueue(self, **kwargs: Any) -> Job:
        return self.submit(**kwargs)

    def submit_callable(self, *, job_type: str, module: str, created_by: str, handler: JobHandler,
                        metadata: dict[str, Any] | None = None, retryable: bool = False, cancellable: bool = False,
                        priority: JobPriority = JobPriority.normal, max_retries: int = 0, timeout: float | None = None,
                        name: str = "", description: str = "", dedup_key: str | None = None,
                        correlation_id: str | None = None, total_steps: int | None = None) -> Job:
        job = self.create_job(job_type=job_type, module=module, created_by=created_by, metadata=metadata,
            retryable=retryable, cancellable=cancellable, priority=priority, max_retries=max_retries, timeout=timeout,
            name=name, description=description, dedup_key=dedup_key, correlation_id=correlation_id, total_steps=total_steps)
        self._dispatch(job.id, HandlerRegistration(handler, retryable, cancellable, max_retries, timeout))
        return self.get(job.id) or job

    def _dispatch(self, job_id: str, registration: HandlerRegistration) -> None:
        job = self.get(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return

        def execute() -> None:
            import threading as _threading
            running = self.repository.mark_running(job_id, _threading.current_thread().name)
            if running is None:
                return
            started = time.monotonic()
            self.log(job_id, "info", "Job started", {"worker": running.worker})
            context = JobContext(self, job_id)
            try:
                result = registration.handler(context, dict(running.metadata)) or {}
                context.raise_if_cancelled()
                elapsed = time.monotonic() - started
                if registration.timeout and elapsed > registration.timeout:
                    finished = self.repository.mark_timed_out(job_id, f"Job exceeded timeout of {registration.timeout:g}s")
                    if finished:
                        self.log(job_id, "error", finished.error)
                        emit_job_failed(finished)
                else:
                    finished = self.repository.mark_success(job_id, result=sanitize(result))
                    if finished and finished.status == JobStatus.success:
                        self.log(job_id, "info", "Job completed", {"duration_seconds": round(elapsed, 3)})
                        emit_job_succeeded(finished)
            except InterruptedError as error:
                finished = self.repository.mark_cancelled(job_id, message=str(error) or "Cancelled")
                if finished:
                    self.log(job_id, "warning", "Job cancelled")
            except Exception as error:  # noqa: BLE001
                message = str(sanitize(str(error))) or "Operation failed"
                failed = self.repository.mark_failed(job_id, message)
                if failed:
                    self.log(job_id, "error", message)
                    emit_job_failed(failed)
                    if registration.retryable and failed.retry_count < registration.max_retries:
                        self._schedule_retry(failed, registration)
            finally:
                self._release_dependents(job_id)

        self.runner.submit(job_id, execute, job.priority)

    def _schedule_retry(self, failed: Job, registration: HandlerRegistration) -> None:
        delay = min(60, 2 ** min(failed.retry_count, 6))
        retry = self.create_job(job_type=failed.type, module=failed.module, created_by=failed.created_by,
            metadata=failed.metadata, retryable=True, cancellable=registration.cancellable, parent_job_id=failed.id,
            retry_count=failed.retry_count + 1, name=failed.name, description=failed.description, priority=failed.priority,
            max_retries=failed.max_retries, timeout=failed.timeout, correlation_id=failed.correlation_id)
        self.repository.update(retry.id, status=JobStatus.retrying, message=f"Retrying in {delay}s")
        self.log(retry.id, "warning", "Automatic retry scheduled", {"delay_seconds": delay})
        timer = threading.Timer(delay, lambda: self._dispatch(retry.id, registration))
        timer.daemon = True
        timer.start()

    def _reconcile_waiting(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None or job.status != JobStatus.waiting:
            return
        states = self.repository.dependency_states(job_id)
        if any(state in {JobStatus.failed, JobStatus.cancelled, JobStatus.timed_out, JobStatus.blocked} for state in states):
            self.repository.mark_blocked(job_id, "One or more dependencies did not complete successfully")
            return
        if states and all(state == JobStatus.success for state in states):
            registration = self._handlers.get(job.type)
            if registration:
                self.repository.update(job_id, status=JobStatus.queued, message="Dependencies completed")
                self._dispatch(job_id, registration)

    def _release_dependents(self, job_id: str) -> None:
        for dependent in self.repository.dependents(job_id):
            self._reconcile_waiting(dependent)

    def get(self, job_id: str) -> Job | None:
        return self.repository.get(job_id)

    def list(self, **filters: Any) -> JobPage:
        return self.repository.list(**filters)

    def logs(self, job_id: str, *, limit: int = 250, offset: int = 0):
        return self.repository.logs(job_id, limit=limit, offset=offset)

    def summary(self) -> JobSummary:
        return JobSummary(**self.repository.summary(workers=self.runner.max_workers))

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return job
        if not job.cancellable:
            raise ValueError("Job is not cancellable")
        if self.runner.cancel_queued(job_id):
            cancelled = self.repository.mark_cancelled(job_id, message="Cancelled before execution")
        else:
            cancelled = self.repository.request_cancel(job_id)
        if cancelled:
            self.log(job_id, "warning", "Cancellation requested")
        return cancelled

    def retry(self, job_id: str, actor: str) -> Job:
        previous = self.get(job_id)
        if previous is None:
            raise LookupError("Job not found")
        if previous.status not in {JobStatus.failed, JobStatus.cancelled, JobStatus.timed_out, JobStatus.blocked} or not previous.retryable:
            raise ValueError("Job is not retryable")
        registration = self._handlers.get(previous.type)
        if registration is None or not registration.retryable:
            raise ValueError("No retry-safe handler is registered for this job type")
        retry = self.create_job(job_type=previous.type, module=previous.module, created_by=actor, metadata=previous.metadata,
            retryable=True, cancellable=registration.cancellable, parent_job_id=previous.id,
            retry_count=previous.retry_count + 1, name=previous.name, description=previous.description,
            priority=previous.priority, max_retries=previous.max_retries, timeout=previous.timeout,
            correlation_id=previous.correlation_id)
        self._dispatch(retry.id, registration)
        return self.get(retry.id) or retry

    def update_progress(self, job_id: str, progress: int | None, message: str = "", *, current_step: str = "") -> Job | None:
        if progress is not None:
            progress = min(max(int(progress), 0), 100)
        return self.repository.update(job_id, progress=progress, message=str(sanitize(message))[:1000], current_step=str(sanitize(current_step))[:240])

    def log(self, job_id: str, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        safe_level = level.casefold() if level.casefold() in {"debug", "info", "warning", "error"} else "info"
        self.repository.append_log(job_id, safe_level, str(sanitize(message))[:4000], sanitize(data or {}))

    def cleanup(self, *, retention_days: int = 30) -> int:
        return self.repository.cleanup(time.time() - max(1, retention_days) * 86400)

    def shutdown(self) -> None:
        self.runner.shutdown()


_service: JobService | None = None
_service_lock = threading.Lock()


def service() -> JobService:
    global _service
    with _service_lock:
        if _service is None:
            path = Path(get_config().paths.data_dir) / "jobs.sqlite3"
            _service = JobService(JobRepository(path))
            _service.recover()
        return _service
