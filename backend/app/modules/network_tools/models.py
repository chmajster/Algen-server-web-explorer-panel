from __future__ import annotations

import ipaddress
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$", re.IGNORECASE)


def validated_host(value: str) -> str:
    candidate = value.strip().rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    try:
        ascii_name = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("invalid hostname") from error
    if len(ascii_name) > 253 or not HOST_RE.fullmatch(ascii_name) or any(len(label) > 63 or not label for label in ascii_name.split(".")):
        raise ValueError("invalid hostname")
    return ascii_name


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=253)

    @field_validator("target")
    @classmethod
    def target_is_safe(cls, value: str) -> str:
        return validated_host(value)


class PortTestRequest(TargetRequest):
    port: int = Field(ge=1, le=65535)


class DnsLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hostname: str = Field(min_length=1, max_length=253)
    record_type: Literal["A", "AAAA", "CNAME", "MX", "TXT", "NS", "PTR"] = "A"
    server: str = Field(default="", max_length=64)

    @field_validator("hostname")
    @classmethod
    def hostname_is_safe(cls, value: str) -> str:
        if value.strip().endswith(".in-addr.arpa") or value.strip().endswith(".ip6.arpa"):
            return value.strip().lower()
        return validated_host(value)

    @field_validator("server")
    @classmethod
    def server_is_ip(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            return ""
        return str(ipaddress.ip_address(candidate))


class ReverseDnsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str

    @field_validator("address")
    @classmethod
    def address_is_ip(cls, value: str) -> str:
        return str(ipaddress.ip_address(value.strip()))


class HttpTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("URL must use http/https and cannot contain credentials")
        validated_host(parsed.hostname)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("invalid URL port")
        return value.strip()
