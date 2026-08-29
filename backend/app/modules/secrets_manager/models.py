from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SecretType = Literal[
    "username_password",
    "ssh_password",
    "ssh_private_key",
    "become_password",
    "api_token",
    "generic_secret",
    "proxmox_api",
    "redfish",
    "ipmi",
    "git_private_key",
    "wol",
]

SECRET_TYPES: tuple[str, ...] = (
    "username_password",
    "ssh_password",
    "ssh_private_key",
    "become_password",
    "api_token",
    "generic_secret",
    "proxmox_api",
    "redfish",
    "ipmi",
    "git_private_key",
    "wol",
)


class SecretInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: SecretType
    username: str = Field(default="", max_length=320)
    secret: str = Field(default="", max_length=131072)
    passphrase: str = Field(default="", max_length=32768)
    description: str = Field(default="", max_length=2000)
    environment_id: str | None = Field(default=None, max_length=64)
    shared_with: list[str] = Field(default_factory=list, max_length=256)
    confirm: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("secret name is required")
        return value

    @field_validator("shared_with")
    @classmethod
    def normalize_shares(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values:
            value = raw.strip().lower()
            if not value or len(value) > 64:
                raise ValueError("invalid module id in shared_with")
            if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
                raise ValueError("invalid module id in shared_with")
            if value not in result:
                result.append(value)
        return result


class SecretDeleteInput(BaseModel):
    confirm: bool = False


class KeyRotationInput(BaseModel):
    confirmation: str = Field(min_length=1, max_length=160)


class RestoreInput(BaseModel):
    payload: str = Field(min_length=1, max_length=20_000_000)
    confirmation: str = Field(min_length=1, max_length=160)
