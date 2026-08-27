from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")


class DcstDirection(StrEnum):
    IN = "IN"
    OUT = "OUT"


class DcstAction(StrEnum):
    ACCEPT = "ACCEPT"
    DROP = "DROP"
    REJECT = "REJECT"


class DcstEndpointType(StrEnum):
    TAG = "tag"
    IPSET = "ipset"
    IP = "ip"
    CIDR = "cidr"
    ANY = "any"
    APMID = "apmid"


class DcstProtocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"
    TCP_UDP = "tcp+udp"
    ICMP = "icmp"


class PortInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    protocol: DcstProtocol
    port_from: int | None = Field(default=None, ge=1, le=65535)
    port_to: int | None = Field(default=None, ge=1, le=65535)
    description: str = Field(default="", max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not _NAME.fullmatch(value):
            raise ValueError("invalid port object name")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "PortInput":
        if self.protocol == DcstProtocol.ICMP:
            if self.port_from is not None or self.port_to is not None:
                raise ValueError("ICMP does not use ports")
            return self
        if self.port_from is None:
            raise ValueError("port_from is required")
        if self.port_to is None:
            self.port_to = self.port_from
        if self.port_to < self.port_from:
            raise ValueError("port_to must be greater than or equal to port_from")
        return self


class IPSetInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    entries: list[str] = Field(default_factory=list, max_length=4096)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not _NAME.fullmatch(value):
            raise ValueError("invalid IPSet name")
        return value

    @field_validator("entries")
    @classmethod
    def validate_entries(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values:
            value = raw.strip()
            try:
                if "/" in value:
                    normalized = str(ipaddress.ip_network(value, strict=False))
                else:
                    address = ipaddress.ip_address(value)
                    normalized = f"{address}/{32 if address.version == 4 else 128}"
            except ValueError as error:
                raise ValueError(f"invalid IP/CIDR: {value}") from error
            if normalized not in result:
                result.append(normalized)
        return result


class ServiceInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    direction: DcstDirection
    action: DcstAction = DcstAction.ACCEPT
    source_type: DcstEndpointType
    source_value: str = Field(default="", max_length=256)
    destination_type: DcstEndpointType
    destination_value: str = Field(default="", max_length=256)
    port_ids: list[str] = Field(default_factory=list, max_length=128)
    enabled: bool = True
    logging: bool = False
    comment: str = Field(default="", max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not _NAME.fullmatch(value):
            raise ValueError("invalid service name")
        return value

    @model_validator(mode="after")
    def validate_endpoints(self) -> "ServiceInput":
        for endpoint_type, raw in ((self.source_type, self.source_value), (self.destination_type, self.destination_value)):
            value = raw.strip()
            if endpoint_type == DcstEndpointType.ANY:
                continue
            if not value:
                raise ValueError("source/destination value is required")
            if endpoint_type == DcstEndpointType.IP:
                ipaddress.ip_address(value)
            elif endpoint_type == DcstEndpointType.CIDR:
                ipaddress.ip_network(value, strict=False)
        return self


class BulkServiceInput(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class SyncInput(BaseModel):
    dry_run: bool = False
    force: bool = False
    confirm_high_risk: bool = False


class DangerousConfirmInput(BaseModel):
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=256)


class TagSyncInput(BaseModel):
    apply: bool = True


ServiceState = Literal["ACTIVE", "BLOCKED", "DISABLED", "PENDING", "ERROR"]
SyncState = Literal["SYNCED", "PENDING", "DRIFT", "ERROR"]
