from __future__ import annotations

import http.client
import importlib
import io
import json
import ssl
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import HTTPException

from app import json_limits
from app.modules.ldap_manager.models import ConnectionInput
from app.modules.ldap_manager.repository import LdapManagerRepository
from app.modules.providers import docker_registry_transport as registry
from app.modules.proxmox_manager import secure_client as proxmox


class WireSocket:
    """Socket double with real HTTP parsing, but no external network access."""

    def __init__(self, wire: bytes, timeout: float) -> None:
        self.file = io.BytesIO(wire)
        self.timeout = timeout
        self.read_timeouts: list[float] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendall(self, data: bytes) -> None:
        pass

    def makefile(self, mode: str) -> io.BytesIO:
        self.read_timeouts.append(self.timeout)
        return self.file

    def close(self) -> None:
        self.closed = True


def registry_wire(monkeypatch: pytest.MonkeyPatch, wire: bytes, scheme: str = "http"):
    port = 443 if scheme == "https" else 80
    parsed = urlsplit(f"{scheme}://registry.example/v2/_catalog")
    monkeypatch.setattr(registry, "_validated_target", lambda *_args: (parsed, ["192.0.2.10"]))
    sockets: list[WireSocket] = []
    connects: list[tuple[tuple[str, int], float]] = []
    handshakes: list[tuple[str, float]] = []

    def create_connection(address: tuple[str, int], timeout: float) -> WireSocket:
        connects.append((address, timeout))
        sock = WireSocket(wire, timeout)
        sockets.append(sock)
        return sock

    def wrap_socket(_context, sock: WireSocket, *, server_hostname: str) -> WireSocket:
        handshakes.append((server_hostname, sock.timeout))
        return sock

    monkeypatch.setattr(registry.socket, "create_connection", create_connection)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap_socket)
    transport = registry._PinnedRegistryTransport(
        expected_host="registry.example", require_tls=scheme == "https", verify=True, response_limit=1024,
    )
    request = httpx.Request("GET", parsed.geturl(), extensions={"timeout": {"connect": 8.0, "read": 20.0}})
    return transport, request, sockets, connects, handshakes, port


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_registry_applies_read_timeout_after_connect_and_tls_handshake(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    wire = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
    transport, request, sockets, connects, handshakes, port = registry_wire(monkeypatch, wire, scheme)
    assert transport.handle_request(request).json() == {}
    assert connects == [(("192.0.2.10", port), 8.0)]
    assert sockets[0].read_timeouts == [20.0]
    assert sockets[0].closed
    assert sockets[0].file.closed
    assert handshakes == ([("registry.example", 8.0)] if scheme == "https" else [])


@pytest.mark.parametrize("value", [None, {}, "nan", "inf", -1, 0])
def test_registry_invalid_read_timeout_uses_finite_default(value: Any) -> None:
    request = httpx.Request("GET", "https://registry.example", extensions={"timeout": {"read": value}})
    assert registry._read_timeout(request) == 20.0


def test_registry_preserves_explicit_read_timeout() -> None:
    request = httpx.Request("GET", "https://registry.example", extensions={"timeout": {"connect": 8.0, "read": 45.0}})
    assert registry._connect_timeout(request) == 8.0
    assert registry._read_timeout(request) == 45.0


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_registry_rejects_truncated_http_body_even_when_prefix_is_valid_json(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    wire = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\n{}"
    transport, request, sockets, _, _, _ = registry_wire(monkeypatch, wire, scheme)
    with pytest.raises(httpx.ConnectError):
        transport.handle_request(request)
    assert sockets[0].closed
    assert sockets[0].file.closed


@pytest.mark.parametrize("status", [200, 401, 403, 500])
@pytest.mark.parametrize("body", [b"[]", b"null", b"true", b"42", b'"denied"'])
def test_registry_non_object_error_json_preserves_original_status_and_challenge(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes,
) -> None:
    original_client = httpx.Client
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(status, content=body, headers={"WWW-Authenticate": 'Bearer realm="registry"'})
        responses.append(response)
        return response

    monkeypatch.setattr(registry.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler)))

    class Provider:
        pass

    registry.install_docker_registry_transport(Provider)
    fetch = getattr(Provider(), "_registry_fetch_json")
    if status == 200:
        with pytest.raises(HTTPException) as caught:
            fetch("https://registry.example/v2/_catalog", expected_host="registry.example", require_tls=True, verify=True)
        assert caught.value.status_code == 502
        assert caught.value.detail["code"] == "INVALID_REGISTRY_RESPONSE"
    else:
        code, payload, headers = fetch("https://registry.example/v2/_catalog", expected_host="registry.example", require_tls=True, verify=True)
        assert code == status
        assert payload == {}
        assert headers["www-authenticate"] == 'Bearer realm="registry"'
    assert responses[0].is_closed


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"])
@pytest.mark.parametrize("wrapper", ["{}", '[{}]', '{{"nested": {}}}'])
def test_json_boundary_rejects_non_finite_numbers(number: str, wrapper: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        json_limits.loads_with_depth_limit(wrapper.format(number))


@pytest.mark.parametrize("text", ['{"value":1.25}', '{"value":1e-300}', '{"value":-0.0}', '{"value":"NaN"}'])
def test_json_boundary_preserves_finite_numbers_and_plain_strings(text: str) -> None:
    value = json_limits.loads_with_depth_limit(text)
    assert value == json.loads(text)
    json.dumps(value, allow_nan=False)


@pytest.mark.parametrize("stage", ["login", "api"])
@pytest.mark.parametrize("kind", ["truncated", "non-finite"])
def test_proxmox_normalizes_incomplete_and_non_finite_responses(
    monkeypatch: pytest.MonkeyPatch, stage: str, kind: str,
) -> None:
    client = proxmox.HardenedProxmoxApiClient(
        "https://pve.example:8006", "audit@pve" if stage == "login" else "audit@pve!token", "test-secret",
        credential_type="username_password" if stage == "login" else "proxmox_api", verify_tls=False,
    )
    data = {"ticket": "PVE:ticket", "CSRFPreventionToken": "csrf"} if stage == "login" else {"version": "test"}
    body = json.dumps({"data": data, "metric": float("inf") if kind == "non-finite" else 1}).encode()
    wire = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body) + (10 if kind == "truncated" else 0)).encode() + b"\r\n\r\n" + body
    sock = WireSocket(wire, 20.0)
    response = http.client.HTTPResponse(sock)
    response.begin()
    monkeypatch.setattr(client, "_open_no_redirect", lambda _request: response)
    with pytest.raises(proxmox._service.ProxmoxApiError) as caught:
        client._login() if stage == "login" else client.request("GET", "version")
    assert caught.value.stage == stage
    assert response.closed
    assert sock.file.closed
    assert client.ticket == ""
    assert "test-secret" not in str(caught.value)


