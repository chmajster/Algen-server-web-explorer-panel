from __future__ import annotations

import logging

from ..core.redaction import redact_text
from ..jobs.models import Job
from .models import AlertEvent, AlertSeverity
from .service import service


logger = logging.getLogger(__name__)


def job_event_key(job: Job) -> str:
    return f"{job.module}:{job.type}"


def job_failed(job: Job) -> None:
    try:
        service().fire(
            AlertEvent(
                source="job.failed",
                key=job_event_key(job),
                title=f"Job failed: {job.module} / {job.type}",
                object_ref=job.id,
                severity=AlertSeverity.error,
                details={
                    "job_id": job.id,
                    "job_type": job.type,
                    "module": job.module,
                    "retry_count": job.retry_count,
                    "error": redact_text(job.error or job.message, limit=2000),
                },
            )
        )
    except Exception:  # noqa: BLE001 - monitoring must not alter job outcome
        logger.exception("job_alert_emit_failed job_id=%s", job.id)


def job_succeeded(job: Job) -> None:
    try:
        service().resolve("job.failed", job_event_key(job), "system")
    except Exception:  # noqa: BLE001 - monitoring must not alter job outcome
        logger.exception("job_alert_resolve_failed job_id=%s", job.id)
