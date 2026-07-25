from __future__ import annotations

import ipaddress
import re
from typing import Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()+,;=:@%/-]{0,1023}$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
REGISTRY_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::[1-9][0-9]{0,4})?$", re.ASCII)
VOLUME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$")
REPOSITORY_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def _identifier(value: str, label: str = "identifier") -> str:
    value = value.strip()
    if not CONTAINER_RE.fullmatch(value) or value.startswith("-"):
        raise ValueError(f"invalid {label}")
    return value


def _image(value: str) -> str:
    value = value.strip()
    if not IMAGE_RE.fullmatch(value) or value.startswith("-"):
        raise ValueError("invalid image reference")
    without_digest = value.split("@", 1)[0]
    last_segment = without_digest.rsplit("/", 1)[-1]
    if ":" in last_segment:
        _name, tag = last_segment.rsplit(":", 1)
        validate_tag(tag)
    return value


def _volume_name(value: str) -> str:
    value = value.strip()
    if not VOLUME_RE.fullmatch(value):
        raise ValueError("volume name must contain 2-128 letters, numbers, dots, dashes or underscores")
    return value


def _environment(value: dict[str, str], message: str) -> dict[str, str]:
    if any(
        not ENV_RE.fullmatch(key)
        or len(item.encode("utf-8")) > 8192
        or "\x00" in item
        or "\r" in item
        or "\n" in item
        for key, item in value.items()
    ):
        raise ValueError(message)
    return value


def _labels(value: dict[str, str]) -> dict[str, str]:
    if any(
        not LABEL_RE.fullmatch(key)
        or len(item) > 512
        or any(character in item for character in "\x00\r\n")
        for key, item in value.items()
    ):
        raise ValueError("invalid label")
    return value


class DockerModel(BaseModel):
    # Values such as passwords and Compose YAML must be preserved byte-for-byte.
    # Identifiers are normalized explicitly by their field validators.
    model_config = ConfigDict(extra="forbid", strict=True)


class PortMapping(DockerModel):
    host_ip: str | None = None
    published: int = Field(ge=1, le=65535)
    target: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"

    @field_validator("host_ip")
    @classmethod
    def valid_host_ip(cls, value: str | None) -> str | None:
        if not value:
            return None
        return str(ipaddress.ip_address(value))


class MountSpec(DockerModel):
    type: Literal["volume", "bind", "tmpfs"]
    source: str = Field(default="", max_length=1024)
    target: str = Field(max_length=1024)
    read_only: bool = False
    tmpfs_size_mb: int | None = Field(default=None, ge=1, le=65536)

    @model_validator(mode="after")
    def valid_mount(self) -> "MountSpec":
        if not PATH_RE.fullmatch(self.target) or self.target == "/":
            raise ValueError("mount target must be an absolute container path")
        if self.type == "tmpfs":
            if self.source:
                raise ValueError("tmpfs does not accept a source")
        elif self.type == "volume":
            self.source = _identifier(self.source, "volume name")
        elif not PATH_RE.fullmatch(self.source):
            raise ValueError("bind source must be an absolute path")
        if self.source == "/var/run/docker.sock" or self.target == "/var/run/docker.sock":
            raise ValueError("mounting the Docker socket is forbidden")
        return self


class ResourceLimits(DockerModel):
    cpus: float | None = Field(default=None, ge=0.1, le=128)
    memory_mb: int | None = Field(default=None, ge=16, le=1_048_576)
    memory_swap_mb: int | None = Field(default=None, ge=16, le=2_097_152)
    pids: int | None = Field(default=None, ge=16, le=4_194_304)

    @model_validator(mode="after")
    def valid_swap(self) -> "ResourceLimits":
        if self.memory_swap_mb is not None and self.memory_mb is None:
            raise ValueError("memory limit is required when swap is limited")
        if self.memory_swap_mb is not None and self.memory_mb is not None and self.memory_swap_mb < self.memory_mb:
            raise ValueError("memory plus swap cannot be lower than memory")
        return self