@pytest.fixture
def ldap_saved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    secrets: dict[str, str] = {}
    calls: list[str] = []

    class SecretStore:
        def save(self, payload, actor, secret_id=None):
            calls.append("save")
            identifier = secret_id or "test-bind-secret"
            if payload.secret:
                secrets[identifier] = payload.secret
            return {"id": identifier}

        def delete(self, secret_id, actor):
            calls.append("delete")
            secrets.pop(secret_id, None)

    module = importlib.import_module("app.modules.ldap_manager.repository")
    monkeypatch.setattr(module, "secrets_service", lambda: SecretStore())
    repository = LdapManagerRepository(tmp_path / "ldap.sqlite3")
    payload = ConnectionInput(
        name="Directory", servers=[{"host": "ldap.example", "port": 636}],
        security_mode="ldaps", base_dn="dc=example", bind_dn="cn=bind,dc=example", bind_password="preserve-me",
    )
    saved = repository.save(payload, "admin")
    calls.clear()
    return repository, payload, saved["id"], secrets, calls


def test_rejected_ldap_password_clear_preserves_secret_and_connection(ldap_saved) -> None:
    repository, payload, identifier, secrets, calls = ldap_saved
    before = repository.get(identifier, include_secret_id=True)
    request = ConnectionInput.model_validate({**payload.model_dump(), "bind_password": "", "clear_bind_password": True})
    with pytest.raises(ValueError, match="requires its own bind password"):
        repository.save(request, "admin", identifier)
    assert calls == []
    assert secrets == {"test-bind-secret": "preserve-me"}
    assert repository.get(identifier, include_secret_id=True) == before


@pytest.mark.parametrize("mode", ["unknown", "", "LDAPS"])
def test_corrupted_ldap_security_mode_never_silently_downgrades_to_plaintext(ldap_saved, mode: str) -> None:
    repository, _, identifier, _, _ = ldap_saved
    with repository.connect() as connection:
        connection.execute("UPDATE ldap_manager_connections SET security_mode=? WHERE id=?", (mode, identifier))
    assert repository.get(identifier)["security_mode"] == "starttls"


def test_settings_type_checks_are_not_suppressed_for_the_entire_module() -> None:
    path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    settings = tomllib.loads(path.read_text(encoding="utf-8"))["tool"]["mypy"]
    for override in settings.get("overrides", []):
        modules = override.get("module", [])
        modules = [modules] if isinstance(modules, str) else modules
        if "app.settings" in modules:
            assert not {"arg-type", "call-overload"}.intersection(override.get("disable_error_code", []))
