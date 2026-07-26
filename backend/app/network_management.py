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
        for value in (self.source_cidr, self.destination_cidr):
            if value:
                ipaddress.ip_network(value, strict=False)
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
                commands.append([nmcli, "connection", "modify", f"webnas-{interface}", "ipv4.dns", ",".join(servers), "ipv4.ignore-auto-dns", "yes" if change.dns.ignore_dhcp else "no"])
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
    for gateway in (configuration.ipv4.gateway, configuration.ipv6.gateway):
        if gateway:
            network += f"Gateway={gateway}\n"
    for server in configuration.ipv4.dns + configuration.ipv6.dns:
        network += f"DNS={server}\n"
    files = {f"80-webnas-{configuration.name}.network": match + network}
    if configuration.kind == "bond":
        files[f"80-webnas-{configuration.name}.netdev"] = f"[NetDev]\nName={configuration.name}\nKind=bond\n\n[Bond]\nMode={configuration.bond_mode}\nMIIMonitorSec={configuration.miimon}ms\n"
    elif configuration.kind == "vlan":
        files[f"80-webnas-{configuration.name}.netdev"] = f"[NetDev]\nName={configuration.name}\nKind=vlan\n\n[VLAN]\nId={configuration.vlan_id}\n"
    elif configuration.kind == "bridge":
        files[f"80-webnas-{configuration.name}.netdev"] = f"[NetDev]\nName={configuration.name}\nKind=bridge\n\n[Bridge]\nSTP={'yes' if configuration.stp else 'no'}\nForwardDelaySec={configuration.forward_delay}\n"
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
            return [[networkctl, "reload"], [networkctl, "reconfigure", change.interface.name if change.interface else change.interface_name or "lo"]]
        return []


class NetplanProvider(SystemdNetworkdProvider):
    id = "netplan"

    def commands(self, change: NetworkChange) -> list[list[str]]:
        if change.operation in {"save_interface", "delete_interface", "save_dns"}:
            return [[shutil.which("netplan") or "netplan", "generate"], [shutil.which("netplan") or "netplan", "apply"]]
        return super().commands(change)


class ReadOnlyProvider(NetworkProvider):
    id = "ifupdown"

    def commands(self, change: NetworkChange) -> list[list[str]]:
        return []


def detect_provider() -> tuple[NetworkProvider, list[str]]:
    active: list[str] = []
    if shutil.which("nmcli") and _run_command([shutil.which("nmcli") or "nmcli", "-t", "-f", "RUNNING", "general"]).returncode == 0:
        active.append("networkmanager")
    if shutil.which("netplan") and any(Path("/etc/netplan").glob("*.yaml")):
        active.append("netplan")
    if shutil.which("networkctl") and _run_command([shutil.which("networkctl") or "networkctl", "--no-pager", "list"]).returncode == 0:
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
            return [[tc, "qdisc", "replace", "dev", rule.interface, "handle", f"{handle:x}:", "ingress"]]
        rate = rule.guaranteed_kbit or rule.maximum_kbit
        return [
            [tc, "qdisc", "replace", "dev", rule.interface, "root", "handle", f"{handle:x}:", "htb", "default", "1"],
            [tc, "class", "replace", "dev", rule.interface, "parent", f"{handle:x}:", "classid", f"{handle:x}:1", "htb", "rate", f"{rate}kbit", "ceil", f"{rule.maximum_kbit}kbit", "prio", str(rule.priority)],
        ]
    if change.operation == "delete_traffic" and change.object_id:
        previous = _managed_state()["traffic"].get(change.object_id)
        if previous:
            rule = TrafficRule.model_validate(previous)
            handle = 0x7000 + int(rule.id[:3], 16) % 0x0FFF
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
        "rollback_supported": True, "rollback_seconds": ROLLBACK_SECONDS,
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
    if not change.interface or change.operation != "save_interface":
        return
    if isinstance(provider, SystemdNetworkdProvider) and not isinstance(provider, NetplanProvider):
        directory = Path("/etc/systemd/network")
        for name, content in render_networkd(change.interface).items():
            path = directory / name
            snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
            path.write_text(content, encoding="utf-8")
    elif isinstance(provider, NetplanProvider):
        path = Path("/etc/netplan") / f"90-webnas-{change.interface.name}.yaml"
        snapshot.setdefault("files", {})[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
        path.write_text(render_netplan(change.interface), encoding="utf-8")


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
    try:
        plan = _read_json(_state_root() / "plans" / f"{plan_id}.json", None)
        if not isinstance(plan, dict) or plan.get("actor") != actor or float(plan.get("expires_at", 0)) < time.time():
            raise HTTPException(404, "Network plan is missing or expired")
        if plan.get("required_phrase") and confirmation_phrase != plan["required_phrase"]:
            raise HTTPException(400, "The high-risk confirmation phrase is incorrect")
        change = NetworkChange.model_validate(plan["change"])
        provider = _provider_by_id(str(plan["provider"]))
        transaction_id = uuid.uuid4().hex
        transaction_dir = _state_root() / "transactions" / transaction_id
        transaction_dir.mkdir(parents=True)
        snapshot = {"state": plan["before"], "files": {}, "commands": plan["commands"], "actor": actor}
        _write_provider_files(provider, change, snapshot)
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
        unit = _schedule_rollback(transaction_id, ROLLBACK_SECONDS)
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
        _run_command([shutil.which("systemctl") or "systemctl", "stop", unit], timeout=8)
        _run_command([shutil.which("systemctl") or "systemctl", "reset-failed", unit], timeout=8)
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
    _atomic_json(_state_root() / "state.json", snapshot.get("state", {}))
    active = _read_json(directory / "transaction.json", {"id": transaction_id})
    active.update({"state": "rolled_back", "rolled_back_at": time.time(), "automatic": automatic, "rolled_back_by": actor})
    _atomic_json(directory / "transaction.json", active)
    (_state_root() / "active.json").unlink(missing_ok=True)
    provider = _provider_by_id(str(active.get("provider") or ""))
    reload_change = NetworkChange(operation="set_link", interface_name="lo", link_up=True)
    for command in provider.commands(reload_change):
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
    change = NetworkChange.model_validate(plan.get("change", {}))
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
