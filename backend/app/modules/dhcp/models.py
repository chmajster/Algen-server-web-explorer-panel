from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
INTERFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DhcpBackend(StrEnum):
    kea = "kea"
    isc = "isc"
    none = "none"


def normalize_mac(value: str) -> str:
    value = value.strip().replace("-", ":").lower()
    if not MAC_RE.fullmatch(value):
        raise ValueError("invalid MAC address")
    first = int(value.split(":", 1)[0], 16)
    if first & 1:
        raise ValueError("multicast MAC addresses cannot be DHCP reservations")
    return value


def ipv4(value: str, *, allow_empty: bool = False) -> str:
    if not value and allow_empty:
        return ""
    address = ipaddress.ip_address(value)
    if address.version != 4 or address.is_multicast or address.is_unspecified:
        raise ValueError("a usable IPv4 address is required")
    return str(address)


class DhcpThresholds(StrictModel):
    warning: int = Field(default=70, ge=1, le=100)
    critical: int = Field(default=85, ge=1, le=100)
    emergency: int = Field(default=95, ge=1, le=100)

    @model_validator(mode="after")
    def ordered(self) -> "DhcpThresholds":
        if not self.warning < self.critical < self.emergency:
            raise ValueError("utilization thresholds must satisfy warning < critical < emergency")
        return self


