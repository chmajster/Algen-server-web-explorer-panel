from __future__ import annotations

import socket
import struct
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import network_diagnostics


PROC_SAMPLE = """
Inter-|   Receive                                                |  Transmit
 face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed
  eth0: 1000 10 2 3 0 0 0 0 2000 20 4 5 0 0 0 0
    lo:  500 5 0 0 0 0 0 0 500 5 0 0 0 0 0 0
"""


def test_parses_detailed_network_interface_counters():
    parsed = network_diagnostics.parse_proc_net_dev(PROC_SAMPLE)

    assert parsed["eth0"] == {
        "rx_bytes": 1000,
        "rx_packets": 10,
        "rx_errors": 2,
        "rx_dropped": 3,
        "tx_bytes": 2000,
        "tx_packets": 20,
        "tx_errors": 4,
        "tx_dropped": 5,
    }


def test_network_overview_calculates_rates_and_reads_link_metadata(monkeypatch):
    samples = iter([PROC_SAMPLE, PROC_SAMPLE.replace("1000 10", "1400 14").replace("2000 20", "2600 26")])
    sysfs = {"operstate": "up", "speed": "1000", "mtu": "1500", "carrier": "1", "duplex": "full", "address": "00:11:22:33:44:55"}
    monkeypatch.setattr(network_diagnostics, "_read_text", lambda path, limit=0: next(samples) if str(path) == "/proc/net/dev" else "")
    monkeypatch.setattr(network_diagnostics, "_sysfs_text", lambda interface, field: sysfs.get(field, "") if interface == "eth0" else "")
    monkeypatch.setattr(network_diagnostics, "_interface_addresses", lambda: ({"eth0": [{"family": "ipv4", "address": "192.0.2.10", "prefix_length": 24, "scope": "global"}]}, None))
    network_diagnostics._last_network_sample = None

    first = network_diagnostics.network_overview(now=10.0)
    second = network_diagnostics.network_overview(now=12.0)
    interface = next(item for item in second["interfaces"] if item["name"] == "eth0")

    assert first["interfaces"][0]["rx_bytes_per_sec"] is None
    assert interface["rx_bytes_per_sec"] == 200.0
    assert interface["tx_bytes_per_sec"] == 300.0
    assert interface["rx_errors"] == 2
    assert interface["tx_dropped"] == 5
    assert interface["speed_mbps"] == 1000
    assert interface["addresses"][0]["address"] == "192.0.2.10"


def test_parses_resolver_configuration_and_per_link_servers():
    resolv = network_diagnostics.parse_resolv_conf(
        "nameserver 127.0.0.53\nsearch lan.example example.test\noptions edns0 trust-ad\n"
    )
    resolved = network_diagnostics.parse_resolvectl_map(
        "Global: 1.1.1.1\nLink 2 (eth0): 192.0.2.53 2001:db8::53\n"
    )

    assert resolv == {"nameservers": ["127.0.0.53"], "search": ["lan.example", "example.test"], "options": ["edns0", "trust-ad"]}
    assert resolved == {"global": ["1.1.1.1"], "eth0": ["192.0.2.53", "2001:db8::53"]}


@pytest.mark.parametrize("hostname", ["example.com;reboot", "../example.com", "https://example.com", "192.0.2.1", "-invalid.example"])
def test_dns_test_rejects_non_hostname_input(hostname):
    with pytest.raises(ValidationError):
        network_diagnostics.DnsTestRequest(hostname=hostname)


def test_dns_response_parser_returns_a_records():
    query_id = 1234
    question = network_diagnostics._dns_question("example.com", query_id)[12:]
    message = struct.pack("!HHHHHH", query_id, 0x8180, 1, 1, 0, 0) + question
    message += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("192.0.2.25")

    assert network_diagnostics._parse_dns_response(message, query_id) == ("NOERROR", ["192.0.2.25"])


def test_dns_diagnostics_queries_only_configured_servers(monkeypatch):
    configuration = {
        "resolv_conf": {"nameservers": ["127.0.0.53"]},
        "systemd_resolved": {"global_servers": ["1.1.1.1"], "links": [{"interface": "eth0", "servers": ["192.0.2.53"]}]},
    }
    queried: list[tuple[str, str]] = []
    monkeypatch.setattr(network_diagnostics, "dns_configuration", lambda: configuration)
    monkeypatch.setattr(
        network_diagnostics,
        "_query_dns_server",
        lambda server, hostname: queried.append((server, hostname)) or {"server": server, "success": True, "rcode": "NOERROR", "addresses": ["192.0.2.25"], "latency_ms": 1.2, "error": None},
    )

    result = network_diagnostics.test_dns_resolution("example.com")

    assert set(queried) == {("127.0.0.53", "example.com"), ("1.1.1.1", "example.com"), ("192.0.2.53", "example.com")}
    assert result["addresses"] == ["192.0.2.25"]


def test_routing_snapshot_uses_only_fixed_read_commands(monkeypatch):
    calls: list[list[str]] = []

    def ip_json(arguments):
        calls.append(arguments)
        if "route" in arguments:
            return ([{"dst": "default", "gateway": "192.0.2.1", "dev": "eth0", "metric": 100}], None)
        return ([{"priority": 32766, "src": "all", "table": "main"}], None)

    monkeypatch.setattr(network_diagnostics, "_ip_json", ip_json)

    result = network_diagnostics.routing_snapshot()

    assert calls == [
        ["-4", "route", "show", "table", "all"],
        ["-4", "rule", "show"],
        ["-6", "route", "show", "table", "all"],
        ["-6", "rule", "show"],
    ]
    assert result["read_only"] is True
    assert result["gateways"][0] == {"family": "ipv4", "address": "192.0.2.1", "device": "eth0", "metric": 100, "table": "main"}


def test_network_routes_are_registered_read_only():
    registered = {(method, route.path) for route in network_diagnostics.router.routes for method in route.methods}

    assert ("GET", "/api/admin/network/overview") in registered
    assert ("GET", "/api/admin/network/dns") in registered
    assert ("POST", "/api/admin/network/dns/test") in registered
    assert ("GET", "/api/admin/network/routing") in registered
    assert ("POST", "/api/admin/network/connectivity/test") in registered
    assert not any(method in {"PUT", "PATCH", "DELETE"} for method, _path in registered)


def test_endpoints_ignore_session_values_as_command_arguments(monkeypatch):
    monkeypatch.setattr(network_diagnostics, "routing_snapshot", lambda: {"read_only": True})

    assert network_diagnostics.routing_endpoint(SimpleNamespace(username="; ip route flush table main")) == {"read_only": True}


def test_connectivity_target_validation_rejects_command_text():
    with pytest.raises(ValidationError):
        network_diagnostics.ConnectivityTestRequest(kind="ping", target="example.com; reboot")
    with pytest.raises(ValidationError):
        network_diagnostics.ConnectivityTestRequest(kind="tcp", target="example.com", port=70000)


def test_ping_uses_a_fixed_argument_array(monkeypatch):
    calls = []
    monkeypatch.setattr(network_diagnostics.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        network_diagnostics,
        "_run_command",
        lambda command, timeout=0: calls.append((command, timeout)) or subprocess.CompletedProcess(command, 0, "ok", ""),
    )

    result = network_diagnostics.test_connectivity("ping", "192.0.2.1")

    assert calls == [(["/usr/bin/ping", "-c", "3", "-W", "2", "192.0.2.1"], 15)]
    assert result["success"] is True
