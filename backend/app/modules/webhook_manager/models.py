from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

WebhookMethod = Literal["POST", "PUT", "PATCH"]
WebhookAuth = Literal["none", "bearer", "basic", "api_key_header", "secret_header"]

HTTP_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
CUSTOM_HEADER_FORBIDDEN = {
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
    "x-webnas-delivery",
    "x-webnas-event",
    "x-webnas-signature",
    "x-webnas-timestamp",
}
AUTH_HEADER_FORBIDDEN = {
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
    "x-webnas-delivery",
    "x-webnas-event",
    "x-webnas-signature",
    "x-webnas-timestamp",
}


def _valid_header_name(value: str) -> bool:
    return bool(HTTP_HEADER_NAME_RE.fullmatch(value))


def _valid_header_value(value: str) -> bool:
    return all((ord(character) >= 32 or character == "\t") and ord(character) != 127 for character in value)


def normalize_custom_headers(values: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        normalized = name.casefold()
        if not name or not _valid_header_name(name):
            raise ValueError("invalid webhook header name")
        if normalized in CUSTOM_HEADER_FORBIDDEN:
            raise ValueError(f"header {raw_name!r} is managed or forbidden")
        if normalized in seen:
            raise ValueError(f"duplicate webhook header {raw_name!r}")
        if not _valid_header_value(value):
            raise ValueError("invalid webhook header value")
        if len(name) > 128 or len(value) > 4096:
            raise ValueError("webhook header is too large")
        seen.add(normalized)
        result[name] = value
    return result


def normalize_auth_header_name(value: str) -> str:
    value = str(value).strip()
    if not value or not _valid_header_name(value):
        raise ValueError("invalid authentication header name")
    if value.casefold() in AUTH_HEADER_FORBIDDEN:
        raise ValueError("unsupported authentication header")
    return value


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
        return normalize_custom_headers(values)

    @field_validator("auth_header_name")
    @classmethod
    def safe_auth_header(cls, value: str) -> str:
        return normalize_auth_header_name(value)


class WebhookDeleteInput(BaseModel):
    confirm: bool = False