class DhcpSubnet(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=128)
    cidr: str = Field(min_length=7, max_length=32)
    gateway: str = ""
    subnet_mask: str = ""
    pool_start: str
    pool_end: str
    dns_servers: list[str] = Field(default_factory=list, max_length=8)
    domain_name: str = Field(default="", max_length=253)
    search_domain: str = Field(default="", max_length=253)
    lease_time: int = Field(default=3600, ge=60, le=31_536_000)
    max_lease_time: int = Field(default=7200, ge=60, le=63_072_000)
    ntp_servers: list[str] = Field(default_factory=list, max_length=8)
    broadcast_address: str = ""
    tftp_server: str = Field(default="", max_length=253)
    boot_filename: str = Field(default="", max_length=255)
    pxe_enabled: bool = False
    enabled: bool = True
    description: str = Field(default="", max_length=2000)

    @field_validator("cidr")
    @classmethod
    def valid_cidr(cls, value: str) -> str:
        network = ipaddress.ip_network(value, strict=True)
        if network.version != 4 or network.prefixlen > 30:
            raise ValueError("DHCP subnet must be an IPv4 network with at least two host addresses")
        return str(network)

    @field_validator("gateway", "broadcast_address", "tftp_server")
    @classmethod
    def valid_optional_ipv4_or_hostname(cls, value: str, info) -> str:
        if not value:
            return ""
        if info.field_name == "tftp_server":
            try:
                return ipv4(value)
            except ValueError:
                if not HOSTNAME_RE.fullmatch(value):
                    raise ValueError("TFTP server must be a valid IPv4 address or hostname")
                return value.lower()
        return ipv4(value)

    @field_validator("pool_start", "pool_end")
    @classmethod
    def valid_pool_address(cls, value: str) -> str:
        return ipv4(value)

    @field_validator("dns_servers", "ntp_servers")
    @classmethod
    def valid_server_addresses(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(ipv4(value) for value in values))

    @field_validator("domain_name", "search_domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        if value and not HOSTNAME_RE.fullmatch(value):
            raise ValueError("invalid DNS domain")
        return value.lower().rstrip(".")

    @model_validator(mode="after")
    def valid_network_membership(self) -> "DhcpSubnet":
        network = ipaddress.ip_network(self.cidr, strict=True)
        start = ipaddress.ip_address(self.pool_start)
        end = ipaddress.ip_address(self.pool_end)
        if int(start) > int(end):
            raise ValueError("pool start must not be greater than pool end")
        if start not in network or end not in network:
            raise ValueError("DHCP pool must be inside its subnet")
        if start in {network.network_address, network.broadcast_address} or end in {network.network_address, network.broadcast_address}:
            raise ValueError("DHCP pool cannot include the network or broadcast address")
        if self.gateway:
            gateway = ipaddress.ip_address(self.gateway)
            if gateway not in network or gateway in {network.network_address, network.broadcast_address}:
                raise ValueError("gateway must be a usable address inside the subnet")
        expected_broadcast = str(network.broadcast_address)
        if self.broadcast_address and self.broadcast_address != expected_broadcast:
            raise ValueError("broadcast address does not match the subnet")
        self.broadcast_address = expected_broadcast
        self.subnet_mask = str(network.netmask)
        if self.max_lease_time < self.lease_time:
            raise ValueError("max lease time must be greater than or equal to lease time")
        return self


class DhcpReservation(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    hostname: str = Field(min_length=1, max_length=253)
    mac_address: str
    ipv4_address: str
    subnet_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    description: str = Field(default="", max_length=2000)
    client_identifier: str = Field(default="", max_length=255)
    enabled: bool = True
    create_dns_record: bool = False
    dns_provider: Literal["auto", "pihole", "adguard-home"] = "auto"

    @field_validator("hostname")
    @classmethod
    def valid_hostname(cls, value: str) -> str:
        value = value.rstrip(".")
        if not HOSTNAME_RE.fullmatch(value):
            raise ValueError("invalid reservation hostname")
        return value.lower()

    _mac = field_validator("mac_address")(lambda value: normalize_mac(value))
    _address = field_validator("ipv4_address")(lambda value: ipv4(value))


class DhcpConfiguration(StrictModel):
    interfaces: list[str] = Field(default_factory=list, max_length=32)
    authoritative: bool = True
    default_lease_time: int = Field(default=3600, ge=60, le=31_536_000)
    max_lease_time: int = Field(default=7200, ge=60, le=63_072_000)
    thresholds: DhcpThresholds = Field(default_factory=DhcpThresholds)
    subnets: list[DhcpSubnet] = Field(default_factory=list, max_length=512)
    reservations: list[DhcpReservation] = Field(default_factory=list, max_length=10000)

    @field_validator("interfaces")
    @classmethod
    def valid_interfaces(cls, values: list[str]) -> list[str]:
        if any(not INTERFACE_RE.fullmatch(value) for value in values):
            raise ValueError("invalid network interface name")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def valid_lease_defaults(self) -> "DhcpConfiguration":
        if self.max_lease_time < self.default_lease_time:
            raise ValueError("global max lease time must be greater than or equal to default lease time")
        return self


class DhcpLease(StrictModel):
    id: str
    hostname: str = ""
    ipv4_address: str
    mac_address: str = ""
    client_identifier: str = ""
    subnet_id: str = ""
    subnet: str = ""
    lease_start: float | None = None
    lease_end: float | None = None
    remaining_seconds: int = 0
    state: Literal["active", "expired", "declined", "released", "unknown"] = "unknown"
    reserved: bool = False


class DhcpInterface(StrictModel):
    name: str
    state: str = "unknown"
    mac_address: str = ""
    ipv4_addresses: list[str] = Field(default_factory=list)
    subnets: list[str] = Field(default_factory=list)
    dhcp_enabled: bool = False


class DhcpUtilization(StrictModel):
    subnet_id: str
    subnet: str
    pool_start: str
    pool_end: str
    used: int
    available: int
    total: int
    usage_percent: float
    level: Literal["normal", "warning", "critical", "emergency"]


class DhcpValidationIssue(StrictModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    object_id: str = ""


class DhcpValidationResult(StrictModel):
    ok: bool
    backend: DhcpBackend = DhcpBackend.none
    issues: list[DhcpValidationIssue] = Field(default_factory=list)
    native_output: str = ""
    candidate_sha256: str = ""


class DhcpConfigurationPlan(StrictModel):
    validation: DhcpValidationResult
    added_subnets: list[str] = Field(default_factory=list)
    removed_subnets: list[str] = Field(default_factory=list)
    changed_subnets: list[str] = Field(default_factory=list)
    added_reservations: list[str] = Field(default_factory=list)
    removed_reservations: list[str] = Field(default_factory=list)
    changed_reservations: list[str] = Field(default_factory=list)
    changed_global_options: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DhcpDiagnostic(StrictModel):
    status: Literal["PASS", "WARNING", "FAIL"]
    code: str
    title: str
    detail: str = ""
    recommendation: str = ""


class DhcpStatus(StrictModel):
    installed: bool
    backend: DhcpBackend = DhcpBackend.none
    version: str = ""
    service: str = ""
    service_state: str = "not_installed"
    service_enabled: bool = False
    uptime_seconds: int | None = None
    interfaces: list[str] = Field(default_factory=list)
    active_leases: int = 0
    available_addresses: int = 0
    used_addresses: int = 0
    subnet_count: int = 0
    reservation_count: int = 0
    last_errors: list[str] = Field(default_factory=list)
    last_config_change: float | None = None
    configuration_valid: bool | None = None
    health: Literal["healthy", "degraded", "failed", "unknown", "not_installed"] = "unknown"
    blocked_by_proxmox: bool = False


class DhcpActionRequest(StrictModel):
    confirmation: str = Field(min_length=1, max_length=256)
    pam_password: str = Field(min_length=1, max_length=1024)


class DhcpConfigurationMutationRequest(DhcpActionRequest):
    configuration: DhcpConfiguration


class DhcpSubnetCreateRequest(DhcpActionRequest):
    subnet: DhcpSubnet


class DhcpReservationCreateRequest(DhcpActionRequest):
    reservation: DhcpReservation


class DhcpRestoreRequest(DhcpActionRequest):
    backup_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")


class DhcpBackupRequest(DhcpActionRequest):
    description: str = Field(default="", max_length=500)


class LeaseToReservationRequest(DhcpActionRequest):
    hostname: str = Field(default="", max_length=253)
    description: str = Field(default="", max_length=2000)
    create_dns_record: bool = False
    dns_provider: Literal["auto", "pihole", "adguard-home"] = "auto"


class LeaseToHostRequest(DhcpActionRequest):
    ssh_user: str = Field(default="algen-ansible", min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


class HostToReservationRequest(DhcpActionRequest):
    subnet_id: str = Field(min_length=1, max_length=64)
    mac_address: str
    hostname: str = Field(default="", max_length=253)
    create_dns_record: bool = False
    dns_provider: Literal["auto", "pihole", "adguard-home"] = "auto"

    _mac = field_validator("mac_address")(lambda value: normalize_mac(value))
