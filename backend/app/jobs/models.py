from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    queued = "queued"
    waiting = "waiting"
    running = "running"
    success = "success"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"
    timed_out = "timed_out"
    retrying = "retrying"
    blocked = "blocked"


class JobPriority(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


TERMINAL_STATUSES = {JobStatus.success, JobStatus.failed, JobStatus.cancelled, JobStatus.timed_out, JobStatus.blocked}
ACTIVE_STATUSES = {JobStatus.queued, JobStatus.waiting, JobStatus.running, JobStatus.cancel_requested, JobStatus.retrying}


class Job(BaseModel):
    id: str
    type: str
    module: str
    name: str = ""
    description: str = ""
    status: JobStatus
    priority: JobPriority = JobPriority.normal
    progress: int | None = Field(default=None, ge=0, le=100)
    current_step: str = ""
    total_steps: int | None = Field(default=None, ge=0)
    created_at: float
    queued_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    created_by: str
    worker: str = ""
    retry_count: int = 0
    max_retries: int = 0
    timeout: float | None = Field(default=None, gt=0)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    cancellable: bool = False
    cancel_requested: bool = False
    parent_job_id: str | None = None
    correlation_id: str | None = None
    dedup_key: str | None = None


class JobLogEntry(BaseModel):
    id: int
    job_id: str
    created_at: float
    level: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class JobPage(BaseModel):
    items: list[Job]
    total: int
    limit: int
    offset: int


class JobSummary(BaseModel):
    running: int = 0
    queued: int = 0
    waiting: int = 0
    failed: int = 0
    completed_today: int = 0
    average_execution_seconds: float = 0
    workers: int = 0
