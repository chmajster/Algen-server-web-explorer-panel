from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")
GITHUB_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?(?:\.git)?$")
REF_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,120}$")
SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
CHECKSUM_RE = re.compile(r"^[a-fA-F0-9]{64}$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")
ENTRYPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,199}$")


class PluginTrust(StrEnum):
    unverified = "unverified"
    trusted = "trusted"
    blocked = "blocked"


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    id: str
    name: str = Field(min_length=1, max_length=200)
    version: str
    publisher: str = Field(default="unknown", min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    repository: str
    min_algen_version: str = "0.1.0"
    entrypoint: str = ""
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    permissions: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not PLUGIN_ID_RE.fullmatch(value):
            raise ValueError("invalid plugin id")
        return value

    @field_validator("version", "min_algen_version")
    @classmethod
    def valid_semver(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("invalid semantic version")
        return value

    @field_validator("repository")
    @classmethod
    def valid_repository(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not GITHUB_URL_RE.fullmatch(normalized):
            raise ValueError("plugin repository must be an HTTPS GitHub repository")
        return normalized

    @field_validator("entrypoint")
    @classmethod
    def valid_entrypoint(cls, value: str) -> str:
        if value and not ENTRYPOINT_RE.fullmatch(value):
            raise ValueError("invalid plugin entrypoint")
        return value

    @field_validator("capabilities", "permissions")
    @classmethod
    def valid_capabilities(cls, values: list[str]) -> list[str]:
        if any(not CAPABILITY_RE.fullmatch(value) for value in values):
            raise ValueError("invalid plugin capability or permission")
        return list(dict.fromkeys(values))


class StorePlugin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    name: str
    github_url: str
    branch: str = "main"
    enabled: bool = True
    codex_instructions: str = ""
    created_at: float = 0
    updated_at: float = 0
    schema_version: int = 1
    version: str = "0.0.0"
    installed_version: str | None = None
    available_version: str | None = None
    publisher: str = "unknown"
    description: str = ""
    min_algen_version: str = "0.1.0"
    entrypoint: str = ""
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    source_ref: str = "main"
    resolved_commit: str | None = None
    checksum_sha256: str | None = None
    trust: PluginTrust = PluginTrust.unverified
    credential_id: str | None = None


class PluginInstallMetadata(BaseModel):
    resolved_commit: str
    checksum_sha256: str
    installed_version: str
