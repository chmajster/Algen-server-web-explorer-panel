from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, NoReturn

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:-]{0,127}$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@_.:-]{0,127}(?:\.service)?$")
PORT_RE = re.compile(r"^(?:[1-9][0-9]{0,4})/(?:tcp|udp)$")
ARCH_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class PackageAction(StrEnum):
    install = "install"
    update = "update"
    uninstall = "uninstall"
    start = "start"
    stop = "stop"
    restart = "restart"


class PackageJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    waiting_for_confirmation = "waiting_for_confirmation"


class ModuleUi(BaseModel):
    hidden: bool = False
    configurable: bool | None = None


class ModuleManifest(BaseModel):
    id: str
    name: str
    description: str
    long_description: str = ""
    category: str = "system_tools"
    version: str
    maintainer: str = "WebNAS"
    homepage: HttpUrl | None = None
    icon: str = "package"
    screenshots: list[str] = Field(default_factory=list)
    license: str = "Unknown"
    supported_distributions: list[str] = Field(default_factory=lambda: ["debian", "ubuntu", "raspbian", "fedora", "rhel", "rocky", "almalinux"])
    supported_architectures: list[str] = Field(default_factory=lambda: ["x86_64", "aarch64", "armv7l"])
    apt_packages: list[str] = Field(default_factory=list)
    dnf_packages: list[str] = Field(default_factory=list)
    systemd_services: list[str] = Field(default_factory=list)
    ports: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    config_paths: list[str] = Field(default_factory=list)
    data_paths: list[str] = Field(default_factory=list)
    backup_paths: list[str] = Field(default_factory=list)
    proxmox_safe: bool = False
    requires_reboot: bool = False
    requires_root: bool = True
    configurable: bool = False
    removable: bool = True
    healthcheck: str | None = "health.py"
    ui: ModuleUi = Field(default_factory=ModuleUi)
    changelog: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not MODULE_ID_RE.fullmatch(value):
            raise ValueError("invalid module id")
        return value

    @field_validator("apt_packages", "dnf_packages")
    @classmethod
    def valid_packages(cls, values: list[str]) -> list[str]:
        if any(not PACKAGE_RE.fullmatch(value) for value in values):
            raise ValueError("invalid package name")
        return list(dict.fromkeys(values))

    @field_validator("systemd_services")
    @classmethod
    def valid_services(cls, values: list[str]) -> list[str]:
        if any(not SERVICE_RE.fullmatch(value) for value in values):
            raise ValueError("invalid systemd service")
        return list(dict.fromkeys(value.removesuffix(".service") for value in values))

    @field_validator("ports")
    @classmethod
    def valid_ports(cls, values: list[str]) -> list[str]:
        if any(not PORT_RE.fullmatch(value) or int(value.split("/", 1)[0]) > 65535 for value in values):
            raise ValueError("invalid port")
        return list(dict.fromkeys(values))

    @field_validator("supported_architectures")
    @classmethod
    def valid_architectures(cls, values: list[str]) -> list[str]:
        if any(not ARCH_RE.fullmatch(value) for value in values):
            raise ValueError("invalid architecture")
        return values

    @field_validator("supported_distributions", "dependencies", "conflicts")
    @classmethod
    def valid_identifiers(cls, values: list[str]) -> list[str]:
        if any(not MODULE_ID_RE.fullmatch(value) for value in values):
            raise ValueError("invalid identifier")
        return list(dict.fromkeys(values))

    @field_validator("config_paths", "data_paths", "backup_paths")
    @classmethod
    def absolute_paths(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("/") or "\x00" in value or ".." in value.split("/") for value in values):
            raise ValueError("module paths must be absolute and traversal-free")
        return list(dict.fromkeys(values))

    @field_validator("healthcheck")
    @classmethod
    def safe_healthcheck(cls, value: str | None) -> str | None:
        if value is not None and value not in {"health.py", "health.sh"}:
            raise ValueError("healthcheck must use a fixed module-local filename")
        return value

    @model_validator(mode="after")
    def has_package_definition(self) -> "ModuleManifest":
        if not self.apt_packages and not self.dnf_packages and not self.ui.hidden:
            raise ValueError("installable module has no packages")
        return self


class DistributionInfo(BaseModel):
    id: str
    name: str
    version_id: str = ""
    id_like: list[str] = Field(default_factory=list)
    architecture: str
    package_manager: str | None = None


class PackagePlan(BaseModel):
    module_id: str
    action: PackageAction
    distribution: DistributionInfo
    compatible: bool
    blocked_by_proxmox: bool = False
    packages: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    ports: list[str] = Field(default_factory=list)
    config_paths: list[str] = Field(default_factory=list)
    data_paths: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_reboot: bool = False
    remove_data: bool = False
    previous_version: str | None = None
    target_version: str | None = None
    steps: list[str] = Field(default_factory=list)


class AdminPackageAction(BaseModel):
    admin_password: str
    confirm_plan: bool = True
    remove_data: bool = False


class PackageSourceInput(BaseModel):
    name: str
    github_url: HttpUrl
    branch: str = "main"
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 100 or any(char in value for char in "\r\n\x00"):
            raise ValueError("invalid source name")
        return value

    @field_validator("github_url")
    @classmethod
    def github_only(cls, value: HttpUrl) -> HttpUrl:
        if value.host != "github.com" or len((value.path or "").strip("/").split("/")) != 2:
            raise ValueError("only GitHub repository URLs are supported")
        return value

    @field_validator("branch")
    @classmethod
    def valid_branch(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,120}", value) or ".." in value:
            raise ValueError("invalid branch/ref")
        return value


def api_error(status: int, code: str, message: str, **extra: Any) -> NoReturn:
    from fastapi import HTTPException

    raise HTTPException(status, {"code": code, "message": message, **extra})
