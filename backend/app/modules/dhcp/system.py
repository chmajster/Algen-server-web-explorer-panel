from __future__ import annotations

import csv
import io
import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...package_center.executor import redact
from .models import DhcpBackend, DhcpConfiguration, DhcpInterface, DhcpLease


@dataclass(frozen=True, slots=True)
class BackendDefinition:
    backend: DhcpBackend
    executable: str
    services: tuple[str, ...]
    config_path: Path
    leases_path: Path
    interface_config_path: Path | None = None


BACKENDS: dict[DhcpBackend, BackendDefinition] = {
    DhcpBackend.kea: BackendDefinition(
        backend=DhcpBackend.kea,
        executable="kea-dhcp4",
        services=("kea-dhcp4-server", "kea-dhcp4"),
        config_path=Path("/etc/kea/kea-dhcp4.conf"),
        leases_path=Path("/var/lib/kea/kea-leases4.csv"),
    ),
    DhcpBackend.isc: BackendDefinition(
        backend=DhcpBackend.isc,
        executable="dhcpd",
        services=("isc-dhcp-server", "dhcpd"),
        config_path=Path("/etc/dhcp/dhcpd.conf"),
        leases_path=Path("/var/lib/dhcp/dhcpd.leases"),
        interface_config_path=Path("/etc/default/isc-dhcp-server"),
    ),
}


