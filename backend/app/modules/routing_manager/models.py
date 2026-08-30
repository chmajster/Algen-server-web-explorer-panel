from __future__ import annotations

import ipaddress
from pydantic import BaseModel, Field, field_validator, model_validator


class RouteInput(BaseModel):
    destination: str = Field(min_length=1, max_length=80)
    gateway: str = Field(default="", max_length=64)
    interface: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.:@-]*$")
    metric: int | None = Field(default=None, ge=0, le=4_294_967_295)
    table: str = Field(default="main", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    source: str = Field(default="", max_length=64)
    persistent: bool = False
    rollback_seconds: int = Field(default=60, ge=15, le=600)
    confirm: bool = False

    @field_validator("destination")
    @classmethod
    def destination_network(cls, value: str) -> str:
        if value == "default":
            return value
        return str(ipaddress.ip_network(value, strict=False))

    @field_validator("gateway", "source")
    @classmethod
    def ip_value(cls, value: str) -> str:
        return str(ipaddress.ip_address(value)) if value else ""

    @model_validator(mode="after")
    def same_family(self):
        if self.destination == "default":
            return self
        network = ipaddress.ip_network(self.destination)
        for candidate in (self.gateway, self.source):
            if candidate and ipaddress.ip_address(candidate).version != network.version:
                raise ValueError("route addresses must use one IP family")
        return self


class PolicyRuleInput(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=4_294_967_295)
    source: str = Field(default="all", max_length=80)
    destination: str = Field(default="all", max_length=80)
    fwmark: str = Field(default="", max_length=64, pattern=r"^[A-Fa-f0-9x/]*$")
    input_interface: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.:@-]*$")
    output_interface: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.:@-]*$")
    table: str = Field(default="main", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    family: int = 4
    confirm: bool = False

    @field_validator("source", "destination")
    @classmethod
    def network_or_all(cls, value: str) -> str:
        if value == "all":
            return value
        return str(ipaddress.ip_network(value, strict=False))

    @field_validator("family")
    @classmethod
    def valid_family(cls, value: int) -> int:
        if value not in {4, 6}:
            raise ValueError("family must be 4 or 6")
        return value


class DiagnosticInput(BaseModel):
    target: str = Field(min_length=1, max_length=253)


class TransactionConfirmInput(BaseModel):
    confirm: bool = False
