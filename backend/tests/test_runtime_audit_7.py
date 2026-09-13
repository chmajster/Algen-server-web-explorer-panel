from __future__ import annotations

import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from app.modules.os_repositories import auth_proxy
from app.modules.webhook_manager.models import WebhookInput
from app.modules.webhook_manager.service import WebhookManagerService


def _webhook_payload(**overrides):
    payload = {
        "name": "audit",
        "url": "https://8.8.8.8/hook",
        "events": ["fail2ban.ip_banned"],
        "headers": {},
        "auth_type": "none",
        "auth_header_name": "X-API-Key",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "headers",
    [
        {"Bad Header": "value"},
        {"Connection": "keep-alive"},
        {"content-type": "text/plain"},
        {"x-webnas-event": "forged.event"},
        {"X-Test": "one", "x-test": "two"},
        {"X-Test": "value\x01control"},
    ],
)
def test_webhook_rejects_malformed_managed_and_ambiguous_headers(headers):
    with pytest.raises(ValidationError):
        WebhookInput.model_validate(_webhook_payload(headers=headers))


@pytest.mark.parametrize(
    "name",
    ["Bad Header", "Connection", "Content-Length", "x-webnas-signature", "User-Agent"],
)
def test_webhook_rejects_unsafe_auth_header_names(name):
    with pytest.raises(ValidationError):
        WebhookInput.model_validate(
            _webhook_payload(auth_type="api_key_header", secret_id="secret", auth_header_name=name)
        )


def test_corrupted_persisted_webhook_is_disabled_before_delivery(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    now = time.time()
    with service.connect() as connection:
        connection.execute(
            """
            INSERT INTO webhooks(
                id,name,description,enabled,url,method,events_json,timeout_seconds,max_attempts,
                headers_json,auth_type,secret_id,auth_header_name,signing_secret_id,
                allow_private_networks,created_at,updated_at,created_by,updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "corrupt",
                "corrupt",
                "",
                1,
                "https://8.8.8.8/hook",
                "POST\r\nX-Injected: yes",
                '["fail2ban.ip_banned"]',
                10,
                3,
                '{"Connection":"keep-alive"}',
                "none",
                None,
                "X-API-Key",
                None,
                0,
                now,
                now,
                "admin",
                "admin",
            ),
        )

    item = service.webhook("corrupt")
    assert item is not None
    assert item["enabled"] is False
    assert item["configuration_valid"] is False
    assert item["headers"] == {}
    assert item["method"] == "POST"


def test_webhook_shutdown_does_not_enqueue_stale_stop_sentinel(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    service.startup()
    service.shutdown()

    assert service._queue.empty()

    service.startup()
    assert service._worker is not None
    assert service._worker.is_alive()
    service.shutdown()


def test_authenticated_mirror_connection_uses_validated_address(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[tuple[str, int], float | object]] = []

    class FakeSocket:
        def close(self) -> None:
            return None

    def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr(socket, "create_connection", create_connection)
    connection = auth_proxy._connection_for(
        urlsplit("http://mirror.example.invalid/repository"),
        "203.0.113.10",
        timeout=7,
    )
    connection.connect()

    assert connection.host == "mirror.example.invalid"
    assert calls == [(('203.0.113.10', 80), 7)]
