from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"
    retrying = "retrying"
    waiting = "waiting"


TERMINAL_STATUSES = {JobStatus.success, JobStatus.failed, JobStatus.cancelled}


class Job(BaseModel):
    id: str
    type: str
    module: str
    status: JobStatus
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    created_by: str
    progress: int | None = Field(default=None, ge=0, le=100)
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    retryable: bool = False
    cancellable: bool = False
    cancel_requested: bool = False
    parent_job_id: str | None = None


class JobPage(BaseModel):
    items: list[Job]
    total: int
    limit: int
    offset: int