class DhcpSystem:
    """Closed host adapter for Kea DHCPv4 and ISC dhcpd."""

    def __init__(self, *, definitions: dict[DhcpBackend, BackendDefinition] | None = None) -> None:
        self.definitions = definitions or BACKENDS

    @staticmethod
    def _run(args: list[str], *, timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, shell=False, input=input_text)

    @staticmethod
    def _which(name: str) -> str | None:
        return shutil.which(name)

    def _unit_exists(self, service: str) -> bool:
        executable = self._which("systemctl")
        if not executable:
            return False
        result = self._run([executable, "show", service, "--property=LoadState", "--value"], timeout=8)
        return result.returncode == 0 and result.stdout.strip() not in {"", "not-found"}

    def service_state(self, service: str) -> tuple[str, bool]:
        executable = self._which("systemctl")
        if not executable or not service:
            return "unknown", False
        active = self._run([executable, "is-active", service], timeout=8)
        enabled = self._run([executable, "is-enabled", service], timeout=8)
        return (active.stdout.strip() or "unknown"), enabled.returncode == 0

    def selected_service(self, backend: DhcpBackend) -> str:
        definition = self.definitions.get(backend)
        if not definition:
            return ""
        for service in definition.services:
            if self._unit_exists(service):
                return service
        return definition.services[0] if self._which(definition.executable) else ""

    def detect_backend(self) -> DhcpBackend:
        available: list[DhcpBackend] = []
        for backend in (DhcpBackend.kea, DhcpBackend.isc):
            definition = self.definitions[backend]
            if self._which(definition.executable):
                available.append(backend)
                service = self.selected_service(backend)
                if service and self.service_state(service)[0] == "active":
                    return backend
        if DhcpBackend.kea in available:
            return DhcpBackend.kea
        if DhcpBackend.isc in available:
            return DhcpBackend.isc
        return DhcpBackend.none

    def version(self, backend: DhcpBackend) -> str:
        definition = self.definitions.get(backend)
        if not definition:
            return ""
        executable = self._which(definition.executable)
        if not executable:
            return ""
        args = [executable, "-V"] if backend == DhcpBackend.kea else [executable, "--version"]
        result = self._run(args, timeout=8)
        text = (result.stdout or result.stderr).strip().splitlines()
        return redact(text[0])[:256] if text else ""

    def service_action(self, backend: DhcpBackend, action: str) -> subprocess.CompletedProcess[str]:
        if action not in {"start", "stop", "restart", "reload", "enable", "disable"}:
            raise ValueError("unsupported DHCP service action")
        service = self.selected_service(backend)
        if not service:
            raise RuntimeError("DHCP systemd service is unavailable")
        executable = self._which("systemctl")
        if not executable:
            raise RuntimeError("systemctl is unavailable")
        return self._run([executable, action, service], timeout=60)

    def service_uptime(self, backend: DhcpBackend) -> int | None:
        service = self.selected_service(backend)
        executable = self._which("systemctl")
        if not service or not executable:
            return None
        result = self._run([executable, "show", service, "--property=ActiveEnterTimestampMonotonic", "--value"], timeout=8)
        raw = result.stdout.strip()
        if result.returncode != 0 or not raw.isdigit() or int(raw) <= 0:
            return None
        return max(0, int(time.monotonic() - int(raw) / 1_000_000))

    def interfaces(self, enabled: set[str] | None = None) -> list[DhcpInterface]:
        enabled = enabled or set()
        executable = self._which("ip")
        if not executable:
            return []
        result = self._run([executable, "-j", "address", "show"], timeout=10)
        if result.returncode != 0:
            return []
        try:
            rows = json.loads(result.stdout)
        except (ValueError, TypeError):
            return []
        values: list[DhcpInterface] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("ifname") or "")
            if not name or name == "lo":
                continue
            ipv4_addresses: list[str] = []
            subnets: list[str] = []
            for address in row.get("addr_info") or []:
                if not isinstance(address, dict) or address.get("family") != "inet":
                    continue
                local = str(address.get("local") or "")
                prefix = int(address.get("prefixlen") or 32)
                try:
                    ipv4_addresses.append(str(ipaddress.ip_address(local)))
                    subnets.append(str(ipaddress.ip_network(f"{local}/{prefix}", strict=False)))
                except ValueError:
                    continue
            values.append(DhcpInterface(
                name=name,
                state=str(row.get("operstate") or "unknown").lower(),
                mac_address=str(row.get("address") or "").lower(),
                ipv4_addresses=ipv4_addresses,
                subnets=list(dict.fromkeys(subnets)),
                dhcp_enabled=name in enabled,
            ))
        return values

    def validate_candidate(self, backend: DhcpBackend, path: Path) -> tuple[bool, str]:
        definition = self.definitions.get(backend)
        if not definition:
            return False, "No supported DHCP backend is installed"
        executable = self._which(definition.executable)
        if not executable:
            return False, f"{definition.executable} is unavailable"
        args = [executable, "-t", str(path)] if backend == DhcpBackend.kea else [executable, "-t", "-cf", str(path)]
        result = self._run(args, timeout=30)
        output = redact((result.stdout + "\n" + result.stderr).strip())[:32_768]
        return result.returncode == 0, output

    @staticmethod
    def render_kea(config: DhcpConfiguration) -> str:
        reservations_by_subnet: dict[str, list[dict[str, Any]]] = {}
        for item in config.reservations:
            if not item.enabled:
                continue
            payload: dict[str, Any] = {
                "hostname": item.hostname,
                "hw-address": item.mac_address,
                "ip-address": item.ipv4_address,
            }
            if item.client_identifier:
                payload["client-id"] = item.client_identifier
            reservations_by_subnet.setdefault(item.subnet_id, []).append(payload)
        subnet4: list[dict[str, Any]] = []
        for index, subnet in enumerate((value for value in config.subnets if value.enabled), start=1):
            options: list[dict[str, Any]] = []
            if subnet.gateway:
                options.append({"name": "routers", "data": subnet.gateway})
            if subnet.dns_servers:
                options.append({"name": "domain-name-servers", "data": ", ".join(subnet.dns_servers)})
            if subnet.domain_name:
                options.append({"name": "domain-name", "data": subnet.domain_name})
            if subnet.search_domain:
                options.append({"name": "domain-search", "data": subnet.search_domain})
            if subnet.ntp_servers:
                options.append({"name": "ntp-servers", "data": ", ".join(subnet.ntp_servers)})
            options.append({"name": "broadcast-address", "data": subnet.broadcast_address})
            if subnet.tftp_server:
                options.append({"name": "tftp-server-name", "data": subnet.tftp_server})
            if subnet.boot_filename:
                options.append({"name": "boot-file-name", "data": subnet.boot_filename})
            subnet4.append({
                "id": index,
                "subnet": subnet.cidr,
                "pools": [{"pool": f"{subnet.pool_start} - {subnet.pool_end}"}],
                "valid-lifetime": subnet.lease_time,
                "max-valid-lifetime": subnet.max_lease_time,
                "option-data": options,
                "reservations": reservations_by_subnet.get(subnet.id, []),
                "user-context": {"webnas-id": subnet.id, "name": subnet.name, "description": subnet.description},
            })
        payload = {
            "Dhcp4": {
                "interfaces-config": {"interfaces": config.interfaces},
                "lease-database": {"type": "memfile", "persist": True, "name": "/var/lib/kea/kea-leases4.csv"},
                "authoritative": config.authoritative,
                "valid-lifetime": config.default_lease_time,
                "max-valid-lifetime": config.max_lease_time,
                "subnet4": subnet4,
            }
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def render_isc(config: DhcpConfiguration) -> str:
        lines = ["# Managed by WebNAS DHCP Manager. Manual edits may be replaced."]
        if config.authoritative:
            lines.append("authoritative;")
        lines.extend([f"default-lease-time {config.default_lease_time};", f"max-lease-time {config.max_lease_time};", ""])
        reservations_by_subnet: dict[str, list[Any]] = {}
        for reservation in config.reservations:
            if reservation.enabled:
                reservations_by_subnet.setdefault(reservation.subnet_id, []).append(reservation)
        for subnet in (item for item in config.subnets if item.enabled):
            network = ipaddress.ip_network(subnet.cidr)
            lines.append(f"subnet {network.network_address} netmask {network.netmask} {{")
            if subnet.gateway:
                lines.append(f"  option routers {subnet.gateway};")
            lines.append(f"  option subnet-mask {network.netmask};")
            lines.append(f"  option broadcast-address {network.broadcast_address};")
            if subnet.dns_servers:
                lines.append(f"  option domain-name-servers {', '.join(subnet.dns_servers)};")
            if subnet.domain_name:
                lines.append(f'  option domain-name "{subnet.domain_name}";')
            if subnet.ntp_servers:
                lines.append(f"  option ntp-servers {', '.join(subnet.ntp_servers)};")
            if subnet.tftp_server:
                lines.append(f'  next-server {subnet.tftp_server};' if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", subnet.tftp_server) else f'  option tftp-server-name "{subnet.tftp_server}";')
            if subnet.boot_filename:
                lines.append(f'  filename "{subnet.boot_filename}";')
            lines.append(f"  default-lease-time {subnet.lease_time};")
            lines.append(f"  max-lease-time {subnet.max_lease_time};")
            lines.append(f"  range {subnet.pool_start} {subnet.pool_end};")
            for reservation in reservations_by_subnet.get(subnet.id, []):
                safe_name = re.sub(r"[^A-Za-z0-9_-]", "-", reservation.hostname)[:48]
                lines.append(f"  host webnas-{safe_name}-{reservation.id[:8]} {{")
                lines.append(f"    hardware ethernet {reservation.mac_address};")
                lines.append(f"    fixed-address {reservation.ipv4_address};")
                lines.append(f'    option host-name "{reservation.hostname}";')
                if reservation.client_identifier:
                    escaped = reservation.client_identifier.replace('"', "")
                    lines.append(f'    option dhcp-client-identifier "{escaped}";')
                lines.append("  }")
            lines.append("}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def render(self, backend: DhcpBackend, config: DhcpConfiguration) -> str:
        if backend == DhcpBackend.kea:
            return self.render_kea(config)
        if backend == DhcpBackend.isc:
            return self.render_isc(config)
        raise RuntimeError("No supported DHCP backend is installed")

    @staticmethod
    def render_isc_interfaces(config: DhcpConfiguration) -> str:
        interfaces = " ".join(config.interfaces)
        return f'# Managed by WebNAS DHCP Manager\nINTERFACESv4="{interfaces}"\nINTERFACESv6=""\n'

    @staticmethod
    def parse_kea(text: str) -> DhcpConfiguration:
        payload = json.loads(text)
        root = payload.get("Dhcp4", {}) if isinstance(payload, dict) else {}
        from .models import DhcpReservation, DhcpSubnet
        subnets = []
        reservations = []
        for index, row in enumerate(root.get("subnet4") or [], start=1):
            if not isinstance(row, dict):
                continue
            context = row.get("user-context") if isinstance(row.get("user-context"), dict) else {}
            subnet_id = str(context.get("webnas-id") or f"imported-{index}")
            pools = row.get("pools") or []
            pool = str(pools[0].get("pool") or "") if pools and isinstance(pools[0], dict) else ""
            match = re.match(r"^\s*([^\s]+)\s*-\s*([^\s]+)\s*$", pool)
            if not match:
                continue
            options = {str(item.get("name")): str(item.get("data") or "") for item in row.get("option-data") or [] if isinstance(item, dict)}
            subnet = DhcpSubnet(
                id=subnet_id,
                name=str(context.get("name") or row.get("subnet") or subnet_id),
                cidr=str(row.get("subnet") or ""),
                gateway=options.get("routers", "").split(",")[0].strip(),
                pool_start=match.group(1), pool_end=match.group(2),
                dns_servers=[item.strip() for item in options.get("domain-name-servers", "").split(",") if item.strip()],
                domain_name=options.get("domain-name", ""), search_domain=options.get("domain-search", ""),
                lease_time=int(row.get("valid-lifetime") or root.get("valid-lifetime") or 3600),
                max_lease_time=int(row.get("max-valid-lifetime") or root.get("max-valid-lifetime") or 7200),
                ntp_servers=[item.strip() for item in options.get("ntp-servers", "").split(",") if item.strip()],
                broadcast_address=options.get("broadcast-address", ""),
                tftp_server=options.get("tftp-server-name", ""), boot_filename=options.get("boot-file-name", ""),
                pxe_enabled=bool(options.get("tftp-server-name") or options.get("boot-file-name")),
                description=str(context.get("description") or ""),
            )
            subnets.append(subnet)
            for reservation_index, item in enumerate(row.get("reservations") or [], start=1):
                if not isinstance(item, dict) or not item.get("hw-address") or not item.get("ip-address"):
                    continue
                reservations.append(DhcpReservation(
                    id=f"imported-{index}-{reservation_index}", hostname=str(item.get("hostname") or f"host-{reservation_index}"),
                    mac_address=str(item["hw-address"]), ipv4_address=str(item["ip-address"]), subnet_id=subnet_id,
                    client_identifier=str(item.get("client-id") or ""),
                ))
        interfaces = root.get("interfaces-config", {}).get("interfaces", []) if isinstance(root.get("interfaces-config"), dict) else []
        return DhcpConfiguration(
            interfaces=[str(item) for item in interfaces], authoritative=bool(root.get("authoritative", True)),
            default_lease_time=int(root.get("valid-lifetime") or 3600), max_lease_time=int(root.get("max-valid-lifetime") or 7200),
            subnets=subnets, reservations=reservations,
        )

    @staticmethod
    def parse_isc(text: str) -> DhcpConfiguration:
        from .models import DhcpReservation, DhcpSubnet
        clean = re.sub(r"#.*", "", text)
        subnets: list[DhcpSubnet] = []
        reservations: list[DhcpReservation] = []
        cursor = 0
        index = 0
        header = re.compile(r"subnet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(\d+\.\d+\.\d+\.\d+)\s*\{", re.I)
        while True:
            match = header.search(clean, cursor)
            if not match:
                break
            depth, end = 1, match.end()
            while end < len(clean) and depth:
                if clean[end] == "{": depth += 1
                elif clean[end] == "}": depth -= 1
                end += 1
            body = clean[match.end():end - 1]
            index += 1
            network = ipaddress.ip_network(f"{match.group(1)}/{match.group(2)}", strict=False)
            range_match = re.search(r"\brange\s+(\S+)\s+(\S+)\s*;", body)
            if not range_match:
                cursor = end
                continue
            router = re.search(r"option\s+routers\s+([^;]+);", body)
            dns = re.search(r"option\s+domain-name-servers\s+([^;]+);", body)
            domain = re.search(r'option\s+domain-name\s+"([^"]+)"\s*;', body)
            default_lease = re.search(r"default-lease-time\s+(\d+)\s*;", body)
            max_lease = re.search(r"max-lease-time\s+(\d+)\s*;", body)
            subnet_id = f"imported-{index}"
            subnets.append(DhcpSubnet(
                id=subnet_id, name=str(network), cidr=str(network), gateway=router.group(1).split(",")[0].strip() if router else "",
                pool_start=range_match.group(1), pool_end=range_match.group(2),
                dns_servers=[item.strip() for item in dns.group(1).split(",")] if dns else [], domain_name=domain.group(1) if domain else "",
                lease_time=int(default_lease.group(1)) if default_lease else 3600,
                max_lease_time=int(max_lease.group(1)) if max_lease else 7200,
            ))
            host_pattern = re.compile(r"host\s+([A-Za-z0-9_.-]+)\s*\{(.*?)\}", re.S | re.I)
            for reservation_index, host in enumerate(host_pattern.finditer(body), start=1):
                mac = re.search(r"hardware\s+ethernet\s+([0-9A-Fa-f:.-]+)\s*;", host.group(2))
                fixed = re.search(r"fixed-address\s+([^;]+);", host.group(2))
                hostname = re.search(r'option\s+host-name\s+"([^"]+)"\s*;', host.group(2))
                if mac and fixed:
                    reservations.append(DhcpReservation(
                        id=f"imported-{index}-{reservation_index}", hostname=hostname.group(1) if hostname else host.group(1),
                        mac_address=mac.group(1), ipv4_address=fixed.group(1).strip(), subnet_id=subnet_id,
                    ))
            cursor = end
        default = re.search(r"default-lease-time\s+(\d+)\s*;", clean)
        maximum = re.search(r"max-lease-time\s+(\d+)\s*;", clean)
        return DhcpConfiguration(
            authoritative=bool(re.search(r"\bauthoritative\s*;", clean)),
            default_lease_time=int(default.group(1)) if default else 3600,
            max_lease_time=int(maximum.group(1)) if maximum else 7200,
            subnets=subnets, reservations=reservations,
        )

    def parse_config(self, backend: DhcpBackend, text: str) -> DhcpConfiguration:
        if backend == DhcpBackend.kea:
            return self.parse_kea(text)
        if backend == DhcpBackend.isc:
            return self.parse_isc(text)
        return DhcpConfiguration()

    def leases(self, backend: DhcpBackend) -> list[DhcpLease]:
        definition = self.definitions.get(backend)
        if not definition or not definition.leases_path.is_file():
            return []
        try:
            text = definition.leases_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.parse_kea_leases(text) if backend == DhcpBackend.kea else self.parse_isc_leases(text)

    @staticmethod
    def parse_kea_leases(text: str) -> list[DhcpLease]:
        now = time.time()
        leases: list[DhcpLease] = []
        reader = csv.DictReader(io.StringIO(text))
        for index, row in enumerate(reader):
            address = str(row.get("address") or "")
            if not address:
                continue
            try:
                expire = float(row.get("expire") or 0)
                valid = int(row.get("valid_lifetime") or 0)
            except ValueError:
                expire, valid = 0, 0
            start = expire - valid if expire and valid else None
            state_raw = str(row.get("state") or "0")
            state = "active" if expire > now and state_raw in {"0", "default", "active"} else "declined" if state_raw in {"1", "declined"} else "expired"
            leases.append(DhcpLease(
                id=f"kea:{address}:{row.get('hwaddr') or index}", hostname=str(row.get("hostname") or ""), ipv4_address=address,
                mac_address=str(row.get("hwaddr") or "").lower(), client_identifier=str(row.get("client_id") or ""),
                subnet_id=str(row.get("subnet_id") or ""), lease_start=start, lease_end=expire or None,
                remaining_seconds=max(0, int(expire - now)) if expire else 0, state=state,
            ))
        return leases

    @staticmethod
    def parse_isc_leases(text: str) -> list[DhcpLease]:
        now = time.time()
        by_address: dict[str, DhcpLease] = {}
        pattern = re.compile(r"lease\s+(\d+\.\d+\.\d+\.\d+)\s*\{(.*?)\}", re.S | re.I)
        for index, match in enumerate(pattern.finditer(text)):
            address, body = match.group(1), match.group(2)
            mac = re.search(r"hardware\s+ethernet\s+([0-9A-Fa-f:.-]+)\s*;", body)
            hostname = re.search(r'client-hostname\s+"([^"]*)"\s*;', body)
            binding = re.search(r"binding\s+state\s+(\w+)\s*;", body)
            ends = re.search(r"ends\s+\d+\s+(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s*;", body)
            end_ts = None
            if ends:
                try:
                    end_ts = time.mktime(time.strptime(ends.group(1), "%Y/%m/%d %H:%M:%S"))
                except ValueError:
                    pass
            raw_state = binding.group(1).lower() if binding else "unknown"
            state = "active" if raw_state == "active" and (end_ts is None or end_ts > now) else "expired" if raw_state in {"free", "expired", "backup"} or (end_ts and end_ts <= now) else "released" if raw_state == "released" else "unknown"
            by_address[address] = DhcpLease(
                id=f"isc:{address}:{index}", hostname=hostname.group(1) if hostname else "", ipv4_address=address,
                mac_address=mac.group(1).replace("-", ":").lower() if mac else "", lease_end=end_ts,
                remaining_seconds=max(0, int(end_ts - now)) if end_ts else 0, state=state,
            )
        return list(by_address.values())

    def logs(self, backend: DhcpBackend, *, limit: int = 200, search: str = "", level: str = "", since: str = "") -> dict[str, Any]:
        service = self.selected_service(backend)
        if not service:
            return {"source": "", "sources": [], "lines": [], "truncated": False}
        executable = self._which("journalctl")
        sources = [{"id": f"journal:{service}", "label": service}]
        if not executable:
            return {"source": sources[0]["id"], "sources": sources, "lines": [], "truncated": False}
        args = [executable, "-u", service, "-n", str(min(max(limit, 1), 1000)), "--no-pager"]
        if since in {"1h", "6h", "24h", "7d"}:
            args.extend(["--since", {"1h": "1 hour ago", "6h": "6 hours ago", "24h": "24 hours ago", "7d": "7 days ago"}[since]])
        result = self._run(args, timeout=15)
        values = [redact(line) for line in (result.stdout if result.returncode == 0 else result.stderr).splitlines()]
        needle, severity = search.lower().strip(), level.lower().strip()
        if needle:
            values = [line for line in values if needle in line.lower()]
        if severity:
            values = [line for line in values if severity in line.lower()]
        selected, size = [], 0
        for line in reversed(values):
            encoded = len(line.encode("utf-8", errors="replace")) + 1
            if size + encoded > 512 * 1024:
                break
            selected.append(line)
            size += encoded
        selected.reverse()
        return {"source": sources[0]["id"], "sources": sources, "lines": selected, "truncated": len(selected) < len(values)}

    def udp67_listening(self) -> bool:
        executable = self._which("ss")
        if not executable:
            return False
        result = self._run([executable, "-lun"], timeout=8)
        return result.returncode == 0 and bool(re.search(r"(?:^|\s)(?:0\.0\.0\.0|\*|\[::\]):67(?:\s|$)", result.stdout, re.M))

    def firewall_state(self) -> str:
        if executable := self._which("ufw"):
            result = self._run([executable, "status"], timeout=8)
            return redact(result.stdout.strip())[:2048]
        if executable := self._which("firewall-cmd"):
            result = self._run([executable, "--state"], timeout=8)
            return redact(result.stdout.strip() or result.stderr.strip())[:2048]
        return "unknown"
