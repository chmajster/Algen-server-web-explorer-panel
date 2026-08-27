from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProxmoxConnectionInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=2048)
    credential_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    verify_tls: bool = True
    ca_certificate: str = Field(default="", max_length=131072)
    default_ssh_user: str = Field(
        default="algen-ansible",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$",
    )
    project: str = Field(default="", max_length=64)
    environment: str = Field(default="", max_length=64)
    location: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=lambda: ["proxmox"], max_length=50)
    sync_proxmox_tags: bool = True
    sync_lxc: bool = True
    sync_templates: bool = False
    active: bool = True
    auto_sync: bool = False

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Proxmox endpoint must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Proxmox endpoint cannot contain credentials, query or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("Proxmox endpoint must be an origin, for example https://pve.example:8006")
        return value.rstrip("/")

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values: list[str]) -> list[str]:
        if any(not TAG_PATTERN.fullmatch(value) for value in values):
            raise ValueError("invalid host tag")
        return list(dict.fromkeys(values))

    @field_validator("ca_certificate")
    @classmethod
    def valid_ca_certificate(cls, value: str) -> str:
        if value and "BEGIN CERTIFICATE" not in value:
            raise ValueError("CA certificate must be PEM encoded")
        return value


class ProxmoxSyncInput(StrictModel):
    resolve_addresses: bool = True
    disable_missing: bool = True


class ProxmoxPowerInput(StrictModel):
    action: Literal["start", "stop", "shutdown", "reboot"]
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class ProxmoxDeleteInput(StrictModel):
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)
