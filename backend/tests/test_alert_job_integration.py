from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.alerts.models import RuleInput, SinkInput, SinkType
from app.alerts.service import AlertService
from app.jobs.models import JobStatus
from app.jobs.repository import JobRepository
from app.jobs.runner import JobRunner
from app.jobs.service import JobContext, JobService


def _wait(service: JobService, job_id: str) -> JobStatus:
    deadline = time.time() + 5
    while time.time() < deadline:
        item = service.get(job_id)
        if item and item.status in {JobStatus.success, JobStatus.failed, JobStatus.cancelled}:
            return item.status
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_real_job_failure_deduplicates_notifies_and_success_resolves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts = AlertService(tmp_path / "alerts.sqlite3", tmp_path / "alerts.key")
    sink = alerts.save_sink(
        SinkInput(
            name="test-webhook",
            type=SinkType.webhook,
            url="https://example.invalid/hooks/secret-path",
            token="delivery-secret",
        ),
        "admin",
    )
    default = next(rule for rule in alerts.list_rules() if rule["id"] == "durable-job-failure")
    alerts.save_rule(
        RuleInput(
            name=default["name"],
            source=default["source"],
            severity=default["severity"],
            cooldown_seconds=3600,
            enabled=True,
            matcher={},
            sink_ids=[sink["id"]],
        ),
        "admin",
        default["id"],
    )
    monkeypatch.setattr("app.alerts.integrations.service", lambda: alerts)
    delivered: list[dict] = []
    monkeypatch.setattr("app.alerts.service.deliver", lambda _sink, alert: delivered.append(alert))

    runner = JobRunner(max_workers=1)
    jobs = JobService(JobRepository(tmp_path / "jobs.sqlite3"), runner)

    def fail(_context: JobContext, _metadata: dict) -> dict:
        raise RuntimeError("password=hunter2 upstream unavailable")

    try:
        first = jobs.submit_callable(job_type="sync", module="inventory", created_by="admin", handler=fail)
        assert _wait(jobs, first.id) == JobStatus.failed
        second = jobs.submit_callable(job_type="sync", module="inventory", created_by="admin", handler=fail)
        assert _wait(jobs, second.id) == JobStatus.failed

        active = alerts.list_alerts(state="firing")
        assert len(active) == 1
        assert active[0]["occurrences"] == 2
        assert "hunter2" not in str(active[0]["details"])
        assert alerts.process_due_deliveries()["succeeded"] == 1
        assert len(delivered) == 1
        assert "delivery-secret" not in str(delivered[0])

        def succeed(_context: JobContext, _metadata: dict) -> dict:
            return {"ok": True}

        recovered = jobs.submit_callable(job_type="sync", module="inventory", created_by="admin", handler=succeed)
        assert _wait(jobs, recovered.id) == JobStatus.success
        resolved = alerts.list_alerts(state="resolved")
        assert len(resolved) == 1
        assert resolved[0]["id"] == active[0]["id"]
    finally:
        runner.shutdown()
