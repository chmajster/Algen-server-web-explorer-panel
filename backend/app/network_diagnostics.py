from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from .audit import logger
from .identity.permissions import Permission, require_permission
from .security import SessionUser


router = APIRouter(prefix="/api/admin/network", tags=["network-diagnostics"])
INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,32}$")
MAX_COMMAND_OUTPUT = 1024 * 1024
MAX_INTERFACES = 128
MAX_ROUTES = 512
MAX_RULES = 256
_network_lock = Lock()
_last_network_sample: tuple[float, dict[str, dict[str, int]]] | None = None


class DnsTestRequest(BaseModel):
    hostname: str = Field(default="example.com", min_length=1, max_length=253)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        candidate = value.strip().rstrip(".")
        try:
            ascii_name = candidate.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("Invalid DNS name") from exc
        labels = ascii_name.split(".")
        if (
            not ascii_name
            or len(ascii_name) > 253
            or any(not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels)
        ):
            raise ValueError("Invalid DNS name")
        try:
            ipaddress.ip_address(ascii_name)
        except ValueError:
            return ascii_name
        raise ValueError("Enter a DNS name, not an IP address")


class ConnectivityTestRequest(BaseModel):
    kind: Literal["ping", "trace", "tcp"]
    target: str = Field(min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        candidate = value.strip().rstrip(".")
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
        try:
            ascii_name = candidate.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("Invalid connectivity target") from exc
        if len(ascii_name) > 253 or any(
            not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in ascii_name.split(".")
        ):
            raise ValueError("Invalid connectivity target")
        return ascii_name

    @field_validator("port")
    @classmethod
    def port_is_optional_only_for_non_tcp(cls, value: int | None) -> int | None:
        return value


def test_connectivity(kind: str, target: str, port: int | None = None) -> dict[str, Any]:
    started = time.monotonic()
    if kind == "tcp":
        if port is None:
            raise ValueError("TCP test requires a port")
        try:
            with socket.create_connection((target, port), timeout=5):
                success, output = True, f"TCP {target}:{port} accepted the connection"
        except OSError as exc:
            success, output = False, f"TCP connection failed: {type(exc).__name__}"
    else:
        if kind == "ping":
            tool = shutil.which("ping")
            arguments = ["-c", "3", "-W", "2", target]
        else:
            tool = shutil.which("tracepath") or shutil.which("traceroute")
            arguments = ["-n", "-m", "20", target] if tool and Path(tool).name == "traceroute" else ["-n", "-m", "20", target]
        if not tool:
            return {"kind": kind, "target": target, "port": port, "success": False, "duration_ms": 0, "output": f"{kind} tool is unavailable"}
        result = _run_command([tool, *arguments], timeout=15)
        success = result.returncode == 0
        output = (result.stdout or result.stderr or "")[:64 * 1024]
    return {
        "kind": kind,
        "target": target,
        "port": port,
        "success": success,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "output": output,
    }


def _read_text(path: str | Path, *, limit: int = 256 * 1024) -> str:
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _run_command(command: list[str], *, timeout: float = 4.0) -> subprocess.CompletedProcess[str]:
    try:
        # Commands and every argument are selected server-side.
        return subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("network_diagnostic_command_failed tool=%s error=%s", Path(command[0]).name, type(exc).__name__)
        return subprocess.CompletedProcess(command, 1, "", type(exc).__name__)


def _ip_json(arguments: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    tool = shutil.which("ip")
    if not tool:
        return [], "iproute2 is unavailable"
    result = _run_command([tool, "-j", *arguments])
    if result.returncode or len(result.stdout) > MAX_COMMAND_OUTPUT:
        return [], "Could not read kernel network state"
    try:
        payload = json.loads(result.stdout or "[]")
    except (TypeError, ValueError):
        return [], "The iproute2 response was invalid"
    if not isinstance(payload, list):
        return [], "The iproute2 response was invalid"
    return [item for item in payload if isinstance(item, dict)], None


def parse_proc_net_dev(content: str) -> dict[str, dict[str, int]]:
    interfaces: dict[str, dict[str, int]] = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        raw_name, raw_values = line.split(":", 1)
        name = raw_name.strip()
        values = raw_values.split()
        if not INTERFACE_RE.fullmatch(name) or len(values) < 16:
            continue
        try:
            counters = [max(0, int(value)) for value in values[:16]]
        except ValueError:
            continue
        interfaces[name] = {
            "rx_bytes": counters[0],
            "rx_packets": counters[1],
            "rx_errors": counters[2],
            "rx_dropped": counters[3],
            "tx_bytes": counters[8],
            "tx_packets": counters[9],
            "tx_errors": counters[10],
            "tx_dropped": counters[11],
        }
        if len(interfaces) >= MAX_INTERFACES:
            break
    return interfaces


def _sysfs_text(interface: str, field: str) -> str:
    if not INTERFACE_RE.fullmatch(interface) or not re.fullmatch(r"[a-z_]+", field):
        return ""
    return _read_text(Path("/sys/class/net") / interface / field, limit=256).strip()


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 0 < parsed <= 10_000_000 else None


def _interface_addresses() -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    payload, warning = _ip_json(["address", "show"])
    result: dict[str, list[dict[str, Any]]] = {}
    for link in payload[:MAX_INTERFACES]:
        name = str(link.get("ifname", ""))
        if not INTERFACE_RE.fullmatch(name):
            continue
        addresses = []
        for address in link.get("addr_info", []) if isinstance(link.get("addr_info"), list) else []:
            if not isinstance(address, dict):
                continue
            family = str(address.get("family", ""))
            local = str(address.get("local", ""))
            if family not in {"inet", "inet6"}:
                continue
            try:
                ipaddress.ip_address(local.split("%", 1)[0])
                prefixlen = int(address.get("prefixlen", 0))
            except (TypeError, ValueError):
                continue
            addresses.append({
                "family": "ipv4" if family == "inet" else "ipv6",
                "address": local,
                "prefix_length": max(0, min(32 if family == "inet" else 128, prefixlen)),
                "scope": str(address.get("scope", ""))[:32],
            })
        result[name] = addresses[:64]
    return result, warning


def network_overview(*, now: float | None = None) -> dict[str, Any]:
    global _last_network_sample
    monotonic = time.monotonic() if now is None else now
    counters = parse_proc_net_dev(_read_text("/proc/net/dev"))
    addresses, warning = _interface_addresses()
    with _network_lock:
        previous = _last_network_sample
        elapsed = monotonic - previous[0] if previous else 0.0
        _last_network_sample = (monotonic, counters)

    interfaces = []
    for name, values in counters.items():
        old = previous[1].get(name) if previous else None
        rx_rate = round((values["rx_bytes"] - old["rx_bytes"]) / elapsed, 1) if old and elapsed > 0 and values["rx_bytes"] >= old["rx_bytes"] else None
        tx_rate = round((values["tx_bytes"] - old["tx_bytes"]) / elapsed, 1) if old and elapsed > 0 and values["tx_bytes"] >= old["tx_bytes"] else None
        state = _sysfs_text(name, "operstate")
        speed = _positive_int(_sysfs_text(name, "speed"))
        mtu = _positive_int(_sysfs_text(name, "mtu"))
        carrier = _sysfs_text(name, "carrier")
        duplex = _sysfs_text(name, "duplex").lower()
        mac = _sysfs_text(name, "address").lower()
        interfaces.append({
            "name": name,
            "state": state if state in {"up", "down", "dormant", "lowerlayerdown", "unknown"} else "unknown",
            "carrier": carrier == "1" if carrier in {"0", "1"} else None,
            "speed_mbps": speed,
            "duplex": duplex if duplex in {"full", "half"} else None,
            "mtu": mtu,
            "mac_address": mac if re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac) else None,
            "addresses": addresses.get(name, []),
            "rx_bytes_per_sec": rx_rate,
            "tx_bytes_per_sec": tx_rate,
            **values,
            "system": name == "lo",
        })
    return {
        "timestamp": time.time(),
        "sample_interval_seconds": round(elapsed, 3) if elapsed > 0 else None,
        "interfaces": sorted(interfaces, key=lambda item: (item["system"], item["name"])),
        "warnings": [warning] if warning else [],
    }


def parse_resolv_conf(content: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"nameservers": [], "search": [], "options": []}
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        key, *values = line.split()
        if key == "nameserver" and values:
            result["nameservers"].append(values[0][:128])
        elif key in {"search", "domain"}:
            result["search"].extend(value[:253] for value in values)
        elif key == "options":
            result["options"].extend(value[:128] for value in values)
    for key in result:
        result[key] = list(dict.fromkeys(result[key]))[:32]
    return result


def parse_resolvectl_map(content: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        global_match = re.fullmatch(r"Global:\s*(.*)", line)
        link_match = re.fullmatch(r"Link\s+\d+\s+\(([^)]+)\):\s*(.*)", line)
        if global_match:
            current = "global"
            values = global_match.group(1).split()
        elif link_match and INTERFACE_RE.fullmatch(link_match.group(1)):
            current = link_match.group(1)
            values = link_match.group(2).split()
        elif current and raw_line[:1].isspace():
            values = line.split()
        else:
            current = ""
            continue
        result.setdefault(current, []).extend(value[:253] for value in values if value != "n/a")
    return {key: list(dict.fromkeys(values))[:32] for key, values in result.items()}


def _resolvectl_state() -> tuple[dict[str, Any], list[str]]:
    tool = shutil.which("resolvectl")
    if not tool:
        return {"available": False, "global_servers": [], "links": []}, []
    dns_result = _run_command([tool, "--no-pager", "dns"])
    domain_result = _run_command([tool, "--no-pager", "domain"])
    if dns_result.returncode:
        return {"available": False, "global_servers": [], "links": []}, ["systemd-resolved is unavailable"]
    dns_map = parse_resolvectl_map(dns_result.stdout)
    domain_map = parse_resolvectl_map(domain_result.stdout) if domain_result.returncode == 0 else {}
    names = sorted((set(dns_map) | set(domain_map)) - {"global"})
    links = [{"interface": name, "servers": dns_map.get(name, []), "domains": domain_map.get(name, [])} for name in names]
    return {"available": True, "global_servers": dns_map.get("global", []), "global_domains": domain_map.get("global", []), "links": links}, []


def dns_configuration() -> dict[str, Any]:
    resolv_path = Path("/etc/resolv.conf")
    content = _read_text(resolv_path)
    resolv = parse_resolv_conf(content)
    try:
        symlink_target = os.readlink(resolv_path) if resolv_path.is_symlink() else None
    except OSError:
        symlink_target = None
    resolved, warnings = _resolvectl_state()
    target = symlink_target or ""
    mode = "stub" if "stub-resolv.conf" in target else "uplink" if target.endswith("/run/systemd/resolve/resolv.conf") else "static"
    return {
        "resolv_conf": {
            "path": str(resolv_path),
            "symlink_target": symlink_target,
            "mode": mode,
            **resolv,
        },
        "systemd_resolved": resolved,
        "warnings": warnings,
    }


def _configured_dns_servers(configuration: dict[str, Any]) -> list[str]:
    candidates = list(configuration["resolv_conf"]["nameservers"])
    resolved = configuration.get("systemd_resolved", {})
    candidates.extend(resolved.get("global_servers", []))
    for link in resolved.get("links", []):
        candidates.extend(link.get("servers", []))
    valid = []
    for candidate in candidates:
        try:
            _dns_endpoint(str(candidate))
        except ValueError:
            continue
        valid.append(str(candidate))
    return list(dict.fromkeys(valid))[:8]


def _dns_endpoint(value: str) -> tuple[str, int, int]:
    candidate = value.split("#", 1)[0]
    port = 53
    if candidate.startswith("["):
        match = re.fullmatch(r"\[([^]]+)](?::(\d{1,5}))?", candidate)
        if not match:
            raise ValueError("invalid DNS server")
        candidate = match.group(1)
        port = int(match.group(2) or 53)
    else:
        try:
            ipaddress.ip_address(candidate.split("%", 1)[0])
        except ValueError:
            host, separator, raw_port = candidate.rpartition(":")
            if not separator or not raw_port.isdigit():
                raise ValueError("invalid DNS server")
            ipaddress.ip_address(host)
            candidate, port = host, int(raw_port)
    address = ipaddress.ip_address(candidate.split("%", 1)[0])
    if not 1 <= port <= 65535:
        raise ValueError("invalid DNS port")
    return candidate, port, socket.AF_INET if address.version == 4 else socket.AF_INET6


def _dns_question(hostname: str, query_id: int) -> bytes:
    labels = hostname.encode("ascii").split(b".")
    encoded = b"".join(bytes([len(label)]) + label for label in labels) + b"\x00"
    return struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + encoded + struct.pack("!HH", 1, 1)


def _skip_dns_name(message: bytes, offset: int) -> int:
    steps = 0
    while offset < len(message) and steps < 128:
        length = message[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(message):
                break
            return offset + 2
        if length > 63 or offset + 1 + length > len(message):
            break
        offset += 1 + length
        steps += 1
    raise ValueError("invalid DNS response")


def _parse_dns_response(message: bytes, query_id: int) -> tuple[str, list[str]]:
    if len(message) < 12:
        raise ValueError("short DNS response")
    response_id, flags, questions, answers, _authority, _additional = struct.unpack("!HHHHHH", message[:12])
    if response_id != query_id or not flags & 0x8000:
        raise ValueError("mismatched DNS response")
    rcode_number = flags & 0xF
    rcode = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED"}.get(rcode_number, f"RCODE{rcode_number}")
    offset = 12
    for _ in range(min(questions, 16)):
        offset = _skip_dns_name(message, offset)
        if offset + 4 > len(message):
            raise ValueError("invalid DNS question")
        offset += 4
    addresses: list[str] = []
    for _ in range(min(answers, 128)):
        offset = _skip_dns_name(message, offset)
        if offset + 10 > len(message):
            raise ValueError("invalid DNS answer")
        record_type, record_class, _ttl, length = struct.unpack("!HHIH", message[offset : offset + 10])
        offset += 10
        if offset + length > len(message):
            raise ValueError("invalid DNS record length")
        value = message[offset : offset + length]
        offset += length
        if record_class == 1 and record_type == 1 and length == 4:
            addresses.append(str(ipaddress.ip_address(value)))
        elif record_class == 1 and record_type == 28 and length == 16:
            addresses.append(str(ipaddress.ip_address(value)))
    return rcode, list(dict.fromkeys(addresses))


def _query_dns_server(server: str, hostname: str, *, timeout: float = 1.5) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        host, port, family = _dns_endpoint(server)
        query_id = secrets.randbelow(65536)
        endpoint: tuple[Any, ...]
        if family == socket.AF_INET6:
            address, _, scope = host.partition("%")
            scope_id = socket.if_nametoindex(scope) if scope else 0
            endpoint = (address, port, 0, scope_id)
        else:
            endpoint = (host, port)
        with socket.socket(family, socket.SOCK_DGRAM) as dns_socket:
            dns_socket.settimeout(timeout)
            dns_socket.sendto(_dns_question(hostname, query_id), endpoint)
            response, _peer = dns_socket.recvfrom(4096)
        rcode, addresses = _parse_dns_response(response, query_id)
        return {"server": server, "success": rcode == "NOERROR", "rcode": rcode, "addresses": addresses, "latency_ms": round((time.perf_counter() - started) * 1000, 2), "error": None}
    except socket.timeout:
        error = "timeout"
    except (OSError, ValueError, struct.error):
        error = "unavailable"
    return {"server": server, "success": False, "rcode": None, "addresses": [], "latency_ms": None, "error": error}


def test_dns_resolution(hostname: str) -> dict[str, Any]:
    configuration = dns_configuration()
    servers = _configured_dns_servers(configuration)
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(servers)))) as executor:
        results = list(executor.map(lambda server: _query_dns_server(server, hostname), servers)) if servers else []
    addresses = list(dict.fromkeys(address for result in results for address in result["addresses"]))
    return {"hostname": hostname, "success": any(result["success"] for result in results), "addresses": addresses, "servers": results, "tested_at": time.time()}


