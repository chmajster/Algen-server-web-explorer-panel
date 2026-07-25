from __future__ import annotations

import ipaddress
import json
import re
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
SECRET_MARKERS = ("password", "passwd", "private_key", "token", "secret", "vault", "api_key")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConnectionType(StrEnum):
    ssh = "ssh"
    paramiko = "paramiko"


class CredentialType(StrEnum):
    ssh_private_key = "ssh_private_key"
    ssh_password = "ssh_password"
    become_password = "become_password"
    redfish = "redfish"
    ipmi = "ipmi"
    proxmox_api = "proxmox_api"
    wol = "wol"
    git_private_key = "git_private_key"


class PowerProvider(StrEnum):
    none = "none"
    wol = "wol"
    redfish = "redfish"
    ipmi = "ipmi"
    proxmox = "proxmox"


def safe_address(value: str) -> str:
    value = value.strip().rstrip(".")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        try:
            value = value.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("invalid host address") from error
        if value.casefold() == "localhost" or not re.fullmatch(
            r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
            value,
        ):
            raise ValueError("invalid host address")
        return value
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        raise ValueError("loopback, unspecified and multicast targets are forbidden")
    return value


def no_secrets(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode()) > 128 * 1024:
        raise ValueError("JSON data exceeds 128 KiB")

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if any(marker in str(key).casefold() for marker in SECRET_MARKERS):
                    raise ValueError("secrets must be stored as credentials")
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return value


