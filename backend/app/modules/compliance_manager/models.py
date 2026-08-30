from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ComplianceStatus(StrEnum):
    passed = "pass"
    failed = "fail"
    manual = "manual"
    error = "error"
    not_applicable = "not_applicable"


class ComplianceSeverity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class ComplianceControl(BaseModel):
    id: str
    benchmark_id: str
    benchmark_ref: str
    profile: str = "level1"
    category: str
    title: str
    status: ComplianceStatus
    severity: ComplianceSeverity
    expected: str
    actual: str
    rationale: str
    remediation: str
    evidence: dict[str, object] = Field(default_factory=dict)


class ComplianceCategorySummary(BaseModel):
    score: int | None
    passed: int
    failed: int
    manual: int
    error: int
    not_applicable: int
    total: int


class ComplianceSummary(BaseModel):
    score: int | None
    passed: int
    failed: int
    manual: int
    error: int
    not_applicable: int
    total: int
    last_scan: float | None
    categories: dict[str, ComplianceCategorySummary]
