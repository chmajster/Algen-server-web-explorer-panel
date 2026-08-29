from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.alerts.delivery import DeliveryError
from app.alerts.models import AlertEvent, AlertSeverity, RuleInput, SinkInput, SinkType
from app.alerts.service import AlertService


def _service(tmp_path: Path) -> AlertService:
    return AlertService(
        tmp_path / "alerts.sqlite3",
        tmp_path / "alerts.key",
    )


def _sink(service: AlertService) -> dict:
    return service.save_sink(
        SinkInput(
            name="ops-webhook",
            type=SinkType.webhook,
            url="https://example.invalid/webnas",
            token="super-secret-token",
        ),
        "admin",
    )


def _attach_job_rule(service: AlertService, sink_id: str, cooldown: int = 300) -> None:
    service.save_rule(
        RuleInput(
            name="Failed durable job",
            source="job.failed",
            severity=AlertSeverity.error,
            cooldown_seconds=cooldown,
            sink_ids=[sink_id],
        ),
        "admin",
        "durable-job-failure",
    )


def test_failed_event_is_deduplicated_and_cooldown_suppresses_repeat_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _service(tmp_path)
    sink = _sink(manager)
    _attach_job_rule(manager, sink["id"], cooldown=3600)

    first = manager.fire(
        AlertEvent(
            source="job.failed",
            key="package-center:install",
            title="Install failed",
            object_ref="job-1",
            details={"password": "do-not-leak", "error": "token=abc123 connection failed"},
        )
    )
    second = manager.fire(
        AlertEvent(
            source="job.failed",
            key="package-center:install",
            title="Install failed again",
            object_ref="job-2",
            details={"secret": "another-secret", "error": "password=hunter2 timeout"},
        )
    )

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] == second[0]["id"]
    assert first[0]["queued_deliveries"] == 1
    assert second[0]["queued_deliveries"] == 0
    assert second[0]["occurrences"] == 2
    assert second[0]["details"]["secret"] == "[REDACTED]"
    assert "hunter2" not in second[0]["details"]["error"]

    delivered: list[tuple[dict, dict]] = []
    monkeypatch.setattr("app.alerts.service.deliver", lambda configured_sink, alert: delivered.append((configured_sink, alert)))
    result = manager.process_due_deliveries()
    assert result == {"processed": 1, "succeeded": 1, "retry": 0, "failed": 0}
    assert len(delivered) == 1
    assert delivered[0][0]["token"] == "super-secret-token"
    assert "super-secret-token" not in str(delivered[0][1])
    assert "do-not-leak" not in str(delivered[0][1])

    public_sink = manager.list_sinks()[0]
    assert public_sink["configured"] is True
    assert "token" not in public_sink
    assert "url" not in public_sink
    assert "encrypted_config" not in public_sink


def test_acknowledged_alert_does_not_repeat_until_condition_resolves(tmp_path: Path) -> None:
    manager = _service(tmp_path)
    sink = _sink(manager)
    _attach_job_rule(manager, sink["id"], cooldown=0)
    alert = manager.fire(AlertEvent(source="job.failed", key="m:t", title="Failed"))[0]

    acknowledged = manager.acknowledge(alert["id"], "operator", "working on it")
    assert acknowledged is not None
    assert acknowledged["state"] == "acknowledged"

    repeated = manager.fire(AlertEvent(source="job.failed", key="m:t", title="Still failed"))[0]
    assert repeated["state"] == "acknowledged"
    assert repeated["queued_deliveries"] == 0

    resolved = manager.resolve("job.failed", "m:t", "system")
    assert resolved[0]["state"] == "resolved"

    refired = manager.fire(AlertEvent(source="job.failed", key="m:t", title="Failed again"))[0]
    assert refired["state"] == "firing"
    assert refired["queued_deliveries"] == 1
    assert refired["acknowledged_by"] == ""


def test_delivery_retry_is_durable_bounded_and_error_text_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _service(tmp_path)
    sink = _sink(manager)
    _attach_job_rule(manager, sink["id"], cooldown=0)
    manager.fire(
        AlertEvent(
            source="job.failed",
            key="module:broken",
            title="Broken",
            details={"authorization": "Bearer private-value"},
        )
    )

    def failing_delivery(_sink: dict, _alert: dict) -> None:
        raise DeliveryError("password=never-store-this")

    monkeypatch.setattr("app.alerts.service.deliver", failing_delivery)
    for attempt in range(5):
        result = manager.process_due_deliveries()
        assert result["processed"] == 1
        with manager.connect() as connection:
            row = connection.execute("SELECT * FROM alert_deliveries").fetchone()
            assert row is not None
            assert int(row["attempt_count"]) == attempt + 1
            assert "never-store-this" not in str(row["last_error"])
            if attempt < 4:
                assert row["state"] == "retry"
                connection.execute("UPDATE alert_deliveries SET next_attempt_at=0")
            else:
                assert row["state"] == "failed"

    assert manager.process_due_deliveries()["processed"] == 0


def test_resolve_queues_state_change_notification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _service(tmp_path)
    sink = _sink(manager)
    _attach_job_rule(manager, sink["id"])
    manager.fire(AlertEvent(source="job.failed", key="x:y", title="Failed"))
    monkeypatch.setattr("app.alerts.service.deliver", lambda _sink, _alert: None)
    assert manager.process_due_deliveries()["succeeded"] == 1

    resolved = manager.resolve("job.failed", "x:y", "system")
    assert resolved[0]["state"] == "resolved"
    assert manager.process_due_deliveries()["succeeded"] == 1


def test_sink_configuration_is_encrypted_at_rest(tmp_path: Path) -> None:
    manager = _service(tmp_path)
    sink = _sink(manager)
    with manager.connect() as connection:
        row = connection.execute("SELECT encrypted_config FROM alert_sinks WHERE id=?", (sink["id"],)).fetchone()
    assert row is not None
    envelope = str(row["encrypted_config"])
    assert "super-secret-token" not in envelope
    assert manager.cipher.envelope_version(envelope) == "WAC2"
