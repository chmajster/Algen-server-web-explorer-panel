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


class BootstrapOS(StrEnum):
    linux = "linux"
    windows = "windows"


class EnrollmentTokenMode(StrEnum):
    one_time = "one_time"
    permanent = "permanent"


class AgentProtocol(StrEnum):
    https = "https"
    wss = "wss"


class HostKeyPolicy(StrEnum):
    ask = "ask"
    reject = "reject"
    accept_new = "accept_new"


class AgentUpdateChannel(StrEnum):
    stable = "stable"
    beta = "beta"
    pinned = "pinned"


def hostname_template_parts(value: str) -> tuple[str, int, str]:
    value = value.strip()
    runs = list(re.finditer(r"X+", value))
    if len(runs) != 1 or not 1 <= len(runs[0].group()) <= 9:
        raise ValueError("hostname template must contain exactly one run of 1 to 9 uppercase X characters")
    if len(value) > 63 or not re.fullmatch(r"[A-Za-z0-9-]+", value) or value.startswith("-") or value.endswith("-"):
        raise ValueError("hostname template must be a valid hostname label of at most 63 characters")
    match = runs[0]
    return value[:match.start()], len(match.group()), value[match.end():]


def render_hostname(value: str, sequence: int) -> str:
    prefix, width, suffix = hostname_template_parts(value)
    if sequence < 1 or sequence > (10**width) - 1:
        raise OverflowError("hostname sequence is exhausted")
    return f"{prefix}{sequence:0{width}d}{suffix}"


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


def safe_tags(values: list[str]) -> list[str]:
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", item) for item in values):
        raise ValueError("invalid tag")
    return list(dict.fromkeys(values))


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

    _tags = field_validator("tags")(safe_tags)

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
    environment_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
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


class HostsManagerSettingsUpdate(StrictModel):
    hostname_template: str = Field(default="SCL000XXX", min_length=1, max_length=63)
    bootstrap_default_os: BootstrapOS = BootstrapOS.linux
    bootstrap_apply_hostname: bool = True
    default_hostname_pattern_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    agent_default_port: int = Field(default=8443, ge=1, le=65535)
    server_url: str = Field(default="", max_length=2048)
    agent_protocol: AgentProtocol = AgentProtocol.https
    connection_timeout_seconds: int = Field(default=15, ge=1, le=300)
    report_interval_seconds: int = Field(default=300, ge=30, le=86400)
    heartbeat_interval_seconds: int = Field(default=30, ge=5, le=3600)
    max_connection_retries: int = Field(default=10, ge=0, le=1000)
    ssh_default_port: int = Field(default=22, ge=1, le=65535)
    ssh_timeout_seconds: int = Field(default=10, ge=1, le=300)
    ssh_max_concurrency: int = Field(default=10, ge=1, le=128)
    ssh_verify_fingerprint: bool = True
    ssh_new_host_key_policy: HostKeyPolicy = HostKeyPolicy.ask
    agent_min_version: str = Field(default="1.0.0", max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
    agent_auto_update: bool = False
    agent_update_channel: AgentUpdateChannel = AgentUpdateChannel.stable
    agent_repository_url: str = Field(default="", max_length=2048)
    agent_enforce_tls: bool = True
    agent_log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    token_ttl_minutes: int = Field(default=15, ge=1, le=525600)
    allowed_registration_networks: list[str] = Field(
        default_factory=lambda: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        min_length=1,
        max_length=64,
    )
    max_auth_failures: int = Field(default=5, ge=1, le=100)

    @field_validator("hostname_template")
    @classmethod
    def valid_hostname_template(cls, value: str) -> str:
        hostname_template_parts(value)
        return value

    @field_validator("server_url", "agent_repository_url")
    @classmethod
    def secure_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("URL must use HTTPS without embedded credentials")
        return value.rstrip("/")

    @field_validator("allowed_registration_networks")
    @classmethod
    def private_registration_networks(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            network = ipaddress.ip_network(value, strict=False)
            if not network.is_private or network.is_loopback or network.is_multicast:
                raise ValueError("registration networks must be private unicast CIDRs")
            normalized.append(str(network))
        return list(dict.fromkeys(normalized))


class EnvironmentInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    description: str = Field(default="", max_length=1000)
    color: str = Field(default="#187eb1", pattern=r"^#[0-9A-Fa-f]{6}$")
    default_hostname_pattern_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    default_credential_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    default_agent_port: int = Field(default=8443, ge=1, le=65535)
    report_interval_seconds: int = Field(default=300, ge=30, le=86400)
    active: bool = True


class ApmidInput(StrictModel):
    code: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=1000)
    active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]+", normalized):
            raise ValueError("APMID code may contain only letters, digits, underscores, and hyphens")
        return normalized


class HostnamePatternInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    prefix: str = Field(default="", max_length=48, pattern=r"^[A-Za-z0-9-]*$")
    suffix: str = Field(default="", max_length=48, pattern=r"^[A-Za-z0-9-]*$")
    digits: int = Field(default=4, ge=1, le=9)
    start_value: int = Field(default=1, ge=1, le=999_999_999)
    step: int = Field(default=1, ge=1, le=1_000_000)
    description: str = Field(default="", max_length=1000)
    active: bool = True

    @model_validator(mode="after")
    def valid_hostname(self) -> "HostnamePatternInput":
        if len(self.prefix) + len(self.suffix) + self.digits > 63:
            raise ValueError("rendered hostname cannot exceed 63 characters")
        if not self.prefix and not self.suffix:
            raise ValueError("hostname prefix or suffix is required")
        sample = f"{self.prefix}{self.start_value:0{self.digits}d}{self.suffix}"
        if len(str(self.start_value)) > self.digits or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", sample):
            raise ValueError("hostname pattern renders an invalid hostname")
        return self


class HostnamePatternSkipInput(StrictModel):
    count: int = Field(default=1, ge=1, le=1000)
    reason: str = Field(default="", max_length=500)


class EnrollmentTokenInput(StrictModel):
    # Retained for old API clients. New tokens always reserve one exact hostname.
    hostname_pattern: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9*?.-]+$")
    bootstrap_os: BootstrapOS | None = None
    apply_hostname: bool | None = None
    expires_minutes: int | None = Field(default=None, ge=1, le=525600)
    mode: EnrollmentTokenMode = EnrollmentTokenMode.one_time
    apmid_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    environment_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    hostname_pattern_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    bound_address: str = Field(default="", max_length=64)
    agent_port: int | None = Field(default=None, ge=1, le=65535)
    report_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    location: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=50)
    group_ids: list[str] = Field(default_factory=list, max_length=500)
    require_approval: bool = True
    onboard_ansible: bool = False

    _tags = field_validator("tags")(safe_tags)

    @model_validator(mode="after")
    def valid_expiration(self) -> "EnrollmentTokenInput":
        if self.mode == EnrollmentTokenMode.one_time and self.expires_minutes is None:
            raise ValueError("one-time enrollment tokens require expires_minutes")
        if self.mode == EnrollmentTokenMode.permanent:
            self.expires_minutes = None
        return self

    @field_validator("bound_address")
    @classmethod
    def valid_bound_address(cls, value: str) -> str:
        if not value:
            return value
        address = ipaddress.ip_address(value)
        if not address.is_private or address.is_loopback or address.is_multicast:
            raise ValueError("token address binding must be a private unicast address")
        return str(address)


class EnrollmentClaimInput(StrictModel):
    hostname: str = Field(min_length=1, max_length=128)
    fqdn: str = Field(default="", max_length=253)
    address: str = Field(min_length=1, max_length=253)
    os: str = Field(default="", max_length=128)
    architecture: str = Field(default="", max_length=64)
    python: str = Field(default="", max_length=128)
    original_hostname: str = Field(default="", max_length=128)
    system_id: str = Field(default="", max_length=128)
    system_version: str = Field(default="", max_length=256)
    powershell: str = Field(default="", max_length=64)
    installation_id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.:-]*$")
    agent_version: str = Field(default="", max_length=64)

    _address = field_validator("address")(safe_address)


class AgentHeartbeatInput(StrictModel):
    agent_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    agent_version: str = Field(min_length=1, max_length=64)
    uptime_seconds: int = Field(default=0, ge=0)
    current_time: float
    status: str = Field(default="online", pattern=r"^(online|warning|error)$")
    error: str = Field(default="", max_length=2000)


class AgentReportInput(StrictModel):
    agent_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    basic: dict[str, Any] = Field(default_factory=dict)
    hardware: dict[str, Any] = Field(default_factory=dict)
    system: dict[str, Any] = Field(default_factory=dict)
    packages: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def safe_report(self) -> "AgentReportInput":
        report = {
            "basic": self.basic,
            "hardware": self.hardware,
            "system": self.system,
            "packages": self.packages,
        }
        encoded = json.dumps(report, ensure_ascii=False)
        if len(encoded.encode()) > 2 * 1024 * 1024:
            raise ValueError("agent report exceeds 2 MiB")
        no_secrets(report)
        return self


class SshOnboardingProbeInput(StrictModel):
    address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    credential_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    use_sudo: bool = True
    accepted_fingerprint: str = Field(
        default="",
        max_length=256,
        pattern=r"^(?:|SHA256:[A-Za-z0-9+/=]{16,})$",
    )

    _address = field_validator("address")(safe_address)


class SshOnboardingInstallInput(SshOnboardingProbeInput):
    apmid_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    environment_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    hostname_pattern_id: str | None = Field(default=None, max_length=64, pattern=ID_PATTERN)
    agent_port: int = Field(default=8443, ge=1, le=65535)
    report_interval_seconds: int = Field(default=300, ge=30, le=86400)
    apply_hostname: bool = True
    confirm: bool = False


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

    _tags = field_validator("tags")(safe_tags)


class BackupInput(StrictModel):
    description: str = Field(default="", max_length=500)
    include_credentials: bool = False
    include_repositories: bool = False
    confirm: bool = False


class RestoreInput(StrictModel):
    checksum: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)
