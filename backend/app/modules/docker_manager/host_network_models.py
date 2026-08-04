from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import (
    DockerModel,
    HealthcheckSpec,
    MountSpec,
    PATH_RE,
    PortMapping,
    ResourceLimits,
    _environment,
    _identifier,
    _image,
    _labels,
)


class ContainerCreateRequest(DockerModel):
    """Container create request with controlled support for Docker host networking."""

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
        if value == "none":
            raise ValueError("none network mode is forbidden")
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

        if self.network == "host":
            if self.ports:
                raise ValueError("host network mode does not accept published ports")
            if self.network_aliases:
                raise ValueError("host network mode does not accept network aliases")
        elif self.network_aliases and self.network == "bridge":
            raise ValueError("network aliases require a user-defined bridge network")
        return self
