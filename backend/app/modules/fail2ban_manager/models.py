from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class BanInput(BaseModel):
    ip: str = Field(min_length=2, max_length=64)
    confirm: bool = False


class JailToggleInput(BaseModel):
    enabled: bool
    confirm: bool = False


class ServiceActionInput(BaseModel):
    confirm: bool = False


class JailConfigInput(BaseModel):
    enabled: bool = True
    filter: str = Field(default="", max_length=128)
    backend: str = Field(default="", max_length=64)
    port: str = Field(default="", max_length=256)
    maxretry: int | None = Field(default=None, ge=1, le=100000)
    findtime: str = Field(default="", max_length=64)
    bantime: str = Field(default="", max_length=64)
    action: str = Field(default="", max_length=512)
    confirm: bool = False

    @field_validator("filter", "backend", "port", "findtime", "bantime", "action")
    @classmethod
    def no_control_characters(cls, value: str) -> str:
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("configuration values cannot contain control characters")
        return value.strip()
