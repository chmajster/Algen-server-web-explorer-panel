from __future__ import annotations

import threading
import time
from functools import lru_cache

from .checks import CATEGORIES, benchmark_metadata, run_checks
from .models import ComplianceCategorySummary, ComplianceControl, ComplianceStatus, ComplianceSummary


class ComplianceManagerService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_scan: float | None = None
        self._controls: list[ComplianceControl] = []

    @staticmethod
    def _score(controls: list[ComplianceControl]) -> int | None:
        measured = [item for item in controls if item.status in {ComplianceStatus.passed, ComplianceStatus.failed}]
        if not measured:
            return None
        passed = sum(1 for item in measured if item.status == ComplianceStatus.passed)
        return round(100 * passed / len(measured))

    @staticmethod
    def _counts(controls: list[ComplianceControl]) -> dict[str, int]:
        return {
            "passed": sum(1 for item in controls if item.status == ComplianceStatus.passed),
            "failed": sum(1 for item in controls if item.status == ComplianceStatus.failed),
            "manual": sum(1 for item in controls if item.status == ComplianceStatus.manual),
            "error": sum(1 for item in controls if item.status == ComplianceStatus.error),
            "not_applicable": sum(1 for item in controls if item.status == ComplianceStatus.not_applicable),
            "total": len(controls),
        }

    def scan(self) -> ComplianceSummary:
        controls = run_checks()
        with self._lock:
            self._controls = controls
            self._last_scan = time.time()
        return self.summary()

    def controls(self, category: str | None = None, status: str | None = None) -> list[ComplianceControl]:
        with self._lock:
            values = list(self._controls)
        if category:
            values = [item for item in values if item.category == category]
        if status:
            values = [item for item in values if item.status.value == status]
        return values

    def summary(self) -> ComplianceSummary:
        with self._lock:
            controls = list(self._controls)
            last_scan = self._last_scan
        counts = self._counts(controls)
        categories: dict[str, ComplianceCategorySummary] = {}
        for category in CATEGORIES:
            values = [item for item in controls if item.category == category]
            category_counts = self._counts(values)
            categories[category] = ComplianceCategorySummary(score=self._score(values), **category_counts)
        return ComplianceSummary(score=self._score(controls), last_scan=last_scan, categories=categories, **counts)

    @staticmethod
    def benchmarks() -> dict[str, object]:
        item = benchmark_metadata()
        return {"items": [item], "total": 1}


@lru_cache
def service() -> ComplianceManagerService:
    return ComplianceManagerService()
