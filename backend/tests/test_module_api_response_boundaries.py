from __future__ import annotations

import io
from urllib.parse import urlsplit

import pytest

from app.modules.providers import infrastructure


class WireSocket:
    def __init__(self, wire: bytes) -> None:
        self.file = io.BytesIO(wire)
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def makefile(self, mode: str) -> io.BytesIO:
        return self.file

    def close(self) -> None:
        self.closed = True


def provider_with_responses(monkeypatch: pytest.MonkeyPatch, *wires: bytes):
    provider = object.__new__(infrastructure.ApiConnectionProvider)
    url = "http://api.internal"
    monkeypatch.setattr(provider, "connection", lambda: {"base_url": url})
    monkeypatch.setattr(provider, "_validated_base_target", lambda _: (url, urlsplit(url), ["10.0.0.1", "10.0.0.2"]))
    sockets: list[WireSocket] = []

    def connect(address, timeout):
        sock = WireSocket(wires[len(sockets)])
        sockets.append(sock)
        return sock

    monkeypatch.setattr(infrastructure.socket, "create_connection", connect)
    return provider, sockets


def response(body: bytes, *, length: int | None = None) -> bytes:
    size = len(body) if length is None else length
    return f"HTTP/1.1 200 OK\r\nContent-Length: {size}\r\nConnection: close\r\n\r\n".encode() + body


def test_truncated_json_prefix_is_rejected_and_read_only_failover_is_preserved(monkeypatch):
    provider, sockets = provider_with_responses(monkeypatch, response(b"{}", length=20), response(b'{"complete":true}'))
    assert provider._request("/health") == {"complete": True}
    assert len(sockets) == 2
    assert all(sock.closed and sock.file.closed for sock in sockets)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("wire", [response(b"{}", length=20), b""])
def test_mutating_request_is_not_replayed_after_incomplete_or_missing_response(monkeypatch, method, wire):
    provider, sockets = provider_with_responses(monkeypatch, wire, response(b"{}"))
    with pytest.raises(RuntimeError, match="outcome is unknown"):
        provider._request("/command", method=method, payload={"action": "start"})
    assert len(sockets) == 1
    assert sockets[0].sent[0].startswith(method.encode() + b" ")
    assert sockets[0].closed and sockets[0].file.closed


@pytest.mark.parametrize("body", [b"NaN", b"1e400", b"[" * 129 + b"]" * 129, b"not json", b"\xff"])
def test_invalid_json_is_reported_without_response_content(monkeypatch, body):
    provider, sockets = provider_with_responses(monkeypatch, response(body))
    with pytest.raises(RuntimeError, match="^Module API returned invalid JSON$"):
        provider._request("/health")
    assert len(sockets) == 1
    assert sockets[0].closed and sockets[0].file.closed


@pytest.mark.parametrize("body, expected", [(b"", {}), (b"{}", {}), (b"[]", []), (b'{"value":1.5}', {"value": 1.5})])
def test_complete_responses_at_the_size_limit_are_preserved(monkeypatch, body, expected):
    monkeypatch.setattr(infrastructure, "MAX_API_RESPONSE", len(body))
    provider, sockets = provider_with_responses(monkeypatch, response(body))
    assert provider._request("/health") == expected
    assert sockets[0].closed and sockets[0].file.closed