def _safe_text(value: Any, *, limit: int = 128) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    cleaned = "".join(character for character in str(value) if character.isprintable()).strip()
    return cleaned[:limit] or None


def _safe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 2**32 - 1 else None


def _route_payload(item: dict[str, Any], family: str) -> dict[str, Any]:
    nexthops = []
    raw_nexthops = item.get("nexthops", [])
    for nexthop in raw_nexthops[:32] if isinstance(raw_nexthops, list) else []:
        if isinstance(nexthop, dict):
            nexthops.append({
                "gateway": _safe_text(nexthop.get("gateway")),
                "device": _safe_text(nexthop.get("dev"), limit=32),
                "weight": _safe_int(nexthop.get("weight")),
            })
    destination = _safe_text(item.get("dst")) or "default"
    return {
        "family": family,
        "destination": destination,
        "gateway": _safe_text(item.get("gateway")),
        "device": _safe_text(item.get("dev"), limit=32),
        "preferred_source": _safe_text(item.get("prefsrc")),
        "protocol": _safe_text(item.get("protocol"), limit=32),
        "scope": _safe_text(item.get("scope"), limit=32),
        "type": _safe_text(item.get("type"), limit=32) or "unicast",
        "table": _safe_text(item.get("table"), limit=32) or "main",
        "metric": _safe_int(item.get("metric")),
        "nexthops": nexthops,
    }


