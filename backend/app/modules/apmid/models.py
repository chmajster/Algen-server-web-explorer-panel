from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class ApmidRole(StrEnum):
    viewer = "viewer"
    operator = "operator"
    manager = "manager"
    owner = "owner"


class ApmidResourcePermission(StrEnum):
    view = "view"
    update = "update"
    members_view = "members.view"
    members_manage = "members.manage"
    permissions_view = "permissions.view"
    permissions_manage = "permissions.manage"
    audit_view = "audit.view"
    delete = "delete"


class PermissionEffect(StrEnum):
    allow = "allow"
    deny = "deny"


class ApmidInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    active: bool = True
    business_owner: str | None = Field(default=None, max_length=160)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or not re.fullmatch(r"[A-Z0-9_-]+", normalized):
            raise ValueError("APMID code may contain only letters, digits, underscores, and hyphens")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("APMID name cannot be empty")
        return value

    @field_validator("business_owner")
    @classmethod
    def normalize_owner(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ApmidMemberCreate(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=100)
    role: ApmidRole = ApmidRole.viewer

    @field_validator("usernames")
    @classmethod
    def unique_users(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("Usernames must be non-empty and unique")
        return normalized


class ApmidMemberUpdate(BaseModel):
    role: ApmidRole


class ApmidPermissionUpdate(BaseModel):
    allow: list[ApmidResourcePermission] = Field(default_factory=list, max_length=8)
    deny: list[ApmidResourcePermission] = Field(default_factory=list, max_length=8)

    @field_validator("allow", "deny")
    @classmethod
    def unique_permissions(cls, values: list[ApmidResourcePermission]) -> list[ApmidResourcePermission]:
        return list(dict.fromkeys(values))


class ApmidRestoreInput(BaseModel):
    confirmation: str = Field(max_length=64)


class ApmidBackupInput(BaseModel):
    description: str = Field(default="", max_length=500)


class ApmidPurgeInput(BaseModel):
    confirmation: str = Field(max_length=64)

