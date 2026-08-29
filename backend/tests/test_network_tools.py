from __future__ import annotations

import pytest

from app.modules.network_tools.models import DnsLookupRequest, HttpTestRequest, PortTestRequest, TargetRequest
from app.modules.network_tools.service import NetworkToolError, NetworkToolsService


def test_target_validation_accepts_host_and_ip() -> None:
    assert TargetRequest(target="example.com").target == "example.com"
    assert TargetRequest(target="192.0.2.1").target == "192.0.2.1"


def test_target_validation_rejects_shell_payload() -> None:
    with pytest.raises(ValueError):
        TargetRequest(target="example.com;id")


def test_port_validation() -> None:
    with pytest.raises(ValueError):
        PortTestRequest(target="example.com", port=70000)


def test_dns_server_must_be_ip() -> None:
    with pytest.raises(ValueError):
        DnsLookupRequest(hostname="example.com", server="resolver.example")


def test_http_rejects_credentials() -> None:
    with pytest.raises(ValueError):
        HttpTestRequest(url="https://user:password@example.com/")


def test_rate_limit_is_enforced() -> None:
    service = NetworkToolsService()
    for _ in range(30):
        service.admit("tester")
    with pytest.raises(NetworkToolError):
        service.admit("tester")