def _rule_payload(item: dict[str, Any], family: str) -> dict[str, Any]:
    return {
        "family": family,
        "priority": _safe_int(item.get("priority")),
        "from": _safe_text(item.get("src")) or "all",
        "to": _safe_text(item.get("dst")) or "all",
        "table": _safe_text(item.get("table"), limit=32),
        "fwmark": _safe_text(item.get("fwmark"), limit=32),
        "input_interface": _safe_text(item.get("iif"), limit=32),
        "output_interface": _safe_text(item.get("oif"), limit=32),
        "action": _safe_text(item.get("action"), limit=32) or "lookup",
    }


def routing_snapshot() -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    warnings: list[str] = []
    for option, family in (("-4", "ipv4"), ("-6", "ipv6")):
        route_items, route_warning = _ip_json([option, "route", "show", "table", "all"])
        rule_items, rule_warning = _ip_json([option, "rule", "show"])
        routes.extend(_route_payload(item, family) for item in route_items[:MAX_ROUTES])
        rules.extend(_rule_payload(item, family) for item in rule_items[:MAX_RULES])
        warnings.extend(warning for warning in (route_warning, rule_warning) if warning)
    gateways = [
        {
            "family": route["family"],
            "address": route["gateway"],
            "device": route["device"],
            "metric": route["metric"],
            "table": route["table"],
        }
        for route in routes
        if route["destination"] == "default" and route["gateway"] and route["type"] == "unicast"
    ]
    return {
        "timestamp": time.time(),
        "routes": routes[: MAX_ROUTES * 2],
        "rules": rules[: MAX_RULES * 2],
        "gateways": gateways,
        "warnings": list(dict.fromkeys(warnings)),
        "read_only": True,
    }


@router.get("/overview")
def network_overview_endpoint(user: SessionUser = Depends(require_permission(Permission.SETTINGS_VIEW_SYSTEM))):
    return network_overview()


@router.get("/dns")
def dns_configuration_endpoint(user: SessionUser = Depends(require_permission(Permission.SETTINGS_VIEW_SYSTEM))):
    return dns_configuration()


@router.post("/dns/test")
def dns_test_endpoint(payload: DnsTestRequest, user: SessionUser = Depends(require_permission(Permission.SETTINGS_VIEW_SYSTEM, mutating=False))):
    return test_dns_resolution(payload.hostname)


@router.get("/routing")
def routing_endpoint(user: SessionUser = Depends(require_permission(Permission.SETTINGS_VIEW_SYSTEM))):
    return routing_snapshot()


@router.post("/connectivity/test")
def connectivity_test_endpoint(payload: ConnectivityTestRequest, user: SessionUser = Depends(require_permission(Permission.NETWORK_CONFIG_VIEW, mutating=False))):
    if payload.kind == "tcp" and payload.port is None:
        from fastapi import HTTPException

        raise HTTPException(422, "TCP test requires a port")
    return test_connectivity(payload.kind, payload.target, payload.port)
