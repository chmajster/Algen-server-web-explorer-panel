from __future__ import annotations

from app.identity.models import Role
from app.identity.permissions import PERMISSION_REGISTRY, ROLE_PERMISSIONS
from app.modules.compliance_manager import service as service_module
from app.modules.compliance_manager.checks import parse_sshd_config
from app.modules.compliance_manager.models import ComplianceControl, ComplianceSeverity, ComplianceStatus
from app.modules.compliance_manager.rbac import COMPLIANCE_SCAN, COMPLIANCE_VIEW
from app.modules.compliance_manager.service import ComplianceManagerService


def _control(control_id: str, status: ComplianceStatus, category: str = "ssh") -> ComplianceControl:
    return ComplianceControl(
        id=control_id,
        benchmark_id="cis-linux-level1",
        benchmark_ref="test",
        category=category,
        title=control_id,
        status=status,
        severity=ComplianceSeverity.medium,
        expected="expected",
        actual="actual",
        rationale="rationale",
        remediation="remediation",
    )


def test_sshd_parser_ignores_comments_and_match_blocks():
    values = parse_sshd_config(
        """
        # global comment
        PermitRootLogin no
        MaxAuthTries 4 # inline comment
        X11Forwarding no
        Match User legacy
            PermitRootLogin yes
        """
    )

    assert values["permitrootlogin"] == "no"
    assert values["maxauthtries"] == "4"
    assert values["x11forwarding"] == "no"


def test_summary_scores_only_automated_pass_fail_results(monkeypatch):
    sample = [
        _control("ssh.pass", ComplianceStatus.passed, "ssh"),
        _control("ssh.fail", ComplianceStatus.failed, "ssh"),
        _control("ssh.manual", ComplianceStatus.manual, "ssh"),
        _control("kernel.pass", ComplianceStatus.passed, "kernel"),
        _control("pam.error", ComplianceStatus.error, "pam"),
    ]
    monkeypatch.setattr(service_module, "run_checks", lambda: sample)
    service = ComplianceManagerService()

    result = service.scan()

    assert result.score == 67
    assert result.passed == 2
    assert result.failed == 1
    assert result.manual == 1
    assert result.error == 1
    assert result.total == 5
    assert result.categories["ssh"].score == 50
    assert result.categories["kernel"].score == 100
    assert result.categories["pam"].score is None
    assert service.controls(category="ssh") == sample[:3]
    assert service.controls(status="fail") == [sample[1]]


def test_compliance_permissions_are_registered_for_expected_roles():
    assert COMPLIANCE_VIEW in PERMISSION_REGISTRY
    assert COMPLIANCE_SCAN in PERMISSION_REGISTRY
    assert COMPLIANCE_VIEW in ROLE_PERMISSIONS[Role.auditor]
    assert COMPLIANCE_SCAN not in ROLE_PERMISSIONS[Role.auditor]
    assert {COMPLIANCE_VIEW, COMPLIANCE_SCAN}.issubset(ROLE_PERMISSIONS[Role.operator])
