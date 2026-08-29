from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, Field, field_validator


class NtpBackend(StrEnum):
    chrony = "chrony"
    timesyncd = "systemd-timesyncd"
    ntpd = "ntpd"
    none = "none"


class NtpSourceInput(BaseModel):
    server: str = Field(min_length=1, max_length=253)
    prefer: bool = False
    enabled: bool = True
    confirm: bool = False

    @field_validator("server")
    @classmethod
    def validate_server(cls, value: str) -> str:
        value = value.strip().rstrip(".")
        if not value or any(char.isspace() for char in value) or "/" in value or "\\" in value:
            raise ValueError("invalid NTP server")
        return value


class ServiceActionInput(BaseModel):
    action: str
    confirm: bool = False
