from __future__ import annotations

from pathlib import Path

import importlib

from app.modules.security_center.models import FindingStatus, SecurityFinding, Severity
from app.modules.security_center.repository import SecurityStateRepository
from app.modules.security_center.service import SecurityCenterService

security_service_module = importlib.import_module("app.modules.security_center.service")


def _finding(severity: Severity, identifier: str = "a") -> SecurityFinding:
    return SecurityFinding(id=identifier, check_id=identifier, severity=severity, title="t", description="d", affected_resource="r", detection_source="s", recommendation="x", timestamp=1, category="firewall")


def test_security_score_is_bounded() -> None:
    assert SecurityCenterService.score([_finding(Severity.critical), _finding(Severity.high)]) == 60
    assert SecurityCenterService.score([_finding(Severity.critical, str(index)) for index in range(8)]) == 0


def test_resolved_finding_does_not_reduce_score() -> None:
    item = _finding(Severity.critical)
    item.status = FindingStatus.resolved
    assert SecurityCenterService.score([item]) == 100


def test_finding_state_repository(tmp_path: Path) -> None:
    repository = SecurityStateRepository(tmp_path / "security.sqlite3")
    repository.set_state("abc", FindingStatus.acknowledged, "admin")
    assert repository.states()["abc"] == "acknowledged"


def test_unscanned_summary_does_not_run_checks(tmp_path: Path, monkeypatch) -> None:
    repository = SecurityStateRepository(tmp_path / "security.sqlite3")
    service = SecurityCenterService(repository)
    monkeypatch.setattr(security_service_module, "run_checks", lambda: (_ for _ in ()).throw(AssertionError("scan must not run")))
    summary = service.summary()
    assert summary["score"] is None
    assert summary["last_scan"] is None


def test_resolved_finding_reopens_when_detected_again(tmp_path: Path, monkeypatch) -> None:
    repository = SecurityStateRepository(tmp_path / "security.sqlite3")
    repository.set_state("a", FindingStatus.resolved, "admin")
    service = SecurityCenterService(repository)
    monkeypatch.setattr(security_service_module, "run_checks", lambda: ([_finding(Severity.critical)], {}))
    service.scan()
    assert service.findings()[0].status == FindingStatus.open