class HealthcheckSpec(DockerModel):
    type: Literal["none", "http", "tcp"] = "none"
    port: int | None = Field(default=None, ge=1, le=65535)
    path: str = Field(default="/", max_length=512, pattern=r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*$")
    interval_seconds: int = Field(default=30, ge=5, le=3600)
    timeout_seconds: int = Field(default=5, ge=1, le=300)
    retries: int = Field(default=3, ge=1, le=20)
    start_period_seconds: int = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def port_required(self) -> "HealthcheckSpec":
        if self.type != "none" and self.port is None:
            raise ValueError("healthcheck port is required")
        return self


class ContainerCreateRequest(DockerModel):
    name: str
    image: str
    pull_policy: Literal["missing", "always", "never"] = "missing"
    environment: dict[str, str] = Field(default_factory=dict, max_length=200)
    secret_environment: dict[str, str] = Field(default_factory=dict, max_length=100)
    ports: list[PortMapping] = Field(default_factory=list, max_length=100)
    mounts: list[MountSpec] = Field(default_factory=list, max_length=100)
    network: str = "bridge"
    network_aliases: list[str] = Field(default_factory=list, max_length=20)
    restart_policy: Literal["no", "always", "unless-stopped", "on-failure"] = "unless-stopped"
    hostname: str | None = None
    working_dir: str | None = None
    user: str | None = None
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    healthcheck: HealthcheckSpec = Field(default_factory=HealthcheckSpec)
    labels: dict[str, str] = Field(default_factory=dict, max_length=100)
    read_only: bool = False
    init: bool = True
    auto_start: bool = True
    confirmation: str = ""

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _identifier(value, "container name")

    @field_validator("image")
    @classmethod
    def valid_image(cls, value: str) -> str:
        return _image(value)

    @field_validator("network")
    @classmethod
    def valid_network(cls, value: str) -> str:
        value = _identifier(value, "network")
        if value in {"host", "none"}:
            raise ValueError("host and none network modes are forbidden")
        return value

    @field_validator("network_aliases")
    @classmethod
    def valid_network_aliases(cls, values: list[str]) -> list[str]:
        aliases = []
        for value in values:
            normalized = value.strip().lower()
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?", normalized) or ".." in normalized:
                raise ValueError("invalid network alias")
            aliases.append(normalized)
        return list(dict.fromkeys(aliases))

    @field_validator("hostname")
    @classmethod
    def valid_hostname(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", normalized):
            raise ValueError("invalid hostname")
        return normalized

    @field_validator("working_dir")
    @classmethod
    def valid_working_dir(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not PATH_RE.fullmatch(value) or ".." in value.split("/"):
            raise ValueError("working directory must be an absolute container path")
        return value

    @field_validator("user")
    @classmethod
    def valid_user(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not re.fullmatch(r"[0-9]{1,10}(?::[0-9]{1,10})?", value):
            raise ValueError("container user must be a numeric UID or UID:GID")
        return value

    @field_validator("environment", "secret_environment")
    @classmethod
    def valid_environment(cls, value: dict[str, str]) -> dict[str, str]:
        return _environment(value, "invalid environment variable")

    @field_validator("labels")
    @classmethod
    def valid_labels(cls, value: dict[str, str]) -> dict[str, str]:
        return _labels(value)

    @model_validator(mode="after")
    def distinct_ports_and_mounts(self) -> "ContainerCreateRequest":
        if len({(item.host_ip, item.published, item.protocol) for item in self.ports}) != len(self.ports):
            raise ValueError("published ports must be unique")
        if len({item.target for item in self.mounts}) != len(self.mounts):
            raise ValueError("mount targets must be unique")
        if set(self.environment) & set(self.secret_environment):
            raise ValueError("a variable cannot be both public and secret")
        if self.network_aliases and self.network == "bridge":
            raise ValueError("network aliases require a user-defined bridge network")
        return self


class ContainerActionRequest(DockerModel):
    action: Literal["start", "stop", "restart", "pause", "unpause", "kill", "rename", "remove", "duplicate", "recreate", "check_update", "update"]
    timeout: int = Field(default=10, ge=1, le=300)
    signal: Literal["KILL", "TERM", "HUP", "INT", "QUIT", "USR1", "USR2"] = "KILL"
    force: bool = False
    new_name: str | None = None
    image: str | None = None
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("new_name")
    @classmethod
    def valid_new_name(cls, value: str | None) -> str | None:
        return _identifier(value, "container name") if value else None

    @field_validator("image")
    @classmethod
    def valid_image(cls, value: str | None) -> str | None:
        return _image(value) if value else None

    @model_validator(mode="after")
    def required_fields(self) -> "ContainerActionRequest":
        if self.action in {"rename", "duplicate"} and not self.new_name:
            raise ValueError("new container name is required")
        return self


class ContainerSettingsRequest(DockerModel):
    name: str
    resource_limits_enabled: bool = False
    cpu_priority: Literal["low", "medium", "high"] = "medium"
    memory_mb: int | None = Field(default=None, ge=16, le=1_048_576)
    auto_restart: bool = True
    portal_enabled: bool = False
    portal_port: int | None = Field(default=None, ge=1, le=65535)
    portal_protocol: Literal["http", "https"] = "http"
    confirmation: str = ""

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _identifier(value, "container name")

    @model_validator(mode="after")
    def required_settings(self) -> "ContainerSettingsRequest":
        if self.resource_limits_enabled and self.memory_mb is None:
            raise ValueError("memory limit is required when resource limits are enabled")
        if self.portal_enabled and self.portal_port is None:
            raise ValueError("a published container port is required for the web portal")
        return self


class ImageActionRequest(DockerModel):
    action: Literal["pull", "update", "remove", "prune", "save"]
    image: str | None = None
    platform: Literal["linux/amd64", "linux/arm64", "linux/arm/v7"] | None = None
    force: bool = False
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("image")
    @classmethod
    def valid_image(cls, value: str | None) -> str | None:
        return _image(value) if value else None

    @model_validator(mode="after")
    def image_required(self) -> "ImageActionRequest":
        if self.action != "prune" and not self.image:
            raise ValueError("image is required")
        return self


class RegistryRequest(DockerModel):
    name: str
    provider: Literal["docker_hub", "ghcr", "gitlab", "quay", "custom"] = "custom"
    server: str
    username: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=4096)
    tls: bool = True
    ca_certificate: str | None = Field(default=None, max_length=128 * 1024)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _identifier(value, "registry name")

    @field_validator("server")
    @classmethod
    def valid_server(cls, value: str) -> str:
        value = value.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not REGISTRY_RE.fullmatch(value) or ".." in value:
            raise ValueError("invalid registry server")
        return value

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character in value for character in "\x00\r\n"):
            raise ValueError("invalid registry username")
        return value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in "\x00\r\n"):
            raise ValueError("invalid registry credential")
        return value or None

    @field_validator("ca_certificate")
    @classmethod
    def valid_ca_certificate(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.replace("\r\n", "\n")
        if "\x00" in normalized or not normalized.startswith("-----BEGIN CERTIFICATE-----\n") or not normalized.rstrip().endswith("-----END CERTIFICATE-----"):
            raise ValueError("custom CA must be a PEM certificate")
        return normalized

    @model_validator(mode="after")
    def ca_requires_tls(self) -> "RegistryRequest":
        if self.ca_certificate and not self.tls:
            raise ValueError("custom CA requires TLS")
        return self


class RegistrySource(DockerModel):
    id: str
    name: str
    provider: Literal["docker_hub", "ghcr", "gitlab", "quay", "custom"]
    server: str
    built_in: bool = False
    public_access: bool = False


class RegistryCatalogImage(DockerModel):
    registry_id: str
    registry: str
    provider: Literal["docker_hub", "ghcr", "gitlab", "quay", "custom"]
    repository: str
    pull_reference: str
    description: str = ""
    stars: int = Field(default=0, ge=0)
    official: bool = False
    automated: bool | None = None


class RegistryPagination(DockerModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
    has_next: bool = False
    truncated: bool = False


class RegistryCatalogResponse(DockerModel):
    items: list[RegistryCatalogImage]
    pagination: RegistryPagination
    source: RegistrySource


class RegistryTagsResponse(DockerModel):
    repository: str
    pull_reference: str
    tags: list[str]
    pagination: RegistryPagination
    source: RegistrySource


def validate_repository(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 255 or not REPOSITORY_RE.fullmatch(normalized):
        raise ValueError("invalid repository name")
    return normalized


def validate_tag(value: str) -> str:
    normalized = value.strip()
    if not TAG_RE.fullmatch(normalized):
        raise ValueError("invalid image tag")
    return normalized


class VolumeCreateRequest(DockerModel):
    name: str
    labels: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _volume_name(value)

    @field_validator("labels")
    @classmethod
    def valid_labels(cls, value: dict[str, str]) -> dict[str, str]:
        return _labels(value)


class VolumeActionRequest(DockerModel):
    action: Literal["remove", "prune", "backup", "restore", "clone"]
    target_name: str | None = None
    backup_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    force: bool = False
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("target_name")
    @classmethod
    def valid_target_name(cls, value: str | None) -> str | None:
        return _volume_name(value) if value else None

    @model_validator(mode="after")
    def required_action_fields(self) -> "VolumeActionRequest":
        if self.action == "clone" and not self.target_name:
            raise ValueError("clone target name is required")
        if self.action == "restore" and not self.backup_id:
            raise ValueError("volume backup identifier is required")
        return self


class NetworkCreateRequest(DockerModel):
    name: str
    driver: Literal["bridge"] = "bridge"
    ipv4_mode: Literal["auto", "manual"] = "auto"
    ipv4_subnet: str | None = None
    ipv4_ip_range: str | None = None
    ipv4_gateway: str | None = None
    ipv6_mode: Literal["none", "manual"] = "none"
    ipv6_subnet: str | None = None
    ipv6_ip_range: str | None = None
    ipv6_gateway: str | None = None
    internal: bool = False
    disable_ip_masquerade: bool = False
    labels: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = _identifier(value, "network name")
        if value in {"bridge", "host", "none"}:
            raise ValueError("system networks cannot be replaced")
        return value

    @field_validator("labels")
    @classmethod
    def valid_labels(cls, value: dict[str, str]) -> dict[str, str]:
        return _labels(value)

    @model_validator(mode="after")
    def valid_ipam(self) -> "NetworkCreateRequest":
        def normalize(
            version: Literal[4, 6],
            mode: str,
            subnet_value: str | None,
            range_value: str | None,
            gateway_value: str | None,
        ) -> tuple[str | None, str | None, str | None]:
            values = (subnet_value, range_value, gateway_value)
            if mode in {"auto", "none"}:
                if any(value is not None for value in values):
                    raise ValueError(f"IPv{version} {mode} mode does not accept manual IPAM fields")
                return None, None, None
            if not subnet_value:
                raise ValueError(f"IPv{version} manual mode requires a subnet")
            try:
                network = ipaddress.ip_network(subnet_value, strict=False)
                ip_range = ipaddress.ip_network(range_value, strict=False) if range_value else None
                gateway = ipaddress.ip_address(gateway_value) if gateway_value else None
            except ValueError as error:
                raise ValueError(f"invalid IPv{version} IPAM value") from error
            if network.version != version or network.is_multicast or network.prefixlen == 0:
                raise ValueError(f"invalid IPv{version} subnet")
            if ip_range and (
                ip_range.version != version
                or ip_range.is_multicast
                or not ip_range.subnet_of(network)
            ):
                raise ValueError(f"IPv{version} IP range must belong to the subnet")
            if gateway and (gateway.version != version or gateway not in network):
                raise ValueError(f"IPv{version} gateway must belong to the subnet")
            if version == 4 and gateway and gateway in {network.network_address, network.broadcast_address}:
                raise ValueError("IPv4 gateway must be a usable host address")
            return str(network), str(ip_range) if ip_range else None, str(gateway) if gateway else None

        self.ipv4_subnet, self.ipv4_ip_range, self.ipv4_gateway = normalize(
            4,
            self.ipv4_mode,
            self.ipv4_subnet,
            self.ipv4_ip_range,
            self.ipv4_gateway,
        )
        self.ipv6_subnet, self.ipv6_ip_range, self.ipv6_gateway = normalize(
            6,
            self.ipv6_mode,
            self.ipv6_subnet,
            self.ipv6_ip_range,
            self.ipv6_gateway,
        )
        return self


class NetworkActionRequest(DockerModel):
    action: Literal["remove", "prune", "connect", "disconnect"]
    container: str | None = None
    force: bool = False
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("container")
    @classmethod
    def valid_container(cls, value: str | None) -> str | None:
        return _identifier(value, "container") if value else None

    @model_validator(mode="after")
    def container_required(self) -> "NetworkActionRequest":
        if self.action in {"connect", "disconnect"} and not self.container:
            raise ValueError("container is required")
        return self


class DefaultBridgeConfigRequest(DockerModel):
    ipv4_mode: Literal["auto", "manual"] = "auto"
    ipv4_subnet: str | None = None
    ipv4_ip_range: str | None = None
    ipv4_gateway: str | None = None
    ipv6_mode: Literal["none", "manual"] = "none"
    ipv6_subnet: str | None = None
    ipv6_gateway: str | None = None
    disable_ip_masquerade: bool = False
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def valid_bridge_ipam(self) -> "DefaultBridgeConfigRequest":
        if self.ipv4_mode == "auto":
            if any(value is not None for value in (self.ipv4_subnet, self.ipv4_ip_range, self.ipv4_gateway)):
                raise ValueError("IPv4 auto mode does not accept manual IPAM fields")
        else:
            if not self.ipv4_subnet or not self.ipv4_gateway:
                raise ValueError("manual default bridge IPv4 requires a subnet and gateway")
            try:
                network = ipaddress.ip_network(self.ipv4_subnet, strict=False)
                ip_range = ipaddress.ip_network(self.ipv4_ip_range, strict=False) if self.ipv4_ip_range else None
                gateway = ipaddress.ip_address(self.ipv4_gateway)
            except ValueError as error:
                raise ValueError("invalid default bridge IPv4 configuration") from error
            if network.version != 4 or network.is_multicast or network.prefixlen == 0:
                raise ValueError("invalid default bridge IPv4 subnet")
            if ip_range and (ip_range.version != 4 or not ip_range.subnet_of(network)):
                raise ValueError("default bridge IPv4 range must belong to the subnet")
            if gateway.version != 4 or gateway not in network or gateway in {network.network_address, network.broadcast_address}:
                raise ValueError("default bridge IPv4 gateway must be a usable address in the subnet")
            self.ipv4_subnet = str(network)
            self.ipv4_ip_range = str(ip_range) if ip_range else None
            self.ipv4_gateway = str(gateway)
        if self.ipv6_mode == "none":
            if self.ipv6_subnet is not None or self.ipv6_gateway is not None:
                raise ValueError("IPv6 none mode does not accept manual IPAM fields")
        else:
            if not self.ipv6_subnet:
                raise ValueError("manual default bridge IPv6 requires a subnet")
            try:
                network6 = ipaddress.ip_network(self.ipv6_subnet, strict=False)
                gateway6 = ipaddress.ip_address(self.ipv6_gateway) if self.ipv6_gateway else None
            except ValueError as error:
                raise ValueError("invalid default bridge IPv6 configuration") from error
            if network6.version != 6 or network6.is_multicast or network6.prefixlen == 0:
                raise ValueError("invalid default bridge IPv6 subnet")
            if gateway6 and (gateway6.version != 6 or gateway6 not in network6):
                raise ValueError("default bridge IPv6 gateway must belong to the subnet")
            self.ipv6_subnet = str(network6)
            self.ipv6_gateway = str(gateway6) if gateway6 else None
        return self


class ComposeSaveRequest(DockerModel):
    content: str = Field(max_length=512 * 1024)
    environment: dict[str, str] = Field(default_factory=dict, max_length=200)
    secret_environment: dict[str, str] | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=200)

    @field_validator("environment", "secret_environment")
    @classmethod
    def valid_environment(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _environment(value, "invalid environment variable") if value is not None else None

    @model_validator(mode="after")
    def distinct_environment(self) -> "ComposeSaveRequest":
        if self.secret_environment is not None and set(self.environment) & set(self.secret_environment):
            raise ValueError("a variable cannot be both public and secret")
        return self


class ComposeActionRequest(DockerModel):
    action: Literal["up", "down", "start", "stop", "restart", "pull", "recreate", "scale", "delete", "validate"]
    services: list[str] = Field(default_factory=list, max_length=100)
    scale: dict[str, int] = Field(default_factory=dict, max_length=100)
    remove_volumes: bool = False
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("services")
    @classmethod
    def valid_services(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(_identifier(value, "service") for value in values))

    @field_validator("scale")
    @classmethod
    def valid_scale(cls, value: dict[str, int]) -> dict[str, int]:
        if any(replicas < 0 or replicas > 1000 for replicas in value.values()):
            raise ValueError("replica count must be between 0 and 1000")
        return {_identifier(service, "service"): replicas for service, replicas in value.items()}

    @model_validator(mode="after")
    def scale_required(self) -> "ComposeActionRequest":
        if self.action == "scale" and not self.scale:
            raise ValueError("at least one service replica count is required")
        return self


class PrunePlanRequest(DockerModel):
    resources: list[Literal["containers", "images", "networks", "volumes", "build_cache"]] = Field(min_length=1, max_length=5)
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)


class EngineActionRequest(DockerModel):
    action: Literal["install", "reinstall", "update", "start", "stop", "restart", "enable", "disable", "test"]
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)


class DaemonConfigRequest(DockerModel):
    config: dict[str, object]
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def bounded(self) -> "DaemonConfigRequest":
        import json

        if len(json.dumps(self.config, ensure_ascii=False).encode("utf-8")) > 256 * 1024:
            raise ValueError("daemon configuration exceeds 256 KiB")
        if any(key in self.config for key in {"hosts", "authorization-plugins"}):
            raise ValueError("remote daemon listeners and authorization plugins are not managed here")
        return self


class AppInstallRequest(DockerModel):
    secret_environment: dict[str, str] = Field(default_factory=dict, max_length=50)
    timezone: str = "Europe/Warsaw"
    hostname: str = "pihole"
    panel_port: int = Field(default=8080, ge=1, le=65535)
    dns_port: int = Field(default=53, ge=1, le=65535)
    network: str = "bridge"
    confirmation: str = ""

    @field_validator("secret_environment")
    @classmethod
    def valid_environment(cls, value: dict[str, str]) -> dict[str, str]:
        return _environment(value, "invalid application secret")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        if value not in available_timezones():
            raise ValueError("timezone must be a known IANA timezone")
        return value

    @field_validator("hostname")
    @classmethod
    def valid_hostname(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("invalid application hostname")
        return value

    @field_validator("network")
    @classmethod
    def valid_network(cls, value: str) -> str:
        value = _identifier(value, "network")
        if value in {"host", "none"}:
            raise ValueError("host and none network modes are forbidden")
        return value


class AppActionRequest(DockerModel):
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)


class ContainerRestoreRequest(DockerModel):
    new_name: str
    secret_environment: dict[str, str] = Field(default_factory=dict, max_length=100)
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("new_name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _identifier(value, "container name")

    @field_validator("secret_environment")
    @classmethod
    def valid_environment(cls, value: dict[str, str]) -> dict[str, str]:
        return _environment(value, "invalid restore secret")


class ContainerFilesystemImportRequest(DockerModel):
    repository: str
    confirmation: str = ""

    @field_validator("repository")
    @classmethod
    def valid_repository(cls, value: str) -> str:
        return _image(value)
