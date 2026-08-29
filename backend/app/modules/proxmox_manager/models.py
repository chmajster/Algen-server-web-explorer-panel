from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .endpoint import normalize_endpoint_input


ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
RESOURCE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
SNAPSHOT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
NODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
STORAGE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
DISK_PATTERN = r"^(?:ide|sata|scsi|virtio)\d+$"


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
    sync_interval_seconds: int = Field(default=300, ge=60, le=86400)

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        return normalize_endpoint_input(value)

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


class ProxmoxSnapshotCreateInput(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=SNAPSHOT_PATTERN)
    description: str = Field(default="", max_length=1000)
    include_ram: bool = False


class ProxmoxDestructiveInput(StrictModel):
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class ProxmoxCloneInput(StrictModel):
    new_vmid: int = Field(ge=100, le=999_999_999)
    name: str = Field(min_length=1, max_length=128, pattern=RESOURCE_NAME_PATTERN)
    full: bool = True
    target_node: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.-]*$")
    target_storage: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.-]*$")
    pool: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.-]*$")
    sync_to_host_registry: bool = True


class ProxmoxMigrationInput(StrictModel):
    target_node: str = Field(min_length=1, max_length=128, pattern=NODE_PATTERN)
    target_storage: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.-]*$")
    online: bool = True
    with_local_disks: bool = True
    migration_network: str = Field(default="", max_length=128)
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class ProxmoxHardwareUpdateInput(StrictModel):
    cores: int | None = Field(default=None, ge=1, le=256)
    sockets: int | None = Field(default=None, ge=1, le=16)
    memory_mb: int | None = Field(default=None, ge=128, le=4_194_304)
    balloon_mb: int | None = Field(default=None, ge=0, le=4_194_304)
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def has_change(self) -> "ProxmoxHardwareUpdateInput":
        if all(value is None for value in (self.cores, self.sockets, self.memory_mb, self.balloon_mb)):
            raise ValueError("at least one hardware value is required")
        return self


class ProxmoxDiskResizeInput(StrictModel):
    disk: str = Field(min_length=4, max_length=16, pattern=DISK_PATTERN)
    new_size_gb: int = Field(ge=1, le=1_048_576)
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class ProxmoxCreateVmInput(StrictModel):
    vmid: int = Field(ge=100, le=999_999_999)
    name: str = Field(min_length=1, max_length=128, pattern=RESOURCE_NAME_PATTERN)
    node: str = Field(min_length=1, max_length=128, pattern=NODE_PATTERN)
    storage: str = Field(min_length=1, max_length=128, pattern=STORAGE_PATTERN)
    disk_size_gb: int = Field(default=32, ge=1, le=1_048_576)
    cores: int = Field(default=2, ge=1, le=256)
    sockets: int = Field(default=1, ge=1, le=16)
    memory_mb: int = Field(default=2048, ge=128, le=4_194_304)
    bridge: str = Field(default="vmbr0", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    vlan: int | None = Field(default=None, ge=1, le=4094)
    ipv4_mode: Literal["dhcp", "static"] = "dhcp"
    ipv4_address: str = Field(default="", max_length=64)
    gateway: str = Field(default="", max_length=64)
    dns: str = Field(default="", max_length=255)
    cloud_init_user: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.-]*$")
    ssh_public_key: str = Field(default="", max_length=16384)
    start_after_create: bool = False
    sync_to_host_registry: bool = True

    @model_validator(mode="after")
    def validate_ip_settings(self) -> "ProxmoxCreateVmInput":
        if self.ipv4_mode == "static" and (not self.ipv4_address or not self.gateway):
            raise ValueError("static IPv4 requires address and gateway")
        if self.ssh_public_key and not self.ssh_public_key.startswith(("ssh-", "ecdsa-", "sk-ssh-")):
            raise ValueError("cloud-init SSH public key has an unsupported format")
        return self
