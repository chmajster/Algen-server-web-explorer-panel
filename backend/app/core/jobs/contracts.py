from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class JobStep(BaseModel):
    id: str
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    started_at: float | None = None
    finished_at: float | None = None


class JobSnapshot(BaseModel):
    id: str
    module_id: str
    operation: str
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100)
    steps: list[JobStep] = Field(default_factory=list)
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    retry_count: int = Field(default=0, ge=0)
    resumable: bool = False
    cancellable: bool = True
    message: str = ""
    error_code: str | None = None
    result: dict[str, Any] | None = None
    logs: list[str] = Field(default_factory=list)


class JobHandler(Protocol):
    def run(self, job: JobSnapshot) -> JobSnapshot: ...
    def cancel(self, job_id: str) -> None: ...
    def resume(self, job_id: str) -> JobSnapshot: ...
