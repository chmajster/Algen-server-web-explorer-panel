from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NtpBackend(StrEnum):
    chrony = "chrony"
    timesyncd = "systemd-timesyncd"
    ntpd = "ntpd"
    none = "none"


class NtpMode(StrEnum):
    disabled = "disabled"
    client = "client"
    server = "server"
    client_server = "client_server"


class NtpSourceKind(StrEnum):
    server = "server"
    pool = "pool"


def validate_host(value: str) -> str:
    value = value.strip().rstrip(".")
    if not value or any(char.isspace() for char in value) or "/" in value or "\\" in value:
        raise ValueError("invalid NTP host")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if not _HOST_RE.fullmatch(value):
            raise ValueError("NTP host must be a valid hostname, IPv4 or IPv6 address") from None
        return value.lower()
    if address.is_unspecified or address.is_multicast:
        raise ValueError("NTP host must be a usable unicast address")
    return str(address)


def validate_cidr(value: str) -> str:
    try:
        network = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError as error:
        raise ValueError("invalid IPv4/IPv6 CIDR") from error
    if network.is_unspecified or network.is_multicast:
        raise ValueError("NTP client network must be a usable unicast network")
    return str(network)


class NtpSourceInput(StrictModel):
    server: str = Field(min_length=1, max_length=253)
    kind: NtpSourceKind = NtpSourceKind.server
    prefer: bool = False
    enabled: bool = True
    confirm: bool = False

    @field_validator("server")
    @classmethod
    def validate_server(cls, value: str) -> str:
        return validate_host(value)


class NtpSourcesMutation(StrictModel):
    sources: list[NtpSourceInput] = Field(default_factory=list, max_length=64)
    confirm: bool = False

    @model_validator(mode="after")
    def validate_sources(self) -> "NtpSourcesMutation":
        servers = [item.server for item in self.sources]
        if len(servers) != len(set(servers)):
            raise ValueError("duplicate NTP sources are not allowed")
        return self


class NtpAllowedNetwork(StrictModel):
    cidr: str = Field(min_length=3, max_length=64)
    description: str = Field(default="", max_length=200)
    enabled: bool = True

    @field_validator("cidr")
    @classmethod
    def valid_cidr(cls, value: str) -> str:
        return validate_cidr(value)


class NtpConfiguration(StrictModel):
    mode: NtpMode = NtpMode.client
    sources: list[NtpSourceInput] = Field(default_factory=list, max_length=64)
    allowed_networks: list[NtpAllowedNetwork] = Field(default_factory=list, max_length=256)
    local_time_when_unsynced: bool = False
    local_stratum: int = Field(default=10, ge=1, le=15)

    @model_validator(mode="after")
    def validate_configuration(self) -> "NtpConfiguration":
        servers = [item.server for item in self.sources]
        if len(servers) != len(set(servers)):
            raise ValueError("duplicate NTP sources are not allowed")
        networks = [item.cidr for item in self.allowed_networks]
        if len(networks) != len(set(networks)):
            raise ValueError("duplicate allowed NTP networks are not allowed")
        if self.mode in {NtpMode.server, NtpMode.client_server} and not any(item.enabled for item in self.allowed_networks):
            raise ValueError("server mode requires at least one explicitly allowed network")
        if self.mode in {NtpMode.client, NtpMode.client_server} and not any(item.enabled for item in self.sources):
            raise ValueError("client mode requires at least one enabled upstream NTP source")
        return self


class NtpConfigurationMutation(StrictModel):
    configuration: NtpConfiguration
    confirm: bool = False


class ServiceActionInput(StrictModel):
    action: Literal["start", "stop", "restart"]
    confirm: bool = False


class NtpTimezoneInput(StrictModel):
    timezone: str = Field(min_length=1, max_length=128)
    confirm: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        if value == "UTC":
            return value
        if value.startswith("/") or ".." in value or "\\" in value or not re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+", value):
            raise ValueError("invalid timezone")
        return value


class NtpTestInput(StrictModel):
    server: str = Field(min_length=1, max_length=253)

    @field_validator("server")
    @classmethod
    def validate_server(cls, value: str) -> str:
        return validate_host(value)


class NtpRestoreInput(StrictModel):
    confirm: bool = False


class NtpFirewallInput(StrictModel):
    confirm: bool = False


class NtpHistoryQuery(StrictModel):
    limit: int = Field(default=200, ge=1, le=2000)
