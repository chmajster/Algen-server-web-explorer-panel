from __future__ import annotations

import ipaddress
import socket
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from .models import NetworkScanInput


MAX_SCAN_ADDRESSES = 4096


def _network_allowed(network: ipaddress.IPv4Network | ipaddress.IPv6Network, allowed_networks: Iterable[str] = ()) -> bool:
    if network.prefixlen == 0 or network.is_unspecified or network.is_multicast or network.is_loopback:
        return False
    if network.is_private or network.is_link_local:
        return True
    for raw in allowed_networks:
        try:
            configured = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if network.version == configured.version:
            if isinstance(network, ipaddress.IPv4Network) and isinstance(configured, ipaddress.IPv4Network) and network.subnet_of(configured):
                return True
            if isinstance(network, ipaddress.IPv6Network) and isinstance(configured, ipaddress.IPv6Network) and network.subnet_of(configured):
                return True
    return False


def scan_addresses(payload: NetworkScanInput, allowed_networks: Iterable[str] = (), max_addresses: int = MAX_SCAN_ADDRESSES) -> list[str]:
    if payload.cidr:
        try:
            network = ipaddress.ip_network(payload.cidr, strict=False)
        except ValueError as error:
            raise ValueError("invalid CIDR") from error
        if not _network_allowed(network, allowed_networks):
            raise ValueError("scan range is not private, local or explicitly allowed")
        count = max(0, int(network.num_addresses) - (2 if network.version == 4 and network.prefixlen < 31 else 0))
        if count > max_addresses:
            raise ValueError(f"scan range exceeds {max_addresses} addresses")
        return [str(address) for address in network.hosts()]
    try:
        start = ipaddress.ip_address(payload.start_address or "")
        end = ipaddress.ip_address(payload.end_address or "")
    except ValueError as error:
        raise ValueError("invalid address range") from error
    if start.version != end.version or int(start) > int(end):
        raise ValueError("invalid address range order")
    count = int(end) - int(start) + 1
    if count > max_addresses:
        raise ValueError(f"scan range exceeds {max_addresses} addresses")
    networks = list(ipaddress.summarize_address_range(start, end))
    for net in networks:
        if isinstance(net, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            if not _network_allowed(net, allowed_networks):
                raise ValueError("scan range is not private, local or explicitly allowed")
    return [str(ipaddress.ip_address(number)) for number in range(int(start), int(end) + 1)]


def build_nmap_args(payload: NetworkScanInput, addresses: list[str], executable: str = "nmap") -> list[str]:
    if not addresses or len(addresses) > MAX_SCAN_ADDRESSES:
        raise ValueError("invalid nmap target count")
    timeout_ms = max(200, min(15_000, int(payload.timeout_seconds * 1000)))
    return [
        executable,
        "-n",
        "-Pn",
        "-sT",
        "--max-retries",
        "1",
        "--host-timeout",
        f"{timeout_ms}ms",
        "-p",
        str(payload.port),
        "--open",
        "-oX",
        "-",
        "--",
        *addresses,
    ]


def parse_nmap_xml(content: str, port: int, reverse_dns: bool = False) -> list[dict[str, object]]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError("invalid nmap XML") from error
    result: list[dict[str, object]] = []
    for host in root.findall("host"):
        address_node = host.find("address")
        if address_node is None or not address_node.attrib.get("addr"):
            continue
        address = address_node.attrib["addr"]
        port_node = host.find(f"./ports/port[@portid='{port}']")
        state_node = port_node.find("state") if port_node is not None else None
        state = state_node.attrib.get("state") if state_node is not None else "closed"
        hostname = ""
        if reverse_dns:
            try:
                hostname = socket.gethostbyaddr(address)[0][:253]
            except (OSError, UnicodeError):
                hostname = ""
        times = host.find("times")
        latency = float(times.attrib.get("srtt", 0)) / 1000 if times is not None else None
        result.append({"address": address, "hostname": hostname, "port": port, "latency_ms": latency, "ssh_status": "open" if state == "open" else "closed"})
    return result
