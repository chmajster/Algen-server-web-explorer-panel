from __future__ import annotations

import hashlib
import importlib
import hmac
import json
import socket
from pathlib import Path

import pytest

from app.modules.webhook_manager.events import event_types
from app.modules.webhook_manager.models import WebhookInput
from app.modules.webhook_manager.service import WebhookManagerService, WebhookValidationError

webhook_module = importlib.import_module("app.modules.webhook_manager.service")


def _payload(**overrides) -> WebhookInput:
    values = {
        "name": "operations",
        "description": "test webhook",
        "enabled": True,
        "url": "https://8.8.8.8/webnas",
        "method": "POST",
        "events": ["fail2ban.ip_banned"],
        "timeout_seconds": 5,
        "max_attempts": 3,
        "headers": {"X-Environment": "test"},
        "auth_type": "none",
        "secret_id": None,
        "auth_header_name": "X-API-Key",
        "signing_secret_id": None,
        "allow_private_networks": False,
    }
    values.update(overrides)
    return WebhookInput.model_validate(values)


def test_ssrf_blocks_local_metadata_and_private_by_default(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")

    for url in (
        "http://127.0.0.1/hook",
        "http://[::1]/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/hook",
        "https://user:pass@8.8.8.8/hook",
    ):
        with pytest.raises(WebhookValidationError):
            service.validate_url(url, allow_private=False)

    assert service.validate_url("http://10.0.0.5/hook", allow_private=True)["resolved_addresses"] == ["10.0.0.5"]
    assert service.validate_url("https://8.8.8.8/hook", allow_private=False)["scheme"] == "https"


def test_ssrf_rejects_hostname_if_any_resolution_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ],
    )

    with pytest.raises(WebhookValidationError, match="blocked address"):
        service.validate_url("https://hooks.example.invalid/path", allow_private=False)


def test_transport_connects_to_validated_ip_and_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
        ],
    )
    validation = service.validate_url(
        "http://hooks.example.invalid/path?kind=test",
        allow_private=False,
    )
    calls: list[tuple[tuple[str, int], float | None]] = []

    class FakeSocket:
        def __init__(self) -> None:
            self.sent = b""

        def settimeout(self, timeout: float) -> None:
            assert timeout == 5

        def sendall(self, data: bytes) -> None:
            self.sent += data

        def close(self) -> None:
            return None

    fake_socket = FakeSocket()

    def create_connection(address, timeout=None):
        calls.append((address, timeout))
        return fake_socket

    class FakeResponse:
        status = 302

        def __init__(self, transport) -> None:
            assert transport is fake_socket

        def begin(self) -> None:
            return None

        def read(self, amount: int) -> bytes:
            assert amount == 2048
            return b"redirect refused"

        def close(self) -> None:
            return None

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(webhook_module.http.client, "HTTPResponse", FakeResponse)

    status, preview = service._pinned_request(
        validation=validation,
        method="POST",
        headers={"Content-Type": "application/json"},
        body=b"{}",
        timeout=5,
    )

    assert calls == [(('8.8.8.8', 80), 5)]
    assert b"POST /path?kind=test HTTP/1.1" in fake_socket.sent
    assert b"Host: hooks.example.invalid" in fake_socket.sent
    assert status == 302
    assert preview == "redirect refused"


def test_auth_and_hmac_use_secrets_manager_without_persisting_plaintext(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    metadata = {
        "auth-id": {"id": "auth-id", "shared_with": ["webhook-manager"]},
        "sign-id": {"id": "sign-id", "shared_with": ["webhook-manager"]},
    }
    monkeypatch.setattr(webhook_module, "secret_metadata", lambda secret_id: metadata.get(secret_id))

    def verified(secret_id: str, *, module_id: str, purpose: str):
        assert module_id == "webhook-manager"
        assert purpose.startswith("webhook-")
        if secret_id == "auth-id":
            return {"id": secret_id, "type": "api_token", "username": "", "secret": "bearer-value", "passphrase": ""}
        return {"id": secret_id, "type": "generic_secret", "username": "", "secret": "signing-value", "passphrase": ""}

    monkeypatch.setattr(webhook_module, "verified_secret", verified)
    saved = service.save(
        _payload(auth_type="bearer", secret_id="auth-id", signing_secret_id="sign-id"),
        "admin",
    )
    timestamp = 1_777_777_777
    body = service._canonical_payload("event-id", "fail2ban.ip_banned", timestamp, {"jail": "sshd", "ip": "192.0.2.10"})
    headers = service._headers(saved, event_id="event-id", event_type="fail2ban.ip_banned", timestamp=timestamp, body=body)

    assert headers["Authorization"] == "Bearer bearer-value"
    expected = hmac.new(b"signing-value", str(timestamp).encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    assert headers["X-WebNAS-Signature"] == f"sha256={expected}"

    with service.connect() as connection:
        row = connection.execute("SELECT * FROM webhooks WHERE id=?", (saved["id"],)).fetchone()
    assert row is not None
    persisted = json.dumps(dict(row))
    assert "bearer-value" not in persisted
    assert "signing-value" not in persisted
    assert "auth-id" in persisted
    assert "sign-id" in persisted


def test_secret_reference_must_be_shared_with_webhook_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    monkeypatch.setattr(
        webhook_module,
        "secret_metadata",
        lambda secret_id: {"id": secret_id, "shared_with": ["hosts-manager"]},
    )

    with pytest.raises(WebhookValidationError, match="not shared"):
        service.save(_payload(auth_type="bearer", secret_id="host-only"), "admin")


def test_event_subscription_enqueues_redacted_nonblocking_work(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    saved = service.save(_payload(), "admin")

    event_id = service.enqueue_event(
        "fail2ban.ip_banned",
        {"jail": "sshd", "ip": "192.0.2.10", "password": "must-not-leak"},
    )

    assert event_id
    assert service._queue.qsize() == 1
    item = service._queue.get_nowait()
    assert item is not None
    webhook_id, queued_event_id, event_type, payload = item
    assert webhook_id == saved["id"]
    assert queued_event_id == event_id
    assert event_type == "fail2ban.ip_banned"
    assert "must-not-leak" not in json.dumps(payload)


def test_retry_reloads_webhook_and_stops_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    saved = service.save(_payload(max_attempts=3), "admin")
    attempts: list[int] = []

    def failed_once(webhook, event_id, event_type, payload, attempt):
        attempts.append(attempt)
        service.set_enabled(saved["id"], False, "admin")
        return {"id": "delivery-1", "status": "failed"}

    monkeypatch.setattr(service, "_deliver_once", failed_once)
    monkeypatch.setattr(service._stop, "wait", lambda timeout: False)

    service._deliver_with_retries(saved["id"], "event-id", "fail2ban.ip_banned", {})
    assert attempts == [1]


def test_only_wired_events_are_advertised_by_default():
    current = set(event_types())
    assert "fail2ban.ip_banned" in current
    assert "secret.created" in current
    assert "host.created" not in current
    assert "operation.completed" not in current
    assert "backup.completed" not in current


def test_unknown_event_is_rejected(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    with pytest.raises(WebhookValidationError, match="unknown webhook event"):
        service.save(_payload(events=["unknown.event.never-registered"]), "admin")
