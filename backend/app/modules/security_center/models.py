from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"
    passed = "passed"


class FindingStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class SecurityFinding(BaseModel):
    id: str
    check_id: str
    severity: Severity
    title: str
    description: str
    affected_resource: str
    detection_source: str
    recommendation: str
    timestamp: float
    status: FindingStatus = FindingStatus.open
    category: str
    evidence: dict[str, object] = Field(default_factory=dict)


class FindingStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: FindingStatus
