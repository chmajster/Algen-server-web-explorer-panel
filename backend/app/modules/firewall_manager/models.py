from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FirewallBackend(StrEnum):
    ufw = "ufw"
    firewalld = "firewalld"
    nftables = "nftables"
    unavailable = "unavailable"


class FirewallRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["allow", "drop", "reject"] = "allow"
    direction: Literal["in", "out"] = "in"
    protocol: Literal["any", "tcp", "udp"] = "tcp"
    port: str = Field(default="", max_length=32)
    source: str = Field(default="any", max_length=64)
    destination: str = Field(default="any", max_length=64)
    interface: str = Field(default="", max_length=32)
    comment: str = Field(default="", max_length=120)
    family: Literal["any", "ipv4", "ipv6"] = "any"

    @field_validator("port")
    @classmethod
    def valid_port(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        match = re.fullmatch(r"(\d{1,5})(?:(?:-|:)(\d{1,5}))?", value)
        if not match:
            raise ValueError("port must be a single port or range")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if not 1 <= start <= end <= 65535:
            raise ValueError("port is outside 1-65535")
        return str(start) if start == end else f"{start}-{end}"

    @field_validator("source", "destination")
    @classmethod
    def valid_network(cls, value: str) -> str:
        value = value.strip().lower()
        if value in {"", "any", "0.0.0.0/0", "::/0"}:
            return "any"
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as error:
            raise ValueError("address must be IPv4/IPv6 or CIDR") from error
        return str(network)

    @field_validator("interface")
    @classmethod
    def valid_interface(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,32}", value):
            raise ValueError("invalid interface")
        return value

    @field_validator("comment")
    @classmethod
    def valid_comment(cls, value: str) -> str:
        value = " ".join(value.split())
        if any(ord(character) < 32 for character in value):
            raise ValueError("comment contains control characters")
        return value[:120]

    @model_validator(mode="after")
    def port_protocol(self) -> "FirewallRuleInput":
        if self.port and self.protocol == "any":
            raise ValueError("a port requires tcp or udp protocol")
        return self


class FirewallRule(BaseModel):
    id: str
    backend: FirewallBackend
    action: str
    direction: str = "in"
    protocol: str = "any"
    port: str = ""
    source: str = "any"
    destination: str = "any"
    interface: str = ""
    comment: str = ""
    family: str = "any"
    enabled: bool = True
    editable: bool = True
    raw: str = ""


class FirewallMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule: FirewallRuleInput | None = None
    pam_password: str = Field(min_length=1, max_length=1024)
    confirmation: str = Field(min_length=1, max_length=128)
    acknowledge_lockout: bool = False


class FirewallActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pam_password: str = Field(min_length=1, max_length=1024)
    confirmation: str = Field(min_length=1, max_length=128)
    acknowledge_lockout: bool = False


class FirewallBackupRequest(FirewallActionRequest):
    description: str = Field(default="", max_length=200)


class FirewallImportRequest(FirewallActionRequest):
    configuration: dict = Field(default_factory=dict)
