from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

WebhookMethod = Literal["POST", "PUT", "PATCH"]
WebhookAuth = Literal["none", "bearer", "basic", "api_key_header", "secret_header"]


class WebhookInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    url: str = Field(min_length=8, max_length=4096)
    method: WebhookMethod = "POST"
    events: list[str] = Field(default_factory=list, max_length=256)
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    max_attempts: int = Field(default=3, ge=1, le=8)
    headers: dict[str, str] = Field(default_factory=dict)
    auth_type: WebhookAuth = "none"
    secret_id: str | None = Field(default=None, max_length=64)
    auth_header_name: str = Field(default="X-API-Key", max_length=128)
    signing_secret_id: str | None = Field(default=None, max_length=64)
    allow_private_networks: bool = False

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("webhook name is required")
        return value

    @field_validator("events")
    @classmethod
    def unique_events(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = value.strip().lower()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    @field_validator("headers")
    @classmethod
    def safe_headers(cls, values: dict[str, str]) -> dict[str, str]:
        forbidden = {"authorization", "cookie", "host", "content-length", "transfer-encoding", "x-webnas-signature"}
        result: dict[str, str] = {}
        for raw_name, raw_value in values.items():
            name = raw_name.strip()
            value = raw_value.strip()
            if not name or name.lower() in forbidden:
                raise ValueError(f"header {raw_name!r} is managed or forbidden")
            if any(character in name for character in "\r\n:") or any(character in value for character in "\r\n\x00"):
                raise ValueError("invalid webhook header")
            if len(name) > 128 or len(value) > 4096:
                raise ValueError("webhook header is too large")
            result[name] = value
        return result

    @field_validator("auth_header_name")
    @classmethod
    def safe_auth_header(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character in value for character in "\r\n:"):
            raise ValueError("invalid authentication header name")
        if value.lower() in {"host", "content-length", "cookie"}:
            raise ValueError("unsupported authentication header")
        return value


class WebhookDeleteInput(BaseModel):
    confirm: bool = False
