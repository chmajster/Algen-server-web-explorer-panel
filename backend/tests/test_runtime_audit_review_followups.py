from __future__ import annotations

import importlib
import socket

import pytest
from fastapi import HTTPException

from app.ldap_authentication import connection as ldap_connection
from app.modules.providers.infrastructure import ApiConnectionProvider


@pytest.mark.parametrize("url", [
    "http://api.internal:70000", "http://api.internal:not-a-port", "http://api.internal:-1",
    "http://api.internal:0", "http://[::1", "http://[not-an-ipv6]/", "https://api.internal:999999999999",
])
def test_module_api_invalid_url_and_port_return_422_before_dns(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    def unexpected_dns(*args, **kwargs):
        raise AssertionError("invalid URL must be rejected before DNS")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_dns)
    with pytest.raises(HTTPException) as caught:
        ApiConnectionProvider._validated_base_target(url)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "INVALID_API_URL"


@pytest.mark.parametrize("url,port", [("http://api.internal/prefix", 80), ("https://api.internal/prefix", 443), ("http://api.internal:8080/prefix", 8080)])
def test_module_api_valid_ports_and_prefix_are_preserved(monkeypatch: pytest.MonkeyPatch, url: str, port: int) -> None:
    queries = []

    def dns(host, selected_port, **kwargs):
        queries.append((host, selected_port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", selected_port))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    normalized, parsed, addresses = ApiConnectionProvider._validated_base_target(url)
    assert normalized == url
    assert parsed.path == "/prefix"
    assert queries == [("api.internal", port)]
    assert addresses == ["10.0.0.10"]


@pytest.mark.parametrize("all_unsafe", [False, True])
def test_ldap_unsafe_dns_never_connects_and_does_not_prevent_safe_failover(monkeypatch: pytest.MonkeyPatch, all_unsafe: bool) -> None:
    service = importlib.import_module("app.ldap_authentication.service")
    lookups = []
    opened = []

    def dns(host, port, **kwargs):
        lookups.append(host)
        address = "169.254.169.254" if all_unsafe or host == "unsafe.example" else "10.0.0.20"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    class Connection:
        def __init__(self, server, **kwargs):
            assert server.host == "healthy.example"
            assert kwargs["auto_referrals"] is False
            self.server = server

        def open(self):
            opened.append((self.server.host, self.server.candidate_addresses()[0][4][0]))

        def start_tls(self):
            pass

        def bind(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(ldap_connection, "Connection", Connection)
    settings = {
        "servers": [{"host": "unsafe.example", "port": 389, "priority": 1}, {"host": "healthy.example", "port": 389, "priority": 2}],
        "security_mode": "starttls", "verify_tls": True, "bind_dn": "cn=service,dc=example",
    }
    if all_unsafe:
        with pytest.raises(service.LdapServiceUnavailable) as caught:
            service._service_connection(settings, "test-password")
        assert caught.value.code == "LDAP_CONNECT_FAILED"
        assert opened == []
    else:
        connection, endpoint = service._service_connection(settings, "test-password")
        assert connection.server.host == endpoint.host == "healthy.example"
        assert opened == [("healthy.example", "10.0.0.20")]
    assert lookups == ["unsafe.example", "healthy.example"]
