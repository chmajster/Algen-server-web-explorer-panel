from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import Any

from ...activity import ActivityCategory, ActivityStatus, record_activity
from .checks import run_checks
from .models import FindingStatus, SecurityFinding, Severity
from .repository import SecurityStateRepository


WEIGHTS = {Severity.critical: 25, Severity.high: 15, Severity.medium: 8, Severity.low: 3, Severity.info: 0, Severity.passed: 0}
AREAS = ("firewall", "authentication", "updates", "network", "tls", "users", "permissions", "system")


class SecurityCenterService:
    def __init__(self, repository: SecurityStateRepository | None = None) -> None:
        self.repository = repository or SecurityStateRepository()
        self._lock = threading.RLock()
        self._last_scan: dict[str, Any] = {"timestamp": None, "findings": [], "metrics": {}}

    @staticmethod
    def score(findings: list[SecurityFinding]) -> int:
        penalty = sum(WEIGHTS[item.severity] for item in findings if item.status != FindingStatus.resolved)
        return max(0, min(100, 100 - penalty))

    def scan(self) -> dict[str, Any]:
        detected, metrics = run_checks()
        states = self.repository.states()
        for item in detected:
            configured = states.get(item.id)
            if configured == FindingStatus.acknowledged.value:
                item.status = FindingStatus.acknowledged
        with self._lock:
            self._last_scan = {"timestamp": time.time(), "findings": detected, "metrics": metrics}
        return self.summary()

    def _snapshot(self) -> tuple[list[SecurityFinding], dict[str, dict[str, Any]], float | None]:
        with self._lock:
            return list(self._last_scan["findings"]), dict(self._last_scan["metrics"]), self._last_scan["timestamp"]

    def findings(self) -> list[SecurityFinding]:
        values, _metrics, _timestamp = self._snapshot()
        return values

    def set_status(self, finding_id: str, status: FindingStatus, actor: str) -> SecurityFinding:
        item = next((item for item in self.findings() if item.id == finding_id), None)
        if item is None:
            raise LookupError("security finding was not found")
        self.repository.set_state(item.id, status, actor)
        item.status = status
        with self._lock:
            for index, existing in enumerate(self._last_scan["findings"]):
                if existing.id == item.id:
                    self._last_scan["findings"][index] = item
                    break
        record_activity(ActivityCategory.module, "security.finding.state", actor, target=item.id, status=ActivityStatus.success, details={"status": status.value, "check_id": item.check_id}, source="security-center")
        return item

    def summary(self) -> dict[str, Any]:
        findings, metrics, timestamp = self._snapshot()
        active = [item for item in findings if item.status != FindingStatus.resolved]
        severity = {level.value: sum(1 for item in active if item.severity == level) for level in Severity}
        if timestamp is None:
            return {"score": None, "severity": severity, "areas": {}, "metrics": {}, "findings": 0, "last_scan": None}
        areas: dict[str, dict[str, Any]] = {}
        for area in AREAS:
            relevant = [item for item in active if item.category == area or area == "system" and item.category == "system"]
            areas[area] = {"score": self.score(relevant), "findings": len(relevant), "critical": sum(1 for item in relevant if item.severity == Severity.critical), "high": sum(1 for item in relevant if item.severity == Severity.high)}
        return {"score": self.score(active), "severity": severity, "areas": areas, "metrics": metrics, "findings": len(active), "last_scan": timestamp}


@lru_cache
def service() -> SecurityCenterService:
    return SecurityCenterService()
