from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import sys
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .activity import ActivityCategory, ActivityStatus, record_activity
from .config import get_config
from .identity.permissions import Permission, authorize, require_permission
from .modules.ansible_controller.security import redact
from .network_diagnostics import INTERFACE_RE, _ip_json, _run_command, dns_configuration, network_overview, routing_snapshot
from .security import SessionUser, get_session_user, require_csrf


router = APIRouter(prefix="/api/admin/network", tags=["network-management"])
IFNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,14}$")
DOMAIN_RE = re.compile(r"^(?:~?\.|~?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$")
ROLLBACK_SECONDS = 90
MAX_OBJECTS = 256
_transaction_lock = Lock()


def _acquire_process_lock() -> int:
    path = _state_root() / "operation.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as error:
        os.close(descriptor)
        raise HTTPException(409, "Another network operation is active") from error
    return descriptor


def _release_process_lock(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _state_root() -> Path:
    path = Path(get_config().paths.data_dir) / "network-management"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _validate_ifname(value: str) -> str:
    if not IFNAME_RE.fullmatch(value):
        raise ValueError("Invalid Linux interface name")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddressConfig(StrictModel):
    address: str
    prefix: int = Field(ge=0, le=128)

    @model_validator(mode="after")
    def valid_address(self) -> "AddressConfig":
        address = ipaddress.ip_address(self.address)
        maximum = 32 if address.version == 4 else 128
        if self.prefix > maximum:
            raise ValueError("Prefix does not match address family")
        self.address = str(address)
        return self


class IPConfiguration(StrictModel):
    method: Literal["disabled", "dhcp", "slaac", "dhcpv6", "manual"] = "dhcp"
    addresses: list[AddressConfig] = Field(default_factory=list, max_length=16)
    gateway: str | None = None
    metric: int = Field(default=100, ge=0, le=4_294_967_295)
    default_route: bool = True
    ignore_auto_routes: bool = False
    ignore_auto_dns: bool = False
    dns: list[str] = Field(default_factory=list, max_length=16)
    search_domains: list[str] = Field(default_factory=list, max_length=16)
    privacy_extensions: bool = False

    @model_validator(mode="after")
    def valid_ip(self) -> "IPConfiguration":
        versions = {ipaddress.ip_address(item.address).version for item in self.addresses}
        gateway = ipaddress.ip_address(self.gateway) if self.gateway else None
        if gateway and versions and gateway.version not in versions:
            raise ValueError("Gateway and addresses must use the same family")
        for server in self.dns:
            ipaddress.ip_address(server)
        if any(not DOMAIN_RE.fullmatch(domain) for domain in self.search_domains):
            raise ValueError("Invalid search domain")
        if self.method == "manual" and not self.addresses:
            raise ValueError("Manual configuration requires an address")
        return self


BondMode = Literal["active-backup", "balance-rr", "balance-xor", "broadcast", "802.3ad", "balance-tlb", "balance-alb"]


class InterfaceConfiguration(StrictModel):
    name: str
    kind: Literal["physical", "bond", "vlan", "bridge"] = "physical"
    autostart: bool = True
    mtu: int = Field(default=1500, ge=576, le=9216)
    parent: str | None = None
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    members: list[str] = Field(default_factory=list, max_length=32)
    bond_mode: BondMode = "active-backup"
    primary: str | None = None
    miimon: int = Field(default=100, ge=0, le=10_000)
    updelay: int = Field(default=0, ge=0, le=60_000)
    downdelay: int = Field(default=0, ge=0, le=60_000)
    lacp_rate: Literal["slow", "fast"] = "slow"
    xmit_hash_policy: Literal["layer2", "layer2+3", "layer3+4"] = "layer2"
    stp: bool = True
    forward_delay: int = Field(default=15, ge=0, le=30)
    ipv4: IPConfiguration = Field(default_factory=IPConfiguration)
    ipv6: IPConfiguration = Field(default_factory=lambda: IPConfiguration(method="slaac"))

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _validate_ifname(value)

    @field_validator("parent", "primary")
    @classmethod
    def optional_name_valid(cls, value: str | None) -> str | None:
        return _validate_ifname(value) if value else None

    @field_validator("members")
    @classmethod
    def members_valid(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Duplicate interface member")
        return [_validate_ifname(value) for value in values]

    @model_validator(mode="after")
    def kind_valid(self) -> "InterfaceConfiguration":
        if any(ipaddress.ip_address(item.address).version != 4 for item in self.ipv4.addresses):
            raise ValueError("IPv4 configuration contains a non-IPv4 address")
        if any(ipaddress.ip_address(item.address).version != 6 for item in self.ipv6.addresses):
            raise ValueError("IPv6 configuration contains a non-IPv6 address")
        if self.ipv4.method not in {"disabled", "dhcp", "manual"}:
            raise ValueError("Invalid IPv4 method")
        if self.ipv6.method not in {"disabled", "slaac", "dhcpv6", "manual"}:
            raise ValueError("Invalid IPv6 method")
        if self.kind == "vlan" and (not self.parent or self.vlan_id is None):
            raise ValueError("VLAN requires parent and VLAN ID")
        if self.kind in {"bond", "bridge"} and not self.members:
            raise ValueError(f"{self.kind} requires members")
        if self.primary and (self.bond_mode != "active-backup" or self.primary not in self.members):
            raise ValueError("Primary must be an active-backup member")
        if self.name in self.members or "lo" in self.members:
            raise ValueError("Invalid member interface")
        return self


class DnsSettings(StrictModel):
    automatic: bool = True
    servers: list[str] = Field(default_factory=list, max_length=16)
    search_domains: list[str] = Field(default_factory=list, max_length=16)
    routing_domains: list[str] = Field(default_factory=list, max_length=16)
    per_interface: dict[str, list[str]] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=-2_147_483_648, le=2_147_483_647)
    ignore_dhcp: bool = False

    @model_validator(mode="after")
    def valid_dns(self) -> "DnsSettings":
        for server in self.servers:
            ipaddress.ip_address(server)
        for interface, servers in self.per_interface.items():
            _validate_ifname(interface)
            if len(servers) > 16:
                raise ValueError("Too many per-interface DNS servers")
            for server in servers:
                ipaddress.ip_address(server)
        if any(not DOMAIN_RE.fullmatch(item) for item in self.search_domains + self.routing_domains):
            raise ValueError("Invalid DNS domain")
        return self


class ManagedRoute(StrictModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=80)
    family: Literal["ipv4", "ipv6"]
    destination: str
    route_type: Literal["unicast", "blackhole", "unreachable", "prohibit"] = "unicast"
    gateway: str | None = None
    interface: str | None = None
    metric: int = Field(default=100, ge=0, le=4_294_967_295)
    table: int = Field(default=254, ge=1, le=4_294_967_295)
    source: str | None = None
    autostart: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def valid_route(self) -> "ManagedRoute":
        network = ipaddress.ip_network(self.destination, strict=False)
        expected = 4 if self.family == "ipv4" else 6
        if network.version != expected:
            raise ValueError("Route family mismatch")
        self.destination = str(network)
        if self.gateway and ipaddress.ip_address(self.gateway).version != expected:
            raise ValueError("Gateway family mismatch")
        if self.source and ipaddress.ip_address(self.source).version != expected:
            raise ValueError("Source family mismatch")
        if self.interface:
            _validate_ifname(self.interface)
        if self.route_type == "unicast" and not (self.gateway or self.interface):
            raise ValueError("Unicast route requires gateway or interface")
        return self


class TrafficRule(StrictModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=80)
    interface: str
    direction: Literal["egress", "ingress"] = "egress"
    guaranteed_kbit: int = Field(default=0, ge=0, le=100_000_000)
    maximum_kbit: int = Field(ge=1, le=100_000_000)
    priority: int = Field(default=5, ge=1, le=100)
    protocol: Literal["any", "tcp", "udp"] = "any"
    source_cidr: str | None = None
    destination_cidr: str | None = None
    source_port: int | None = Field(default=None, ge=1, le=65535)
    destination_port: int | None = Field(default=None, ge=1, le=65535)
    enabled: bool = True

    @model_validator(mode="after")
    def valid_rule(self) -> "TrafficRule":
        _validate_ifname(self.interface)
        families: set[int] = set()
        for value in (self.source_cidr, self.destination_cidr):
            if value:
                families.add(ipaddress.ip_network(value, strict=False).version)
        if len(families) > 1:
            raise ValueError("Traffic filter CIDRs must use the same address family")
        if self.protocol == "any" and (self.source_port or self.destination_port):
            raise ValueError("Ports require TCP or UDP")
        if self.guaranteed_kbit > self.maximum_kbit:
            raise ValueError("Guaranteed bandwidth exceeds maximum")
        return self


class NetworkChange(StrictModel):
    operation: Literal["save_interface", "delete_interface", "set_link", "save_dns", "save_route", "delete_route", "save_traffic", "delete_traffic"]
    interface: InterfaceConfiguration | None = None
    interface_name: str | None = None
    link_up: bool | None = None
    dns: DnsSettings | None = None
    route: ManagedRoute | None = None
    traffic: TrafficRule | None = None
    object_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def matching_payload(self) -> "NetworkChange":
        required = {
            "save_interface": self.interface,
            "delete_interface": self.interface_name,
            "set_link": self.interface_name if self.link_up is not None else None,
            "save_dns": self.dns,
            "save_route": self.route,
            "delete_route": self.object_id,
            "save_traffic": self.traffic,
            "delete_traffic": self.object_id,
        }[self.operation]
        if required is None:
            raise ValueError("Operation payload is missing")
        if self.interface_name:
            _validate_ifname(self.interface_name)
        return self


class PlanRequest(StrictModel):
    change: NetworkChange
    confirmation_phrase: str = Field(default="", max_length=80)


class ApplyRequest(StrictModel):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    confirmation_phrase: str = Field(default="", max_length=80)


class TransactionRequest(StrictModel):
    transaction_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class NetworkProvider(ABC):
    id = "unsupported"
    writable = False

    @abstractmethod
    def commands(self, change: NetworkChange) -> list[list[str]]:
        raise NotImplementedError

    def capabilities(self) -> dict[str, bool]:
        return {
            "write": self.writable, "interfaces": self.writable, "bonds": self.writable,
            "vlans": self.writable, "bridges": self.writable, "dns": self.writable,
            "routes": True, "traffic_control": shutil.which("tc") is not None,
            "ingress_ifb": Path("/sys/module/ifb").exists(),
        }


def _nm_ip_args(family: Literal[4, 6], value: IPConfiguration) -> list[str]:
    prefix = "ipv4" if family == 4 else "ipv6"
    method = {"disabled": "disabled", "dhcp": "auto", "slaac": "auto", "dhcpv6": "dhcp", "manual": "manual"}[value.method]
    addresses = ",".join(f"{item.address}/{item.prefix}" for item in value.addresses)
    return [
        f"{prefix}.method", method,
        f"{prefix}.addresses", addresses,
        f"{prefix}.gateway", value.gateway or "",
        f"{prefix}.route-metric", str(value.metric),
        f"{prefix}.never-default", "no" if value.default_route else "yes",
        f"{prefix}.ignore-auto-routes", "yes" if value.ignore_auto_routes else "no",
        f"{prefix}.ignore-auto-dns", "yes" if value.ignore_auto_dns else "no",
        f"{prefix}.dns", ",".join(value.dns),
        f"{prefix}.dns-search", ",".join(value.search_domains),
    ]


class NetworkManagerProvider(NetworkProvider):
    id = "networkmanager"
    writable = True

    def commands(self, change: NetworkChange) -> list[list[str]]:
        nmcli = shutil.which("nmcli") or "nmcli"
        if change.operation == "set_link":
            return [[nmcli, "device", "connect" if change.link_up else "disconnect", change.interface_name or ""]]
        if change.operation == "delete_interface":
            return [[nmcli, "connection", "delete", f"webnas-{change.interface_name}"]]
        if change.operation == "save_dns" and change.dns:
            commands = []
            for interface, servers in change.dns.per_interface.items():
                result = _run_command([nmcli, "-g", "GENERAL.CONNECTION", "device", "show", interface], timeout=5)
                connection = result.stdout.strip().splitlines()[0][:256] if result.returncode == 0 and result.stdout.strip() else f"webnas-{interface}"
                ipv4 = ",".join(server for server in servers if ipaddress.ip_address(server).version == 4)
                ipv6 = ",".join(server for server in servers if ipaddress.ip_address(server).version == 6)
                commands.append([
                    nmcli, "connection", "modify", connection,
                    "ipv4.dns", ipv4, "ipv6.dns", ipv6,
                    "ipv4.dns-search", ",".join(change.dns.search_domains + change.dns.routing_domains),
                    "ipv6.dns-search", ",".join(change.dns.search_domains + change.dns.routing_domains),
                    "ipv4.ignore-auto-dns", "yes" if change.dns.ignore_dhcp else "no",
                    "ipv6.ignore-auto-dns", "yes" if change.dns.ignore_dhcp else "no",
                ])
                commands.append([nmcli, "connection", "up", connection])
            return commands
        if change.operation == "save_interface" and change.interface:
            item = change.interface
            connection = f"webnas-{item.name}"
            kind = {"physical": "ethernet", "bond": "bond", "vlan": "vlan", "bridge": "bridge"}[item.kind]
            add = [nmcli, "connection", "add", "type", kind, "ifname", item.name, "con-name", connection]
            if item.kind == "vlan":
                add += ["dev", item.parent or "", "id", str(item.vlan_id)]
            if item.kind == "bond":
                add += ["bond.options", f"mode={item.bond_mode},miimon={item.miimon},updelay={item.updelay},downdelay={item.downdelay},lacp_rate={item.lacp_rate},xmit_hash_policy={item.xmit_hash_policy}"]
            modify = [nmcli, "connection", "modify", connection, "connection.autoconnect", "yes" if item.autostart else "no", "802-3-ethernet.mtu", str(item.mtu), *_nm_ip_args(4, item.ipv4), *_nm_ip_args(6, item.ipv6)]
            commands = [[nmcli, "connection", "delete", connection], add, modify]
            slave_type = "bond-slave" if item.kind == "bond" else "bridge-slave"
            for member in item.members:
                commands.append([nmcli, "connection", "add", "type", slave_type, "ifname", member, "master", connection, "con-name", f"webnas-{item.name}-{member}"])
            commands.append([nmcli, "connection", "up", connection])
            return commands
        return []


def render_networkd(configuration: InterfaceConfiguration) -> dict[str, str]:
    match = f"[Match]\nName={configuration.name}\n\n"
    network = "[Network]\n"
    if configuration.ipv4.method == "dhcp":
        network += "DHCP=ipv4\n"
    if configuration.ipv6.method in {"slaac", "dhcpv6"}:
        network += "IPv6AcceptRA=yes\n"
    for address in configuration.ipv4.addresses + configuration.ipv6.addresses:
        network += f"Address={address.address}/{address.prefix}\n"
    for server in configuration.ipv4.dns + configuration.ipv6.dns:
        network += f"DNS={server}\n"
    for domain in configuration.ipv4.search_domains + configuration.ipv6.search_domains:
        network += f"Domains={domain}\n"
    for family in (configuration.ipv4, configuration.ipv6):
        if family.gateway:
            network += f"\n[Route]\nGateway={family.gateway}\nMetric={family.metric}\n"
    files = {
        f"80-webnas-{configuration.name}.network": match + network,
        f"80-webnas-{configuration.name}.link": f"[Match]\nOriginalName={configuration.name}\n\n[Link]\nMTUBytes={configuration.mtu}\n",
    }
    if configuration.kind == "bond":
        files[f"80-webnas-{configuration.name}.netdev"] = f"[NetDev]\nName={configuration.name}\nKind=bond\n\n[Bond]\nMode={configuration.bond_mode}\nMIIMonitorSec={configuration.miimon}ms\n"
        for member in configuration.members:
            files[f"79-webnas-{configuration.name}-{member}.network"] = f"[Match]\nName={member}\n\n[Network]\nBond={configuration.name}\n"
    elif configuration.kind == "vlan":
        files[f"80-webnas-{configuration.name}.netdev"] = f"[NetDev]\nName={configuration.name}\nKind=vlan\n\n[VLAN]\nId={configuration.vlan_id}\n"
        files[f"79-webnas-{configuration.name}-{configuration.parent}.network"] = f"[Match]\nName={configuration.parent}\n\n[Network]\nVLAN={configuration.name}\n"
    elif configuration.kind == "bridge":
        files[f"80-webnas-{configuration.name}.netdev"] = f"[NetDev]\nName={configuration.name}\nKind=bridge\n\n[Bridge]\nSTP={'yes' if configuration.stp else 'no'}\nForwardDelaySec={configuration.forward_delay}\n"
        for member in configuration.members:
            files[f"79-webnas-{configuration.name}-{member}.network"] = f"[Match]\nName={member}\n\n[Network]\nBridge={configuration.name}\n"
    return files


def render_netplan(configuration: InterfaceConfiguration) -> str:
    key = {"physical": "ethernets", "bond": "bonds", "vlan": "vlans", "bridge": "bridges"}[configuration.kind]
    item: dict[str, Any] = {
        "dhcp4": configuration.ipv4.method == "dhcp",
        "dhcp6": configuration.ipv6.method == "dhcpv6",
        "accept-ra": configuration.ipv6.method == "slaac",
        "mtu": configuration.mtu,
        "optional": not configuration.autostart,
    }
    addresses = [f"{address.address}/{address.prefix}" for address in configuration.ipv4.addresses + configuration.ipv6.addresses]
    if addresses:
        item["addresses"] = addresses
    nameservers = list(dict.fromkeys(configuration.ipv4.dns + configuration.ipv6.dns))
    domains = list(dict.fromkeys(configuration.ipv4.search_domains + configuration.ipv6.search_domains))
    if nameservers or domains:
        item["nameservers"] = {"addresses": nameservers, "search": domains}
    routes = []
    for family, default in ((configuration.ipv4, "0.0.0.0/0"), (configuration.ipv6, "::/0")):
        if family.gateway:
            routes.append({"to": default, "via": family.gateway, "metric": family.metric})
    if routes:
        item["routes"] = routes
    if configuration.kind == "bond":
        item["interfaces"] = configuration.members
        item["parameters"] = {"mode": configuration.bond_mode, "mii-monitor-interval": configuration.miimon}
    elif configuration.kind == "bridge":
        item["interfaces"] = configuration.members
        item["parameters"] = {"stp": configuration.stp, "forward-delay": configuration.forward_delay}
    elif configuration.kind == "vlan":
        item["id"] = configuration.vlan_id
        item["link"] = configuration.parent
    return yaml.safe_dump({"network": {"version": 2, "renderer": "networkd", key: {configuration.name: item}}}, sort_keys=False)


class SystemdNetworkdProvider(NetworkProvider):
    id = "systemd-networkd"
    writable = True

    def commands(self, change: NetworkChange) -> list[list[str]]:
        networkctl = shutil.which("networkctl") or "networkctl"
        if change.operation == "set_link":
            ip = shutil.which("ip") or "ip"
            return [[ip, "link", "set", "dev", change.interface_name or "", "up" if change.link_up else "down"]]
        if change.operation in {"save_interface", "delete_interface", "save_dns"}:
            commands = [[networkctl, "reload"]]
            if change.operation != "save_dns":
                commands.append([networkctl, "reconfigure", change.interface.name if change.interface else change.interface_name or "lo"])
            elif shutil.which("systemctl"):
                commands.append([shutil.which("systemctl") or "systemctl", "restart", "systemd-resolved.service"])
            return commands
        return []


class NetplanProvider(SystemdNetworkdProvider):
    id = "netplan"

    def commands(self, change: NetworkChange) -> list[list[str]]:
        if change.operation in {"save_interface", "delete_interface", "save_dns"}:
            commands = [[shutil.which("netplan") or "netplan", "generate"], [shutil.which("netplan") or "netplan", "apply"]]
            if change.operation == "save_dns" and shutil.which("systemctl"):
                commands.append([shutil.which("systemctl") or "systemctl", "restart", "systemd-resolved.service"])
            return commands
        return super().commands(change)


class ReadOnlyProvider(NetworkProvider):
    id = "ifupdown"

    def commands(self, change: NetworkChange) -> list[list[str]]:
        return []


def detect_provider() -> tuple[NetworkProvider, list[str]]:
    active: list[str] = []
    if shutil.which("nmcli") and (nm_result := _run_command([shutil.which("nmcli") or "nmcli", "-t", "-f", "RUNNING", "general"])).returncode == 0 and "running" in nm_result.stdout.lower():
        active.append("networkmanager")
    netplan_active = bool(shutil.which("netplan") and any(Path("/etc/netplan").glob("*.yaml")))
    if netplan_active:
        active.append("netplan")
    elif shutil.which("networkctl") and _run_command([shutil.which("networkctl") or "networkctl", "--no-pager", "list"]).returncode == 0:
        active.append("systemd-networkd")
    if Path("/etc/network/interfaces").exists():
        active.append("ifupdown")
    warnings = []
    writable = [item for item in active if item != "ifupdown"]
    if len(writable) > 1:
        return ReadOnlyProvider(), [f"Ambiguous network management: {', '.join(active)}"]
    if active[:1] == ["networkmanager"]:
        return NetworkManagerProvider(), warnings
    if "netplan" in active:
        return NetplanProvider(), warnings
    if "systemd-networkd" in active:
        return SystemdNetworkdProvider(), warnings
    return ReadOnlyProvider(), ["No safely writable network provider was detected"]


def _managed_state() -> dict[str, Any]:
    return _read_json(_state_root() / "state.json", {"interfaces": {}, "dns": None, "routes": {}, "traffic": {}})


def _commands_for_generic(change: NetworkChange) -> list[list[str]]:
    ip = shutil.which("ip") or "ip"
    tc = shutil.which("tc") or "tc"
    if change.operation == "save_route" and change.route:
        route = change.route
        family = "-4" if route.family == "ipv4" else "-6"
        command = [ip, family, "route", "replace", route.route_type, route.destination]
        if route.gateway:
            command += ["via", route.gateway]
        if route.interface:
            command += ["dev", route.interface]
        command += ["metric", str(route.metric), "table", str(route.table), "proto", "static"]
        return [command] if route.enabled else []
    if change.operation == "delete_route" and change.object_id:
        previous = _managed_state()["routes"].get(change.object_id)
        if previous:
            route = ManagedRoute.model_validate(previous)
            return [[ip, "-4" if route.family == "ipv4" else "-6", "route", "del", route.destination, "table", str(route.table)]]
    if change.operation == "save_traffic" and change.traffic:
        rule = change.traffic
        if not rule.enabled:
            return []
        handle = 0x7000 + int(rule.id[:3], 16) % 0x0FFF
        if rule.direction == "ingress":
            ifb = f"ifbw{rule.id[:8]}"
            return [
                [ip, "link", "add", ifb, "type", "ifb"],
                [ip, "link", "set", "dev", ifb, "up"],
                [tc, "qdisc", "replace", "dev", rule.interface, "handle", "ffff:", "ingress"],
                [tc, "filter", "replace", "dev", rule.interface, "parent", "ffff:", "protocol", "all", "u32", "match", "u32", "0", "0", "action", "mirred", "egress", "redirect", "dev", ifb],
                [tc, "qdisc", "replace", "dev", ifb, "root", "handle", f"{handle:x}:", "htb", "default", "1"],
                [tc, "class", "replace", "dev", ifb, "parent", f"{handle:x}:", "classid", f"{handle:x}:1", "htb", "rate", f"{rule.guaranteed_kbit or rule.maximum_kbit}kbit", "ceil", f"{rule.maximum_kbit}kbit", "prio", str(rule.priority)],
            ]
        rate = rule.guaranteed_kbit or rule.maximum_kbit
        commands = [
            [tc, "qdisc", "replace", "dev", rule.interface, "root", "handle", f"{handle:x}:", "htb", "default", "1"],
            [tc, "class", "replace", "dev", rule.interface, "parent", f"{handle:x}:", "classid", f"{handle:x}:1", "htb", "rate", f"{rate}kbit", "ceil", f"{rule.maximum_kbit}kbit", "prio", str(rule.priority)],
        ]
        filters: list[str] = []
        family = "ipv6" if any(":" in value for value in (rule.source_cidr or "", rule.destination_cidr or "")) else "ip"
        if rule.source_cidr:
            filters += ["src_ip", rule.source_cidr]
        if rule.destination_cidr:
            filters += ["dst_ip", rule.destination_cidr]
        if rule.protocol != "any":
            filters += ["ip_proto", rule.protocol]
        if rule.source_port:
            filters += ["src_port", str(rule.source_port)]
        if rule.destination_port:
            filters += ["dst_port", str(rule.destination_port)]
        if filters:
            commands.append([tc, "filter", "replace", "dev", rule.interface, "protocol", family, "parent", f"{handle:x}:", "prio", str(rule.priority), "flower", *filters, "flowid", f"{handle:x}:1"])
        return commands
    if change.operation == "delete_traffic" and change.object_id:
        previous = _managed_state()["traffic"].get(change.object_id)
        if previous:
            rule = TrafficRule.model_validate(previous)
            handle = 0x7000 + int(rule.id[:3], 16) % 0x0FFF
            if rule.direction == "ingress":
                ifb = f"ifbw{rule.id[:8]}"
                return [[tc, "qdisc", "del", "dev", rule.interface, "ingress"], [ip, "link", "del", ifb]]
            return [[tc, "qdisc", "del", "dev", rule.interface, "root", "handle", f"{handle:x}:"]]
    return []


def _client_interface(request: Request) -> str | None:
    address = request.client.host if request.client else ""
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return None
    items, _ = _ip_json(["route", "get", address])
    if items:
        device = str(items[0].get("dev") or "")
        return device if INTERFACE_RE.fullmatch(device) else None
    return None


def _conflicts(change: NetworkChange, state: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if change.interface:
        item = change.interface
        for name, existing in state["interfaces"].items():
            if name == item.name:
                continue
            parsed = InterfaceConfiguration.model_validate(existing)
            overlap = set(item.members) & set(parsed.members)
            if overlap:
                raise HTTPException(409, f"Interface member already belongs to {name}: {', '.join(sorted(overlap))}")
            if item.kind == "vlan" and parsed.kind == "vlan" and item.parent == parsed.parent and item.vlan_id == parsed.vlan_id:
                raise HTTPException(409, "This parent and VLAN ID are already managed")
        live = {entry["name"]: entry for entry in network_overview()["interfaces"]}
        for member in item.members:
            if member not in live or live[member].get("system"):
                raise HTTPException(409, f"Member cannot be used: {member}")
            if live[member].get("addresses"):
                warnings.append(f"{member} currently has IP addresses; IP configuration will move to {item.name}")
    if change.route:
        route = change.route
        for identifier, existing in state["routes"].items():
            if identifier != route.id:
                previous = ManagedRoute.model_validate(existing)
                if (previous.family, previous.destination, previous.table, previous.route_type) == (route.family, route.destination, route.table, route.route_type):
                    raise HTTPException(409, "A matching managed route already exists")
    if change.traffic and change.traffic.enabled:
        if not shutil.which("tc"):
            raise HTTPException(409, "Traffic control is unavailable")
        if change.traffic.direction == "ingress" and not Path("/sys/module/ifb").exists():
            raise HTTPException(409, "Ingress shaping requires the IFB kernel module")
        result = _run_command([shutil.which("tc") or "tc", "-j", "qdisc", "show", "dev", change.traffic.interface])
        if result.returncode == 0:
            try:
                qdiscs = json.loads(result.stdout or "[]")
            except ValueError:
                qdiscs = []
            for qdisc in qdiscs if isinstance(qdiscs, list) else []:
                handle = str(qdisc.get("handle") or "")
                root = bool(qdisc.get("root"))
                if root and handle and not re.fullmatch(r"7[0-9a-f]{3}:", handle):
                    raise HTTPException(409, "The interface already has unmanaged traffic control configuration")
    return warnings


def build_plan(change: NetworkChange, actor: str, client_interface: str | None) -> dict[str, Any]:
    provider, provider_warnings = detect_provider()
    if not provider.writable and change.operation not in {"save_route", "delete_route", "save_traffic", "delete_traffic"}:
        raise HTTPException(409, "The active network provider is read-only")
    state = _managed_state()
    warnings = provider_warnings + _conflicts(change, state)
    target = change.interface.name if change.interface else change.interface_name or change.object_id or "dns"
    routes = routing_snapshot()
    default_devices = {item["device"] for item in routes["gateways"]}
    risk = bool(target == client_interface or target in default_devices or (change.interface and set(change.interface.members) & ({client_interface} | default_devices)))
    if change.route and change.route.destination in {"0.0.0.0/0", "::/0"}:
        warnings.append("The default route will change")
        risk = True
    commands = provider.commands(change) + _commands_for_generic(change)
    plan_id = uuid.uuid4().hex
    before = state
    after = json.loads(json.dumps(state))
    if change.operation == "save_interface" and change.interface:
        after["interfaces"][change.interface.name] = change.interface.model_dump(mode="json")
    elif change.operation == "delete_interface" and change.interface_name:
        after["interfaces"].pop(change.interface_name, None)
    elif change.operation == "save_dns" and change.dns:
        after["dns"] = change.dns.model_dump(mode="json")
    elif change.operation == "save_route" and change.route:
        after["routes"][change.route.id] = change.route.model_dump(mode="json")
    elif change.operation == "delete_route" and change.object_id:
        after["routes"].pop(change.object_id, None)
    elif change.operation == "save_traffic" and change.traffic:
        after["traffic"][change.traffic.id] = change.traffic.model_dump(mode="json")
    elif change.operation == "delete_traffic" and change.object_id:
        after["traffic"].pop(change.object_id, None)
    plan = {
        "id": plan_id, "actor": actor, "created_at": time.time(), "expires_at": time.time() + 600,
        "provider": provider.id, "change": change.model_dump(mode="json"), "target": target,
        "before": before, "after": after, "commands": redact(commands), "warnings": warnings[:32],
        "high_risk": risk, "required_phrase": f"APPLY {target}" if risk else "",
        "rollback_supported": shutil.which("systemd-run") is not None, "rollback_seconds": ROLLBACK_SECONDS,
        "client_interface": client_interface,
    }
    plans = _state_root() / "plans"
    plans.mkdir(exist_ok=True)
    _atomic_json(plans / f"{plan_id}.json", plan)
    record_activity(ActivityCategory.configuration, "network_plan", actor, target=target, details={"provider": provider.id, "operation": change.operation, "warnings": warnings, "high_risk": risk}, source="network")
    return plan


def _provider_by_id(identifier: str) -> NetworkProvider:
    return {"networkmanager": NetworkManagerProvider(), "systemd-networkd": SystemdNetworkdProvider(), "netplan": NetplanProvider()}.get(identifier, ReadOnlyProvider())


def _write_provider_files(provider: NetworkProvider, change: NetworkChange, snapshot: dict[str, Any]) -> None:
    if change.operation == "save_dns" and change.dns and isinstance(provider, (SystemdNetworkdProvider, NetplanProvider)):
        directory = Path("/etc/systemd/resolved.conf.d")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "80-webnas.conf"
        snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
        servers = " ".join(change.dns.servers)
        domains = " ".join(change.dns.search_domains + change.dns.routing_domains)
        path.write_text(f"[Resolve]\nDNS={servers}\nDomains={domains}\n", encoding="utf-8")
        return
    interface_name = change.interface.name if change.interface else change.interface_name
    if not interface_name or change.operation not in {"save_interface", "delete_interface"}:
        return
    if isinstance(provider, SystemdNetworkdProvider) and not isinstance(provider, NetplanProvider):
        directory = Path("/etc/systemd/network")
        rendered = render_networkd(change.interface) if change.interface else {}
        previous = _managed_state().get("interfaces", {}).get(interface_name)
        previous_names = set(render_networkd(InterfaceConfiguration.model_validate(previous))) if previous else set()
        names = set(rendered) | previous_names | {f"80-webnas-{interface_name}.network", f"80-webnas-{interface_name}.netdev", f"80-webnas-{interface_name}.link"}
        for name in names:
            path = directory / name
            snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
            if name in rendered:
                path.write_text(rendered[name], encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
    elif isinstance(provider, NetplanProvider):
        path = Path("/etc/netplan") / f"90-webnas-{interface_name}.yaml"
        snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
        if change.interface:
            path.write_text(render_netplan(change.interface), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


def _write_restore_service(change: NetworkChange, snapshot: dict[str, Any]) -> bool:
    if change.operation not in {"save_route", "delete_route", "save_traffic", "delete_traffic"}:
        return False
    path = Path("/etc/systemd/system/webnas-network-managed.service")
    snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
    content = (
        "[Unit]\nDescription=Restore WebNAS managed routes and traffic control\n"
        "After=network-online.target\nWants=network-online.target\n\n"
        "[Service]\nType=oneshot\n"
        f"ExecStart={sys.executable} -m app.network_management --restore-managed\n"
        "RemainAfterExit=yes\n\n[Install]\nWantedBy=multi-user.target\n"
    )
    path.write_text(content, encoding="utf-8")
    return True


def _capture_provider_state(provider: NetworkProvider, change: NetworkChange, snapshot: dict[str, Any]) -> None:
    snapshot["live"] = {
        "interfaces": network_overview(),
        "routing": routing_snapshot(),
        "dns": dns_configuration(),
    }
    if not isinstance(provider, NetworkManagerProvider):
        return
    nmcli = shutil.which("nmcli") or "nmcli"
    result = _run_command([nmcli, "-t", "-f", "UUID", "connection", "show", "--active"], timeout=8)
    snapshot["active_nm_uuids"] = [
        value.strip() for value in result.stdout.splitlines()
        if re.fullmatch(r"[0-9a-fA-F-]{36}", value.strip())
    ][:128]
    target = change.interface.name if change.interface else change.interface_name
    if not target:
        return
    directory = Path("/etc/NetworkManager/system-connections")
    if directory.is_dir():
        for path in directory.glob(f"webnas-{target}*.nmconnection"):
            snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.is_file() else None


def _restore_managed_configuration() -> None:
    state = _managed_state()
    for value in state.get("routes", {}).values():
        route = ManagedRoute.model_validate(value)
        if not route.autostart:
            continue
        change = NetworkChange(operation="save_route", route=route)
        for command in _commands_for_generic(change):
            _run_command(command, timeout=30)
    for value in state.get("traffic", {}).values():
        change = NetworkChange(operation="save_traffic", traffic=TrafficRule.model_validate(value))
        for command in _commands_for_generic(change):
            _run_command(command, timeout=30)


def _schedule_rollback(transaction_id: str, seconds: int) -> str | None:
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return None
    unit = f"webnas-network-rollback-{transaction_id}.service"
    command = [systemd_run, "--unit", unit.removesuffix(".service"), f"--on-active={seconds}s", "--collect", sys.executable, "-m", "app.network_management", "--rollback", transaction_id]
    result = _run_command(command, timeout=8)
    return unit if result.returncode == 0 else None


def apply_plan(plan_id: str, actor: str, confirmation_phrase: str) -> dict[str, Any]:
    if not _transaction_lock.acquire(blocking=False):
        raise HTTPException(409, "Another network operation is active")
    process_lock: int | None = None
    try:
        process_lock = _acquire_process_lock()
        if _active_transaction():
            raise HTTPException(409, "A network transaction is awaiting confirmation")
        plan = _read_json(_state_root() / "plans" / f"{plan_id}.json", None)
        if not isinstance(plan, dict) or plan.get("actor") != actor or float(plan.get("expires_at", 0)) < time.time():
            raise HTTPException(404, "Network plan is missing or expired")
        if plan.get("required_phrase") and confirmation_phrase != plan["required_phrase"]:
            raise HTTPException(400, "The high-risk confirmation phrase is incorrect")
        if not plan.get("rollback_supported"):
            raise HTTPException(503, "A durable systemd rollback mechanism is unavailable")
        change = NetworkChange.model_validate(plan["change"])
        provider = _provider_by_id(str(plan["provider"]))
        transaction_id = uuid.uuid4().hex
        transaction_dir = _state_root() / "transactions" / transaction_id
        transaction_dir.mkdir(parents=True)
        snapshot = {"state": plan["before"], "files": {}, "commands": plan["commands"], "actor": actor}
        _capture_provider_state(provider, change, snapshot)
        _write_provider_files(provider, change, snapshot)
        restore_service_changed = _write_restore_service(change, snapshot)
        _atomic_json(transaction_dir / "snapshot.json", snapshot)
        commands = provider.commands(change) + _commands_for_generic(change)
        executed: list[list[str]] = []
        for command in commands:
            result = _run_command(command, timeout=30)
            executed.append(command)
            if result.returncode and not (change.operation == "save_interface" and command[1:4] == ["connection", "delete", f"webnas-{change.interface.name if change.interface else ''}"]):
                rollback_transaction(transaction_id, automatic=True)
                raise HTTPException(502, "Network configuration failed and was rolled back")
        _atomic_json(_state_root() / "state.json", plan["after"])
        if restore_service_changed:
            systemctl = shutil.which("systemctl")
            if not systemctl:
                rollback_transaction(transaction_id, automatic=True)
                raise HTTPException(503, "Persistent network restore requires systemd")
            for command in ([systemctl, "daemon-reload"], [systemctl, "enable", "webnas-network-managed.service"]):
                if _run_command(command, timeout=15).returncode:
                    rollback_transaction(transaction_id, automatic=True)
                    raise HTTPException(502, "Could not enable persistent network configuration")
        unit = _schedule_rollback(transaction_id, ROLLBACK_SECONDS)
        if not unit:
            rollback_transaction(transaction_id, automatic=True)
            raise HTTPException(503, "A durable rollback timer could not be scheduled")
        transaction = {
            "id": transaction_id, "state": "pending_confirmation", "actor": actor,
            "provider": provider.id, "started_at": time.time(), "deadline": time.time() + ROLLBACK_SECONDS,
            "rollback_unit": unit, "plan_id": plan_id, "target": plan["target"],
        }
        _atomic_json(transaction_dir / "transaction.json", transaction)
        _atomic_json(_state_root() / "active.json", transaction)
        record_activity(ActivityCategory.configuration, "network_apply", actor, target=plan["target"], details={"provider": provider.id, "plan_id": plan_id, "warnings": plan["warnings"], "rollback_unit": unit}, source="network")
        return transaction
    finally:
        if process_lock is not None:
            _release_process_lock(process_lock)
        _transaction_lock.release()


def _active_transaction() -> dict[str, Any] | None:
    value = _read_json(_state_root() / "active.json", None)
    return value if isinstance(value, dict) and value.get("state") == "pending_confirmation" else None


def confirm_transaction(transaction_id: str, actor: str) -> dict[str, Any]:
    active = _active_transaction()
    if not active or active.get("id") != transaction_id:
        raise HTTPException(404, "No pending network transaction")
    unit = active.get("rollback_unit")
    if unit and shutil.which("systemctl"):
        systemctl = shutil.which("systemctl") or "systemctl"
        for suffix in (".timer", ".service"):
            name = str(unit).removesuffix(".service").removesuffix(".timer") + suffix
            _run_command([systemctl, "stop", name], timeout=8)
            _run_command([systemctl, "reset-failed", name], timeout=8)
    active.update({"state": "confirmed", "confirmed_at": time.time(), "confirmed_by": actor})
    _atomic_json(_state_root() / "transactions" / transaction_id / "transaction.json", active)
    (_state_root() / "active.json").unlink(missing_ok=True)
    record_activity(ActivityCategory.configuration, "network_confirm", actor, target=str(active.get("target") or ""), details={"provider": active.get("provider"), "transaction_id": transaction_id, "confirmed": True}, source="network")
    return active


def rollback_transaction(transaction_id: str, actor: str = "system", automatic: bool = False) -> dict[str, Any]:
    directory = _state_root() / "transactions" / transaction_id
    snapshot = _read_json(directory / "snapshot.json", None)
    if not isinstance(snapshot, dict):
        raise HTTPException(404, "Network snapshot was not found")
    for raw_path, content in snapshot.get("files", {}).items():
        path = Path(raw_path)
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(str(content), encoding="utf-8")
    restore_unit = "/etc/systemd/system/webnas-network-managed.service"
    if restore_unit in snapshot.get("files", {}) and shutil.which("systemctl"):
        systemctl = shutil.which("systemctl") or "systemctl"
        if snapshot["files"][restore_unit] is None:
            _run_command([systemctl, "disable", "webnas-network-managed.service"], timeout=10)
        _run_command([systemctl, "daemon-reload"], timeout=10)
    _atomic_json(_state_root() / "state.json", snapshot.get("state", {}))
    active = _read_json(directory / "transaction.json", {"id": transaction_id})
    active.update({"state": "rolled_back", "rolled_back_at": time.time(), "automatic": automatic, "rolled_back_by": actor})
    _atomic_json(directory / "transaction.json", active)
    (_state_root() / "active.json").unlink(missing_ok=True)
    provider_id = str(active.get("provider") or "")
    if provider_id == "networkmanager":
        nmcli = shutil.which("nmcli") or "nmcli"
        commands = [[nmcli, "connection", "reload"]]
        commands.extend(
            [nmcli, "connection", "up", "uuid", identifier]
            for identifier in snapshot.get("active_nm_uuids", [])
            if re.fullmatch(r"[0-9a-fA-F-]{36}", str(identifier))
        )
    elif provider_id == "netplan":
        commands = [[shutil.which("netplan") or "netplan", "generate"], [shutil.which("netplan") or "netplan", "apply"]]
    elif provider_id == "systemd-networkd":
        commands = [[shutil.which("networkctl") or "networkctl", "reload"]]
    else:
        commands = []
    for command in commands:
        _run_command(command, timeout=20)
    record_activity(ActivityCategory.configuration, "network_rollback", actor, target=str(active.get("target") or ""), status=ActivityStatus.info, details={"provider": active.get("provider"), "transaction_id": transaction_id, "automatic": automatic}, source="network")
    return active


def management_state() -> dict[str, Any]:
    provider, warnings = detect_provider()
    state = _managed_state()
    overview = network_overview()
    routes = routing_snapshot()
    dns = dns_configuration()
    return {
        "provider": {"id": provider.id, "writable": provider.writable, "capabilities": provider.capabilities(), "warnings": warnings},
        "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        "interfaces": overview["interfaces"],
        "dns": dns,
        "routing": routes,
        "managed": state,
        "transaction": _active_transaction(),
        "tools": {name: shutil.which(name) is not None for name in ("ip", "tc", "ethtool", "nmcli", "networkctl", "resolvectl", "netplan", "tracepath", "traceroute")},
    }


def _mutating_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def _permission_for(change: NetworkChange) -> Permission:
    if change.operation in {"save_dns"}:
        return Permission.NETWORK_DNS
    if change.operation in {"save_route", "delete_route"}:
        return Permission.NETWORK_ROUTES
    if change.operation in {"save_traffic", "delete_traffic"}:
        return Permission.NETWORK_TRAFFIC
    if change.operation == "set_link":
        return Permission.NETWORK_CONNECTIONS
    if change.interface and change.interface.kind == "bond":
        return Permission.NETWORK_BONDS
    if change.interface and change.interface.kind == "vlan":
        return Permission.NETWORK_VLANS
    if change.interface and change.interface.kind == "bridge":
        return Permission.NETWORK_BRIDGES
    return Permission.NETWORK_INTERFACES


@router.get("/management")
def management_endpoint(user: SessionUser = Depends(require_permission(Permission.NETWORK_CONFIG_VIEW))):
    return management_state()


@router.post("/plans")
def plan_endpoint(payload: PlanRequest, request: Request, user: SessionUser = Depends(_mutating_user)):
    authorize(user, _permission_for(payload.change))
    return build_plan(payload.change, user.username, _client_interface(request))


@router.post("/apply")
def apply_endpoint(payload: ApplyRequest, user: SessionUser = Depends(_mutating_user)):
    plan = _read_json(_state_root() / "plans" / f"{payload.plan_id}.json", {})
    if not isinstance(plan, dict) or not plan.get("change"):
        raise HTTPException(404, "Network plan is missing or expired")
    try:
        change = NetworkChange.model_validate(plan["change"])
    except ValueError as error:
        raise HTTPException(404, "Network plan is invalid") from error
    authorize(user, _permission_for(change))
    return apply_plan(payload.plan_id, user.username, payload.confirmation_phrase)


@router.post("/confirm")
def confirm_endpoint(payload: TransactionRequest, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.NETWORK_CONFIRM)
    return confirm_transaction(payload.transaction_id, user.username)


@router.post("/rollback")
def rollback_endpoint(payload: TransactionRequest, user: SessionUser = Depends(_mutating_user)):
    authorize(user, Permission.NETWORK_ROLLBACK)
    return rollback_transaction(payload.transaction_id, user.username)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rollback" and re.fullmatch(r"[a-f0-9]{32}", sys.argv[2]):
        rollback_transaction(sys.argv[2], automatic=True)
    elif len(sys.argv) == 2 and sys.argv[1] == "--restore-managed":
        _restore_managed_configuration()
