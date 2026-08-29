from __future__ import annotations

from pathlib import Path

from app.modules.security_center.models import FindingStatus, SecurityFinding, Severity
from app.modules.security_center.repository import SecurityStateRepository
from app.modules.security_center.service import SecurityCenterService


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
