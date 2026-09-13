from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from app.modules.os_repositories import auth_proxy
from app.modules.providers.infrastructure import ApiConnectionProvider
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
                "not-a-timestamp",
                "also-not-a-timestamp",
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
    assert item["created_at"] == 0.0
    assert item["updated_at"] == 0.0


def test_webhook_shutdown_does_not_enqueue_stale_stop_sentinel(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")
    service.startup()
    service.shutdown()

    assert service._queue.empty()

    service.startup()
    assert service._worker is not None
    assert service._worker.is_alive()
    service.shutdown()


def test_webhook_shutdown_keeps_worker_reference_when_join_times_out(tmp_path: Path):
    service = WebhookManagerService(tmp_path / "webhooks.sqlite3")

    class BusyWorker:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            assert timeout == 3

    worker = BusyWorker()
    service._worker = cast(Any, worker)
    service.shutdown()

    assert service._worker is worker
    service.startup()
    assert service._worker is worker


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


def test_module_api_request_uses_address_from_private_dns_validation(monkeypatch: pytest.MonkeyPatch):
    provider = ApiConnectionProvider("runtime-audit")
    monkeypatch.setattr(provider, "connection", lambda: {"base_url": "http://api.internal"})
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 80))],
    )
    selected: list[str] = []

    class Response:
        status = 200

        def read(self, _amount: int = -1) -> bytes:
            return b"{}"

    class Connection:
        def request(self, method: str, path: str, body=None, headers=None) -> None:
            assert method == "GET"
            assert path == "/health"

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            return None

    def pinned_connection(parsed, address: str, timeout: int):
        selected.append(address)
        assert parsed.hostname == "api.internal"
        return cast(Any, Connection())

    monkeypatch.setattr(provider, "_connection", pinned_connection)

    assert provider._request("/health") == {}
    assert selected == ["10.20.30.40"]
