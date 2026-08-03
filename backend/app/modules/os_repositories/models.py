from __future__ import annotations

import re
import base64
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[a-f0-9]{32}$"
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RepositoryKind(StrEnum):
    local = "local"
    mirror = "mirror"


class RepositoryFormat(StrEnum):
    apt = "apt"
    rpm = "rpm"


class ChannelName(StrEnum):
    incoming = "incoming"
    testing = "testing"
    production = "production"
    archive = "archive"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RepositoryInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    kind: RepositoryKind
    format: RepositoryFormat
    distribution: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    distribution_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    architectures: list[str] = Field(min_length=1, max_length=16)
    source_url: str = Field(default="", max_length=2048)
    active: bool = True
    schedule: str = Field(default="", max_length=128)
    retention_count: int = Field(default=10, ge=1, le=1000)
    signing_key_id: str | None = Field(default=None, pattern=ID_PATTERN)
    allow_private_network: bool = False
    allow_private_http: bool = False

    @field_validator("schedule")
    @classmethod
    def valid_schedule(cls, value: str) -> str:
        if not value:
            return value
        if value in {"@hourly", "@daily", "@weekly"}:
            return value
        fields = value.split()
        if len(fields) != 5 or any(not re.fullmatch(r"[0-9*/,-]+", field) for field in fields):
            raise ValueError("schedule must be a five-field cron expression or @hourly/@daily/@weekly")
        return value

    @field_validator("architectures")
    @classmethod
    def valid_architectures(cls, values: list[str]) -> list[str]:
        allowed = {"amd64", "x86_64", "arm64", "aarch64", "armhf", "armv7l", "noarch", "all"}
        if any(value not in allowed for value in values):
            raise ValueError("unsupported package architecture")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def valid_source(self) -> "RepositoryInput":
        if self.kind == RepositoryKind.local and self.source_url:
            raise ValueError("local repositories cannot define a source URL")
        if self.kind == RepositoryKind.mirror:
            parsed = urlsplit(self.source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("mirror URL must use HTTP(S) without credentials or fragments")
            if parsed.scheme == "http" and not self.allow_private_http:
                raise ValueError("HTTP mirrors require explicit private HTTP approval")
        return self


class FilterRuleInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    include_names: list[str] = Field(default_factory=list, max_length=500)
    exclude_names: list[str] = Field(default_factory=list, max_length=500)
    include_globs: list[str] = Field(default_factory=list, max_length=100)
    exclude_globs: list[str] = Field(default_factory=list, max_length=100)
    include_regex: str = Field(default="", max_length=256)
    exclude_regex: str = Field(default="", max_length=256)
    architectures: list[str] = Field(default_factory=list, max_length=16)
    minimum_version: str = Field(default="", max_length=128)
    maximum_version: str = Field(default="", max_length=128)
    latest_versions: int | None = Field(default=None, ge=1, le=100)
    exclude_source: bool = True
    exclude_debug: bool = False
    exclude_devel: bool = False
    minimum_published_at: float | None = Field(default=None, ge=0)
    maximum_published_at: float | None = Field(default=None, ge=0)
    maximum_size: int | None = Field(default=None, ge=1, le=20 * 1024**3)

    @field_validator("include_regex", "exclude_regex")
    @classmethod
    def safe_regex(cls, value: str) -> str:
        if not value:
            return value
        if re.search(r"\)[+*{]|\\[1-9]|\(\?|\.\*.*\.\*|\.\+.*\.\+", value):
            raise ValueError("regex uses a disallowed complex construct")
        re.compile(value)
        return value


class SnapshotInput(StrictModel):
    name: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_.+-]*$")
    description: str = Field(default="", max_length=1000)


class PromotionInput(StrictModel):
    snapshot_id: str = Field(pattern=ID_PATTERN)
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class RollbackInput(StrictModel):
    confirm: bool = False
    confirmation_text: str = Field(default="", max_length=128)


class SyncInput(StrictModel):
    confirm: bool = False


class CancelInput(StrictModel):
    confirm: bool = False


class SigningKeyInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    public_key: str = Field(min_length=32, max_length=262144)
    private_key: str = Field(default="", max_length=262144)
    passphrase: str = Field(default="", max_length=4096)
    fingerprint: str = Field(min_length=16, max_length=64, pattern=r"^[A-Fa-f0-9 ]+$")
    expires_at: float | None = Field(default=None, ge=0)


class SigningKeyGenerateInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    identity: str = Field(min_length=3, max_length=256)
    expires: str = Field(default="2y", max_length=16, pattern=r"^(0|[1-9][0-9]*[dwmy])$")
    passphrase: str = Field(default="", max_length=4096)
    confirm: bool = False


class HostAssignmentInput(StrictModel):
    repository_id: str = Field(pattern=ID_PATTERN)
    channel: ChannelName
    host_id: str | None = Field(default=None, pattern=ID_PATTERN)
    group_id: str | None = Field(default=None, pattern=ID_PATTERN)
    confirm: bool = False

    @model_validator(mode="after")
    def one_target(self) -> "HostAssignmentInput":
        if bool(self.host_id) == bool(self.group_id):
            raise ValueError("exactly one host or host group is required")
        return self


class SettingsInput(StrictModel):
    listen_address: str = Field(default="0.0.0.0", max_length=64)
    port: int = Field(default=8088, ge=1024, le=65535)
    public_base_url: str = Field(default="", max_length=2048)
    upload_limit_mb: int = Field(default=2048, ge=1, le=20480)
    max_parallel_syncs: int = Field(default=1, ge=1, le=4)


class BackupInput(StrictModel):
    description: str = Field(default="", max_length=500)
    include_content: bool = False
    include_private_keys: bool = False
    passphrase: str = Field(default="", max_length=4096)
    confirm: bool = False


class RestoreInput(StrictModel):
    checksum: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    confirmation_text: str = Field(max_length=128)
    private_keys_passphrase: str = Field(default="", max_length=4096)
    confirm: bool = False


class FullRemoveInput(StrictModel):
    confirmation_text: str = Field(max_length=128)
    force: bool = False


class PackageBuildFileInput(StrictModel):
    source_name: str = Field(min_length=1, max_length=255)
    target_path: str = Field(min_length=2, max_length=1024)
    owner: str = Field(default="root", max_length=32, pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    group: str = Field(default="root", max_length=32, pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    mode: str = Field(default="0644", pattern=r"^0[0-7]{3}$")
    config_file: bool = False
    content_base64: str = Field(max_length=28 * 1024 * 1024)

    @field_validator("target_path")
    @classmethod
    def safe_target(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value.split("/") or "\x00" in value or not re.fullmatch(r"/[A-Za-z0-9_./+@-]+", value):
            raise ValueError("package file target must be an absolute safe path")
        return value

    @field_validator("content_base64")
    @classmethod
    def valid_content(cls, value: str) -> str:
        try:
            base64.b64decode(value, validate=True)
        except ValueError as error:
            raise ValueError("package file content is not valid base64") from error
        return value


class PackageBuildInput(StrictModel):
    repository_id: str = Field(pattern=ID_PATTERN)
    format: RepositoryFormat
    name: str = Field(min_length=1, max_length=128, pattern=NAME_PATTERN)
    version: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9.+:~_-]{0,127}$")
    release: str = Field(default="1", max_length=64, pattern=r"^[A-Za-z0-9.+_-]+$")
    architecture: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=4000)
    maintainer: str = Field(default="", max_length=256)
    vendor: str = Field(default="", max_length=256)
    license: str = Field(default="", max_length=128)
    homepage: str = Field(default="", max_length=2048)
    dependencies: list[str] = Field(default_factory=list, max_length=200)
    conflicts: list[str] = Field(default_factory=list, max_length=200)
    files: list[PackageBuildFileInput] = Field(default_factory=list, max_length=200)
    maintainer_scripts: dict[str, str] = Field(default_factory=dict)
    allow_maintainer_scripts: bool = False
    confirm: bool = False

    @field_validator("maintainer_scripts")
    @classmethod
    def valid_scripts(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"pre_install", "post_install", "pre_remove", "post_remove"}
        if any(key not in allowed or len(content) > 65536 or "\x00" in content for key, content in value.items()):
            raise ValueError("invalid maintainer script")
        return value

    @model_validator(mode="after")
    def scripts_confirmed(self) -> "PackageBuildInput":
        if self.maintainer_scripts and not self.allow_maintainer_scripts:
            raise ValueError("maintainer scripts require explicit high-risk approval")
        if sum(len(item.content_base64) * 3 // 4 for item in self.files) > 200 * 1024 * 1024:
            raise ValueError("package build files exceed the 200 MiB limit")
        return self


JsonObject = dict[str, Any]
