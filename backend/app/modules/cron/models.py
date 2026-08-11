from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from .schedule import CronExpression, explain_schedule, next_occurrence


JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}\$?$", re.IGNORECASE)
ENVIRONMENT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class CronJobSource(StrEnum):
    webnas = "webnas"
    user_crontab = "user_crontab"
    system_crontab = "system_crontab"
    cron_d = "cron_d"
    system = "system"


class CronJobStatus(StrEnum):
    enabled = "enabled"
    disabled = "disabled"
    external = "external"
    invalid = "invalid"


class CronEnvironmentVariable(BaseModel):
    name: str
    value: str = Field(default="", max_length=2048)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not ENVIRONMENT_KEY_RE.fullmatch(value):
            raise ValueError("invalid environment variable name")
        return value

    @field_validator("value")
    @classmethod
    def safe_value(cls, value: str) -> str:
        if "\n" in value or "\r" in value or "\x00" in value or CONTROL_RE.search(value):
            raise ValueError("environment values cannot contain control characters")
        return value


class CronJobDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    user: str = Field(default="root", min_length=1, max_length=32)
    schedule: str = Field(min_length=1, max_length=160)
    command: str = Field(min_length=1, max_length=4096)
    working_directory: str | None = Field(default=None, max_length=1000)
    environment: list[CronEnvironmentVariable] = Field(default_factory=list, max_length=64)
    timeout_seconds: int | None = Field(default=None, ge=1, le=604_800)
    enabled: bool = True

    @field_validator("name", "description")
    @classmethod
    def safe_text(cls, value: str) -> str:
        value = value.strip()
        if "\n" in value or "\r" in value or "\x00" in value or CONTROL_RE.search(value):
            raise ValueError("text cannot contain control characters")
        return value

    @field_validator("user")
    @classmethod
    def valid_user(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("invalid Linux username")
        return value

    @field_validator("schedule")
    @classmethod
    def valid_schedule(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        CronExpression.parse(normalized)
        return normalized

    @field_validator("command")
    @classmethod
    def safe_command_data(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value or "\x00" in value or CONTROL_RE.search(value):
            raise ValueError("command must be a single line without control characters")
        return value

    @field_validator("working_directory")
    @classmethod
    def valid_working_directory(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if "\n" in value or "\r" in value or "\x00" in value or CONTROL_RE.search(value):
            raise ValueError("working directory cannot contain control characters")
        if not Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("working directory must be an absolute traversal-free path")
        return value

    @model_validator(mode="after")
    def unique_environment(self) -> Self:
        names = [item.name for item in self.environment]
        if len(names) != len(set(names)):
            raise ValueError("environment variable names must be unique")
        return self


class CronJobCreate(CronJobDefinition):
    id: str | None = None

    @field_validator("id")
    @classmethod
    def valid_optional_id(cls, value: str | None) -> str | None:
        if value is not None and not JOB_ID_RE.fullmatch(value):
            raise ValueError("invalid cron job id")
        return value


class CronJobUpdate(CronJobDefinition):
    pass


class CronJob(CronJobDefinition):
    id: str
    source: CronJobSource = CronJobSource.webnas
    status: CronJobStatus = CronJobStatus.enabled
    read_only: bool = False
    created_at: float | None = None
    updated_at: float | None = None
    created_by: str = ""
    updated_by: str = ""
    last_run_at: float | None = None
    last_run_status: str | None = None
    next_run_at: float | None = None
    source_label: str = "WebNAS"

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not (JOB_ID_RE.fullmatch(value) or value.startswith("external-")):
            raise ValueError("invalid cron job id")
        return value


class CronValidationRequest(BaseModel):
    schedule: str = Field(min_length=1, max_length=160)
    user: str = Field(default="root", min_length=1, max_length=32)
    command: str = Field(default="/bin/true", min_length=1, max_length=4096)
    working_directory: str | None = Field(default=None, max_length=1000)
    environment: list[CronEnvironmentVariable] = Field(default_factory=list, max_length=64)
    timeout_seconds: int | None = Field(default=None, ge=1, le=604_800)

    def definition(self) -> CronJobDefinition:
        return CronJobDefinition(
            name="Validation preview",
            schedule=self.schedule,
            user=self.user,
            command=self.command,
            working_directory=self.working_directory,
            environment=self.environment,
            timeout_seconds=self.timeout_seconds,
        )


class CronValidationResult(BaseModel):
    valid: bool
    normalized: str
    explanation: str
    next_run_at: float | None
    generated_entry: str
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def for_definition(cls, definition: CronJobDefinition, generated_entry: str, warnings: list[str] | None = None) -> "CronValidationResult":
        following = next_occurrence(definition.schedule)
        return cls(
            valid=True,
            normalized=definition.schedule,
            explanation=explain_schedule(definition.schedule),
            next_run_at=following.timestamp() if following else None,
            generated_entry=generated_entry,
            warnings=warnings or [],
        )


class CronMutationConfirmation(BaseModel):
    confirmation: str = Field(min_length=1, max_length=160)
    pam_password: str = Field(min_length=1, max_length=1024)


class CronJobCreateRequest(CronJobDefinition, CronMutationConfirmation):
    pass


class CronJobUpdateRequest(CronJobDefinition, CronMutationConfirmation):
    pass


class CronDiagnostic(BaseModel):
    code: str
    status: str
    title: str
    detail: str = ""
    recommendation: str = ""


class CronLogEntry(BaseModel):
    source: str
    message: str
    timestamp: str | None = None


class CronDashboard(BaseModel):
    active: int = 0
    inactive: int = 0
    errors: int = 0
    recently_run: int = 0
    total: int = 0


class CronStatus(BaseModel):
    installed: bool
    crontab_available: bool
    daemon: str | None = None
    service_state: str = "unknown"
    service_enabled: bool | None = None
    configuration_valid: bool | None = None
    timezone: str
    config_path: str
    blocked_by_proxmox: bool = False
    dashboard: CronDashboard = Field(default_factory=CronDashboard)
