from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .models import ChannelName, ID_PATTERN, StrictModel


class OfflineBundleType(StrEnum):
    full = "full"
    selected = "selected"
    delta = "delta"


class OfflineBundleStatus(StrEnum):
    creating = "creating"
    ready = "ready"
    verified = "verified"
    imported = "imported"
    failed = "failed"
    deleted = "deleted"


class OfflineTargetInput(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    repository_id: str = Field(pattern=ID_PATTERN)
    snapshot_id: str | None = Field(default=None, pattern=ID_PATTERN)
    channel: ChannelName | None = None
    distribution: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    distribution_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    architecture: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.+-]+$")
    package_names: list[str] = Field(default_factory=list, max_length=5000)
    include_dependencies: bool = True
    signing_key_id: str | None = Field(default=None, pattern=ID_PATTERN)
    host_group_id: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def snapshot_or_channel(self) -> "OfflineTargetInput":
        if self.snapshot_id and self.channel:
            raise ValueError("target cannot pin both a snapshot and a channel")
        return self


class OfflineExportInput(StrictModel):
    repository_id: str = Field(pattern=ID_PATTERN)
    snapshot_id: str | None = Field(default=None, pattern=ID_PATTERN)
    channel: ChannelName | None = None
    target_id: str | None = Field(default=None, pattern=ID_PATTERN)
    architecture: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.+-]+$")
    package_names: list[str] = Field(default_factory=list, max_length=5000)
    include_dependencies: bool = True
    bundle_type: OfflineBundleType = OfflineBundleType.full
    base_snapshot_id: str | None = Field(default=None, pattern=ID_PATTERN)
    sign_manifest: bool = True
    confirm: bool = False

    @model_validator(mode="after")
    def valid_scope(self) -> "OfflineExportInput":
        if bool(self.snapshot_id) == bool(self.channel):
            raise ValueError("exactly one snapshot or channel is required")
        if self.bundle_type == OfflineBundleType.selected and not self.package_names:
            raise ValueError("selected bundle requires at least one package")
        if self.bundle_type == OfflineBundleType.delta and not self.base_snapshot_id:
            raise ValueError("delta bundle requires a base snapshot")
        return self


class OfflineImportInput(StrictModel):
    repository_id: str = Field(pattern=ID_PATTERN)
    publish_channel: ChannelName | None = None
    confirmation_text: str = Field(default="", max_length=128)
    confirm: bool = False


class OfflineSettingsInput(StrictModel):
    air_gapped_mode: bool = False
    keep_last: int = Field(default=5, ge=1, le=100)
    delete_after_days: int = Field(default=90, ge=1, le=3650)
    keep_production: bool = True
    keep_signed: bool = True


class BundlePinInput(StrictModel):
    pinned: bool = True
    confirm: bool = False
