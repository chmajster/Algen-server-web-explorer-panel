from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class AlertSeverity(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class AlertState(StrEnum):
    firing = "firing"
    acknowledged = "acknowledged"
    resolved = "resolved"


class SinkType(StrEnum):
    webhook = "webhook"
    ntfy = "ntfy"
    smtp = "smtp"


class RuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9._-]+$")
    severity: AlertSeverity = AlertSeverity.error
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    enabled: bool = True
    sink_ids: list[str] = Field(default_factory=list, max_length=32)
    matcher: dict[str, Any] = Field(default_factory=dict)


class SinkInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: SinkType
    enabled: bool = True
    url: HttpUrl | None = None
    token: str = Field(default="", max_length=8192)
    smtp_host: str = Field(default="", max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(default="", max_length=256)
    smtp_password: str = Field(default="", max_length=8192)
    smtp_from: str = Field(default="", max_length=320)
    smtp_to: list[str] = Field(default_factory=list, max_length=32)
    smtp_starttls: bool = True

    @model_validator(mode="after")
    def validate_sink(self) -> "SinkInput":
        if self.type in {SinkType.webhook, SinkType.ntfy}:
            if self.url is None or self.url.scheme != "https":
                raise ValueError("webhook sinks require an HTTPS URL")
        elif not self.smtp_host or not self.smtp_from or not self.smtp_to:
            raise ValueError("SMTP sinks require host, sender and at least one recipient")
        return self


class AlertEvent(BaseModel):
    source: str = Field(min_length=1, max_length=96)
    key: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=256)
    object_ref: str = Field(default="", max_length=512)
    details: dict[str, Any] = Field(default_factory=dict)
    severity: AlertSeverity | None = None


class AlertActionInput(BaseModel):
    note: str = Field(default="", max_length=1000)


class TestDeliveryInput(BaseModel):
    sink_id: str = Field(min_length=1, max_length=64)
    diagnostic: dict[str, Any] = Field(default_factory=dict)
