from __future__ import annotations

import http.client
import io
import json
import socket
import ssl
import sys
import urllib.error
from email.message import Message
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import HTTPException

from app.modules.providers import docker_registry_transport as registry
from app.modules.proxmox_manager import secure_client as proxmox


@pytest.fixture
def registry_connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"headers": [], "body": b"{}", "reads": [], "closed": False}
    monkeypatch.setattr(
        registry,
        "_validated_target",
        lambda *_args: (urlsplit("http://registry.example/v2/_catalog"), ["8.8.8.8"]),
    )

    class Response:
        status = 200

        def getheaders(self):
            return state["headers"]

        def read(self, amount: int = -1) -> bytes:
            state["reads"].append(amount)
            return state["body"][:amount]

    class Connection:
        def __init__(self, hostname: str, port: int, address: str, *, timeout: float) -> None:
            state["timeout"] = timeout

        def request(self, method: str, target: str, body=None, headers=None) -> None:
            state["request_headers"] = headers

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            state["closed"] = True

    monkeypatch.setattr(registry, "_PinnedHTTPConnection", Connection)
    return state


def _transport() -> registry._PinnedRegistryTransport:
    return registry._PinnedRegistryTransport(
        expected_host="registry.example", require_tls=False, verify=True, response_limit=1024,
    )


@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Encoding", "identity"), ("Content-Encoding", "gzip")],
        [("content-encoding", ""), ("CONTENT-ENCODING", "deflate")],
        [("Content-Encoding", "identity"), ("content-encoding", "identity, br")],
        [("Content-Encoding", " identity , GZip ")],
    ],
)
def test_registry_checks_every_content_encoding_before_reading(
    registry_connection: dict[str, Any], headers: list[tuple[str, str]],
) -> None:
    registry_connection["headers"] = headers
    with pytest.raises(HTTPException) as caught:
        _transport().handle_request(httpx.Request("GET", "http://registry.example/v2/_catalog"))
    assert caught.value.status_code == 502
    assert caught.value.detail["code"] == "UNSUPPORTED_REGISTRY_ENCODING"
    assert registry_connection["reads"] == []
    assert registry_connection["closed"] is True


@pytest.mark.parametrize(
    "headers", [[], [("Content-Encoding", "identity")], [("Content-Encoding", "identity, identity")]],
)
def test_registry_accepts_uncompressed_responses(
    registry_connection: dict[str, Any], headers: list[tuple[str, str]],
) -> None:
    registry_connection["headers"] = headers
    response = _transport().handle_request(httpx.Request("GET", "http://registry.example/v2/_catalog"))
    assert response.json() == {}
    assert registry_connection["reads"] == [1025]
    assert registry_connection["closed"] is True


def test_registry_sends_exactly_one_identity_accept_encoding(registry_connection: dict[str, Any]) -> None:
    request = httpx.Request(
        "GET", "http://registry.example/v2/_catalog",
        headers=[("Accept-Encoding", "gzip"), ("accept-encoding", "br"), ("Accept", "application/json")],
    )
    _transport().handle_request(request)
    encodings = [
        value for name, value in registry_connection["request_headers"].items()
        if name.lower() == "accept-encoding"
    ]
    assert encodings == ["identity"]
    assert registry_connection["request_headers"]["accept"] == "application/json"


@pytest.mark.parametrize("value", [float("inf"), "inf", float("nan"), -1, 0, {}, None])
def test_registry_invalid_connect_timeouts_have_a_finite_fallback(value: Any) -> None:
    request = httpx.Request("GET", "https://registry.example", extensions={"timeout": {"connect": value}})
    assert registry._connect_timeout(request) == 20.0


def test_registry_preserves_a_valid_connect_timeout() -> None:
    request = httpx.Request("GET", "https://registry.example", extensions={"timeout": {"connect": 8.0}})
    assert registry._connect_timeout(request) == 8.0


