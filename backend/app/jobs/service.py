from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..audit import logger
from ..config import get_config
from .models import TERMINAL_STATUSES, Job, JobPage, JobStatus
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
        return {
            str(key)[:120]: "[REDACTED]" if _sensitive_key(key) else sanitize(nested, depth=depth + 1)
            for key, nested in list(value.items())[:100]
        }
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


class JobContext:
    def __init__(self, service: "JobService", job_id: str) -> None:
        self.service = service
        self.job_id = job_id

    def update_progress(self, progress: int | None, message: str = "") -> Job | None:
        return self.service.update_progress(self.job_id, progress, message)

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

    def register_handler(self, job_type: str, handler: JobHandler, *, retryable: bool = False, cancellable: bool = False) -> None:
        with self._lock:
            self._handlers[job_type] = HandlerRegistration(handler, retryable, cancellable)

    def create_job(
        self,
        *,
        job_type: str,
        module: str,
        created_by: str,
        metadata: dict[str, Any] | None = None,
        retryable: bool = False,
        cancellable: bool = False,
        parent_job_id: str | None = None,
        retry_count: int = 0,
    ) -> Job:
        job = self.repository.create(
            job_type=job_type,
            module=module,
            created_by=created_by,
            metadata=sanitize(metadata or {}),
            retryable=retryable,
            cancellable=cancellable,
            parent_job_id=parent_job_id,
            retry_count=retry_count,
        )
        logger.info("job_created job_id=%s job_type=%s module=%s", job.id, job.type, job.module)
        return job

    def submit(
        self,
        *,
        job_type: str,
        module: str,
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        registration = self._handlers.get(job_type)
        if registration is None:
            raise KeyError(f"No job handler registered for {job_type}")
        job = self.create_job(
            job_type=job_type,
            module=module,
            created_by=created_by,
            metadata=metadata,
            retryable=registration.retryable,
            cancellable=registration.cancellable,
        )
        self._dispatch(job.id, registration)
        return self.get(job.id) or job

    def submit_callable(
        self,
        *,
        job_type: str,
        module: str,
        created_by: str,
        handler: JobHandler,
        metadata: dict[str, Any] | None = None,
        retryable: bool = False,
        cancellable: bool = False,
    ) -> Job:
        job = self.create_job(
            job_type=job_type,
            module=module,
            created_by=created_by,
            metadata=metadata,
            retryable=retryable,
            cancellable=cancellable,
        )
        self._dispatch(job.id, HandlerRegistration(handler, retryable, cancellable))
        return self.get(job.id) or job

    def _dispatch(self, job_id: str, registration: HandlerRegistration) -> None:
        def execute() -> None:
            job = self.repository.mark_running(job_id)
            if job is None:
                return
            logger.info("job_started job_id=%s job_type=%s module=%s", job.id, job.type, job.module)
            context = JobContext(self, job_id)
            try:
                result = registration.handler(context, dict(job.metadata)) or {}
                context.raise_if_cancelled()
                finished = self.repository.mark_success(job_id, result=sanitize(result))
                if finished:
                    logger.info("job_succeeded job_id=%s job_type=%s module=%s", finished.id, finished.type, finished.module)
            except InterruptedError as error:
                finished = self.repository.mark_cancelled(job_id, message=str(error) or "Cancelled")
                if finished:
                    logger.info("job_cancelled job_id=%s job_type=%s module=%s", finished.id, finished.type, finished.module)
            except Exception as error:  # noqa: BLE001
                message = str(sanitize(str(error))) or "Operation failed"
                failed = self.repository.mark_failed(job_id, message)
                if failed:
                    logger.error("job_failed job_id=%s job_type=%s module=%s error=%s", failed.id, failed.type, failed.module, message)

        self.runner.submit(job_id, execute)

    def get(self, job_id: str) -> Job | None:
        return self.repository.get(job_id)

    def list(self, **filters: Any) -> JobPage:
        return self.repository.list(**filters)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return job
        if not job.cancellable:
            raise ValueError("Job is not cancellable")
        cancelled = self.repository.request_cancel(job_id)
        if cancelled:
            logger.info("job_cancel_requested job_id=%s job_type=%s module=%s", cancelled.id, cancelled.type, cancelled.module)
        return cancelled

    def retry(self, job_id: str, actor: str) -> Job:
        previous = self.get(job_id)
        if previous is None:
            raise LookupError("Job not found")
        if previous.status not in {JobStatus.failed, JobStatus.cancelled} or not previous.retryable:
            raise ValueError("Job is not retryable")
        registration = self._handlers.get(previous.type)
        if registration is None or not registration.retryable:
            raise ValueError("No retry-safe handler is registered for this job type")
        retry = self.create_job(
            job_type=previous.type,
            module=previous.module,
            created_by=actor,
            metadata=previous.metadata,
            retryable=True,
            cancellable=registration.cancellable,
            parent_job_id=previous.id,
            retry_count=previous.retry_count + 1,
        )
        self._dispatch(retry.id, registration)
        logger.info("job_retry job_id=%s parent_job_id=%s job_type=%s module=%s", retry.id, previous.id, retry.type, retry.module)
        return self.get(retry.id) or retry

    def update_progress(self, job_id: str, progress: int | None, message: str = "") -> Job | None:
        if progress is not None:
            progress = min(max(int(progress), 0), 100)
        return self.repository.update(job_id, progress=progress, message=str(sanitize(message))[:1000])


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