class HostInput(StrictModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")
    hostname: str = Field(default="", max_length=128)
    fqdn: str = Field(default="", max_length=253)
    address: str = Field(min_length=1, max_length=253)
    management_address: str = Field(default="", max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    connection_type: ConnectionType = ConnectionType.ssh
    ssh_user: str = Field(default="algen-ansible", min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    credential_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    python_interpreter: str = Field(default="auto_silent", max_length=255)
    environment: str = Field(default="", max_length=64)
    location: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    variables: dict[str, Any] = Field(default_factory=dict)
    group_ids: list[str] = Field(default_factory=list, max_length=500)
    active: bool = True
    approved: bool = False
    power_profile_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)

    _address = field_validator("address")(safe_address)

    @field_validator("management_address")
    @classmethod
    def safe_management_address(cls, value: str) -> str:
        return safe_address(value) if value else ""

    @field_validator("hostname", "fqdn")
    @classmethod
    def safe_dns_name(cls, value: str) -> str:
        if value:
            safe_address(value)
        return value.rstrip(".")

    @field_validator("python_interpreter")
    @classmethod
    def safe_interpreter(cls, value: str) -> str:
        if value in {"auto", "auto_silent", "/usr/bin/python3", "/usr/local/bin/python3"}:
            return value
        raise ValueError("unsupported Python interpreter")

    @field_validator("tags")
    @classmethod
    def safe_tags(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", item) for item in values):
            raise ValueError("invalid tag")
        return list(dict.fromkeys(values))

    _variables = field_validator("variables")(no_secrets)


class GroupInput(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    description: str = Field(default="", max_length=500)
    parent_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    variables: dict[str, Any] = Field(default_factory=dict)
    host_ids: list[str] = Field(default_factory=list, max_length=5000)
    active: bool = True

    _variables = field_validator("variables")(no_secrets)


class CredentialInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    type: CredentialType
    username: str = Field(default="", max_length=128)
    secret: str = Field(default="", max_length=131072)
    passphrase: str = Field(default="", max_length=4096)
    description: str = Field(default="", max_length=500)
    confirm: bool = False

    @model_validator(mode="after")
    def valid_secret(self) -> "CredentialInput":
        if self.type != CredentialType.wol and not self.secret:
            raise ValueError("credential secret is required")
        if self.type in {CredentialType.ssh_private_key, CredentialType.git_private_key} and "PRIVATE KEY-----" not in self.secret:
            raise ValueError("private-key credential is invalid")
        if self.type not in {CredentialType.ssh_private_key, CredentialType.git_private_key} and ("\n" in self.secret or "\r" in self.secret):
            raise ValueError("credential secret must be a single line")
        return self


class EnrollmentTokenInput(StrictModel):
    hostname_pattern: str = Field(default="node-*", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9*?.-]+$")
    expires_minutes: int = Field(default=15, ge=1, le=60)
    port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="algen-ansible", max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    credential_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    environment: str = Field(default="", max_length=64)
    location: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=50)
    group_ids: list[str] = Field(default_factory=list, max_length=500)
    require_approval: bool = True
    onboard_ansible: bool = False

    _tags = field_validator("tags")(HostInput.safe_tags.__func__)


class EnrollmentClaimInput(StrictModel):
    hostname: str = Field(min_length=1, max_length=128)
    fqdn: str = Field(default="", max_length=253)
    address: str = Field(min_length=1, max_length=253)
    os: str = Field(default="", max_length=128)
    architecture: str = Field(default="", max_length=64)
    python: str = Field(default="", max_length=128)

    _address = field_validator("address")(safe_address)


class ConfirmationInput(StrictModel):
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class FingerprintAcceptInput(StrictModel):
    fingerprint: str = Field(min_length=20, max_length=256, pattern=r"^SHA256:[A-Za-z0-9+/=]{16,}$")
    public_key: str = Field(min_length=32, max_length=16384)
    replace: bool = False
    confirm: bool = False


class InventoryInput(StrictModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    format: str = Field(default="yaml", pattern=r"^(yaml|json|ini|ansible_yaml|ansible_ini)$")
    confirm: bool = False


class RepositoryInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    url: str = Field(min_length=1, max_length=2048)
    revision: str = Field(default="main", min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_./-]+$")
    credential_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    host_ids: list[str] = Field(default_factory=list, max_length=5000)
    group_ids: list[str] = Field(default_factory=list, max_length=500)
    sync_before_use: bool = True
    active: bool = True

    @field_validator("revision")
    @classmethod
    def safe_revision(cls, value: str) -> str:
        if ".." in value or value.startswith(("/", "-")):
            raise ValueError("unsafe Git revision")
        return value

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        scp = re.fullmatch(r"git@[A-Za-z0-9.-]+:[A-Za-z0-9_./~-]+", value)
        if scp:
            return value
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Git URL must use HTTPS or SSH without embedded secrets")
        if parsed.username and (parsed.scheme != "ssh" or parsed.username != "git"):
            raise ValueError("credentials in Git URLs are forbidden")
        return value


class PowerProfileInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    provider: PowerProvider
    credential_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    address: str = Field(default="", max_length=253)
    mac_address: str = Field(default="", max_length=17, pattern=r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$|^$")
    broadcast_address: str = Field(default="", max_length=64)
    node: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.-]*$")
    resource_id: int | None = Field(default=None, ge=1, le=999999999)
    verify_tls: bool = True
    ca_certificate: str = Field(default="", max_length=131072)
    active: bool = True

    @model_validator(mode="after")
    def requirements(self) -> "PowerProfileInput":
        if self.address:
            self.address = safe_address(self.address)
        if self.broadcast_address:
            address = ipaddress.ip_address(self.broadcast_address)
            if not address.is_private or address.is_loopback or address.is_multicast:
                raise ValueError("Wake-on-LAN broadcast must be a private unicast/broadcast address")
        if self.provider == PowerProvider.wol and not self.mac_address:
            raise ValueError("Wake-on-LAN requires a MAC address")
        if self.provider in {PowerProvider.redfish, PowerProvider.ipmi, PowerProvider.proxmox} and (not self.address or not self.credential_id):
            raise ValueError("provider address and credential are required")
        return self


class PowerActionInput(StrictModel):
    action: str = Field(pattern=r"^(refresh|on|off|shutdown|reboot)$")
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class CapabilityActionInput(StrictModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)

    _parameters = field_validator("parameters")(no_secrets)


class ScanInput(StrictModel):
    cidr: str | None = Field(default=None, max_length=64)
    start_address: str | None = Field(default=None, max_length=64)
    end_address: str | None = Field(default=None, max_length=64)
    port: int = Field(default=22, ge=1, le=65535)
    timeout_seconds: float = Field(default=2, ge=.2, le=15)
    concurrency: int = Field(default=32, ge=1, le=128)
    reverse_dns: bool = False

    @model_validator(mode="after")
    def safe_range(self) -> "ScanInput":
        if bool(self.cidr) == bool(self.start_address or self.end_address):
            raise ValueError("provide CIDR or both range endpoints")
        if self.cidr:
            network = ipaddress.ip_network(self.cidr, strict=False)
            if not network.is_private or network.num_addresses > 65536:
                raise ValueError("discovery is limited to private networks of at most 65536 addresses")
        else:
            start, end = ipaddress.ip_address(self.start_address or ""), ipaddress.ip_address(self.end_address or "")
            if not start.is_private or not end.is_private or start.version != end.version or int(end) - int(start) > 65535:
                raise ValueError("invalid or non-private discovery range")
        return self


class ScanImportInput(StrictModel):
    host_ids: list[str] = Field(min_length=1, max_length=5000)
    group_ids: list[str] = Field(default_factory=list, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=50)
    confirm: bool = False

    _tags = field_validator("tags")(HostInput.safe_tags.__func__)


class BackupInput(StrictModel):
    description: str = Field(default="", max_length=500)
    include_credentials: bool = False
    include_repositories: bool = False
    confirm: bool = False


class RestoreInput(StrictModel):
    checksum: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)
