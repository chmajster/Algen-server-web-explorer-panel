from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.jobs.models import JobPriority, JobStatus
from app.jobs.repository import JobRepository
from app.modules.gitops_manager.models import RepositoryInput
from app.modules.gitops_manager.service import GitOpsService
from app.modules.login_history.service import LoginHistoryService
from app.modules.ntp_manager.models import NtpBackend, NtpSourceInput
from app.modules.ntp_manager.service import NtpService
from app.modules.routing_manager.models import PolicyRuleInput, RouteInput
from app.privileged_broker.infrastructure_policy import InfrastructurePolicyError, _validate_ip_args


def test_job_priority_dependencies_and_structured_logs(tmp_path: Path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    parent = repository.create(job_type="parent", module="tests", created_by="alice", priority=JobPriority.high)
    child = repository.create(job_type="child", module="tests", created_by="alice", status=JobStatus.waiting)
    repository.add_dependencies(child.id, [parent.id])
    repository.append_log(child.id, "info", "waiting for parent", {"parent": parent.id})

    assert repository.get(parent.id).priority == JobPriority.high
    assert repository.dependency_states(child.id) == [JobStatus.queued]
    logs = repository.logs(child.id)
    assert logs[0].message == "waiting for parent"
    assert logs[0].data["parent"] == parent.id


def test_ntp_parser_and_managed_block():
    service = NtpService()
    parsed = service._kv("Stratum : 3\nLast offset : -0.000123 seconds\n")
    assert parsed["stratum"] == "3"
    assert "-0.000123" in parsed["last offset"]

    config = "server distro.pool iburst\n# BEGIN WEBNAS NTP\nserver time1.example iburst prefer\n# server time2.example iburst\n# END WEBNAS NTP\n"
    managed = service._managed_sources(config)
    assert [item.server for item in managed] == ["time1.example", "time2.example"]
    assert managed[0].prefer is True
    assert managed[1].enabled is False

    rendered = service._render(NtpBackend.timesyncd, "[Time]\nFallbackNTP=fallback.example\n", [NtpSourceInput(server="time.example")])
    assert "# BEGIN WEBNAS NTP" in rendered
    assert "NTP=time.example" in rendered


def test_ntp_source_validation_rejects_path_like_input():
    with pytest.raises(ValidationError):
        NtpSourceInput(server="../../etc/passwd")


def test_login_history_parses_success_failure_and_pam():
    service = LoginHistoryService()
    success = service.parse_row({"MESSAGE": "Accepted publickey for alice from 192.0.2.10 port 4444 ssh2", "__REALTIME_TIMESTAMP": "1000000"})
    failure = service.parse_row({"MESSAGE": "Failed password for invalid user root from 2001:db8::10 port 22 ssh2", "__REALTIME_TIMESTAMP": "2000000"})
    pam = service.parse_row({"MESSAGE": "pam_unix(login:session): session opened for user bob(uid=1000)", "__REALTIME_TIMESTAMP": "3000000"})

    assert success and success["result"] == "success" and success["source_ip"] == "192.0.2.10"
    assert failure and failure["result"] == "failure" and failure["source_ip"] == "2001:db8::10"
    assert pam and pam["session_type"] == "local" and pam["event"] == "login"


def test_login_security_correlation_detects_bruteforce_and_spray(monkeypatch: pytest.MonkeyPatch):
    service = LoginHistoryService()
    events = [
        {"source_ip": "192.0.2.50", "username": f"user{index % 6}", "result": "failure"}
        for index in range(24)
    ]
    monkeypatch.setattr(service, "events", lambda **_kwargs: {"items": events})
    findings = service.security_findings(brute_force_threshold=20, spray_users=5)
    types = {item["type"] for item in findings}
    assert "brute_force" in types
    assert "password_spray" in types


def test_gitops_remote_validation_blocks_embedded_passwords():
    RepositoryInput(remote="https://git.example/repo.git", branch="main")
    RepositoryInput(remote="git@github.com:example/repo.git", branch="main")
    with pytest.raises(ValidationError):
        RepositoryInput(remote="https://alice:secret@git.example/repo.git", branch="main")
    with pytest.raises(ValidationError):
        RepositoryInput(remote="file:///tmp/repo", branch="main")


def test_gitops_secret_scanner_redacts_and_allowlists(tmp_path: Path):
    service = object.__new__(GitOpsService)
    service.root = tmp_path
    service.settings_path = tmp_path / "settings.json"
    webnas = tmp_path / "webnas"
    webnas.mkdir()
    (webnas / "config.yaml").write_text("api_token: ghp_123456789012345678901234567890\n", encoding="utf-8")
    (webnas / "modules.json").write_text("{}\n", encoding="utf-8")
    findings = service.scan_secrets()
    assert findings
    assert findings[0]["value"] == "[REDACTED]"
    with pytest.raises(ValueError, match="Commit blocked"):
        service._ensure_clean_secret_scan()
    with pytest.raises(ValueError):
        service._safe_path("../secrets.txt")


def test_routing_models_validate_families_and_policy_rules():
    route = RouteInput(destination="10.10.0.0/24", gateway="10.10.0.1", interface="eth0", metric=100)
    assert route.destination == "10.10.0.0/24"
    with pytest.raises(ValidationError):
        RouteInput(destination="10.10.0.0/24", gateway="2001:db8::1")
    rule = PolicyRuleInput(source="10.10.0.0/24", destination="all", table="100", family=4)
    assert rule.table == "100"


def test_privileged_routing_policy_rejects_unbounded_commands():
    assert _validate_ip_args(["-4", "route", "replace", "default", "via", "192.0.2.1", "dev", "eth0"])[1] == "route"
    with pytest.raises(InfrastructurePolicyError):
        _validate_ip_args(["-4", "route", "flush", "table", "main"])
    with pytest.raises(InfrastructurePolicyError):
        _validate_ip_args(["-4", "route", "replace", "default", "--batch", "/tmp/x"])