@pytest.mark.parametrize("verify", [True, False])
def test_registry_default_context_requires_tls12_even_when_certificate_verification_is_disabled(verify: bool) -> None:
    context = registry._tls_context(verify)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == (ssl.CERT_REQUIRED if verify else ssl.CERT_NONE)


def test_registry_preserves_an_explicit_ssl_context() -> None:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    assert registry._tls_context(context) is context


@pytest.fixture
def parser_payloads():
    # Exercise CPython's real integer-size and nesting guards without depending
    # on a developer's PYTHONINTMAXSTRDIGITS setting or changing the recursion limit.
    previous_limit = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        yield {
            "integer": b'{"data":' + b"9" * 5000 + b"}",
            "nested": b'{"data":' + b"[" * 10000 + b"0" + b"]" * 10000 + b"}",
            "json": b'{"remote-secret":invalid}',
            "utf8": b"\xffremote-secret",
        }
    finally:
        sys.set_int_max_str_digits(previous_limit)


@pytest.mark.parametrize("kind", ["integer", "nested", "json", "utf8"])
@pytest.mark.parametrize("status", [200, 401])
def test_registry_normalizes_parser_failures_and_preserves_authentication_challenges(
    monkeypatch: pytest.MonkeyPatch, parser_payloads: dict[str, bytes], kind: str, status: int,
) -> None:
    original_client = httpx.Client
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(
            status, content=parser_payloads[kind], headers={"WWW-Authenticate": 'Bearer realm="registry"'},
        )
        responses.append(response)
        return response

    def client_factory(**kwargs):
        return original_client(transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr(registry.httpx, "Client", client_factory)

    class Provider:
        pass

    registry.install_docker_registry_transport(Provider)
    fetch = getattr(Provider(), "_registry_fetch_json")
    arguments = {"expected_host": "registry.example", "require_tls": True, "verify": True}
    if status == 200:
        with pytest.raises(HTTPException) as caught:
            fetch("https://registry.example/v2/_catalog", **arguments)
        assert caught.value.status_code == 502
        assert caught.value.detail["code"] == "INVALID_REGISTRY_RESPONSE"
        assert "remote-secret" not in str(caught.value.detail)
    else:
        result_status, payload, headers = fetch("https://registry.example/v2/_catalog", **arguments)
        assert result_status == 401
        assert payload == {}
        assert headers["www-authenticate"] == 'Bearer realm="registry"'
    assert responses[0].is_closed


def _proxmox_client(stage: str) -> proxmox.HardenedProxmoxApiClient:
    return proxmox.HardenedProxmoxApiClient(
        "https://pve.example:8006",
        "audit@pve" if stage == "login" else "audit@pve!token",
        "test-secret",
        credential_type="username_password" if stage == "login" else "proxmox_api",
        verify_tls=False,
    )


def _invoke(client: proxmox.HardenedProxmoxApiClient, stage: str) -> Any:
    if stage == "login":
        return client._login()
    return client.request("GET", "version")


@pytest.mark.parametrize("stage", ["login", "api"])
@pytest.mark.parametrize("kind", ["integer", "nested", "json", "utf8"])
def test_proxmox_normalizes_invalid_json_and_encoding_without_exposing_the_body(
    monkeypatch: pytest.MonkeyPatch, parser_payloads: dict[str, bytes], stage: str, kind: str,
) -> None:
    client = _proxmox_client(stage)
    response = io.BytesIO(parser_payloads[kind])
    monkeypatch.setattr(client, "_open_no_redirect", lambda _request: response)
    with pytest.raises(proxmox._service.ProxmoxApiError) as caught:
        _invoke(client, stage)
    assert caught.value.stage == stage
    assert "remote-secret" not in str(caught.value)
    assert response.closed


@pytest.mark.parametrize("stage", ["login", "api"])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_proxmox_rejects_oversize_responses_without_rejecting_the_exact_limit(
    monkeypatch: pytest.MonkeyPatch, stage: str, offset: int,
) -> None:
    client = _proxmox_client(stage)
    limit = (1 if stage == "login" else 4) * 1024 * 1024
    data = {"ticket": "PVE:valid-ticket", "CSRFPreventionToken": "valid-csrf"} if stage == "login" else {"version": "test"}
    prefix = json.dumps({"data": data}).encode()
    response = io.BytesIO(prefix + b" " * (limit + offset - len(prefix)))
    monkeypatch.setattr(client, "_open_no_redirect", lambda _request: response)
    if offset > 0:
        with pytest.raises(proxmox._service.ProxmoxApiError) as caught:
            _invoke(client, stage)
        assert caught.value.stage == stage
        assert "safety limit" in caught.value.reason
    elif stage == "login":
        _invoke(client, stage)
        assert client.ticket == data["ticket"]
        assert client.csrf_token == data["CSRFPreventionToken"]
    else:
        assert _invoke(client, stage) == data
    assert response.closed


@pytest.mark.parametrize("stage", ["login", "api"])
@pytest.mark.parametrize("kind", ["incomplete", "status-line"])
def test_proxmox_normalizes_broken_http_responses(
    monkeypatch: pytest.MonkeyPatch, stage: str, kind: str,
) -> None:
    client = _proxmox_client(stage)
    failure = (
        http.client.IncompleteRead(b"remote-secret", 20) if kind == "incomplete"
        else http.client.BadStatusLine("remote-secret")
    )

    class Response(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise failure

    response = Response()
    monkeypatch.setattr(client, "_open_no_redirect", lambda _request: response)
    with pytest.raises(proxmox._service.ProxmoxApiError) as caught:
        _invoke(client, stage)
    assert caught.value.stage == stage
    assert "remote-secret" not in str(caught.value)
    assert response.closed


@pytest.mark.parametrize("stage", ["login", "api"])
@pytest.mark.parametrize("kind", ["incomplete", "timeout", "recursive", "normal", "invalid-json"])
def test_proxmox_preserves_http_status_and_closes_error_bodies(
    monkeypatch: pytest.MonkeyPatch, stage: str, kind: str,
) -> None:
    client = _proxmox_client(stage)
    failures = {
        "incomplete": http.client.IncompleteRead(b"remote-secret", 20),
        "timeout": socket.timeout("remote-secret"),
        "recursive": RecursionError("remote-secret"),
    }

    class ErrorBody(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            if kind in failures:
                raise failures[kind]
            return super().read(size)

    body = ErrorBody(b'{"message":"permission denied"}' if kind == "normal" else b"not-json")
    http_error = urllib.error.HTTPError(client.endpoint, 403, "Forbidden", Message(), body)

    def open_request(_request):
        raise http_error

    monkeypatch.setattr(client, "_open_no_redirect", open_request)
    with pytest.raises(proxmox._service.ProxmoxApiError) as caught:
        _invoke(client, stage)
    assert caught.value.status == 403
    assert caught.value.stage == stage
    assert "remote-secret" not in str(caught.value)
    if kind == "normal":
        assert "permission denied" in caught.value.reason
    assert body.closed


@pytest.mark.parametrize("field", ["ticket", "CSRFPreventionToken"])
@pytest.mark.parametrize("value", [123, True, ["value"], {"key": "value"}, "bad\r\nheader", "bad\x00value", "\u2603", " "])
def test_proxmox_rejects_non_string_and_header_unsafe_login_tokens(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any,
) -> None:
    client = _proxmox_client("login")
    data = {"ticket": "PVE:valid-ticket", "CSRFPreventionToken": "valid-csrf", field: value}
    response = io.BytesIO(json.dumps({"data": data}).encode())
    monkeypatch.setattr(client, "_open_no_redirect", lambda _request: response)
    with pytest.raises(proxmox._service.ProxmoxApiError) as caught:
        client._login()
    assert caught.value.stage == "login"
    assert client.ticket == ""
    assert client.csrf_token == ""
    assert response.closed
