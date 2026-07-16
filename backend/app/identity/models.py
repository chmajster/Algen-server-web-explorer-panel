from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


IDENTITY_NAME_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}\$?$", re.IGNORECASE)


class Role(StrEnum):
    admin = "admin"
    operator = "operator"
    auditor = "auditor"
    user = "user"


class PermissionRisk(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class PermissionMetadata(BaseModel):
    id: str
    category: str
    operation: str
    applications: list[str]
    risk: PermissionRisk
    mutating: bool
    label_key: str
    description_key: str


class PolicyBase(BaseModel):
    allow: list[str] = Field(default_factory=list, max_length=256)
    deny: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("allow", "deny")
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        from .permissions import normalize_permissions

        return normalize_permissions(value)

    @model_validator(mode="after")
    def disjoint_policy(self) -> "PolicyBase":
        overlap = set(self.allow) & set(self.deny)
        if overlap:
            raise ValueError(f"permissions cannot be both allowed and denied: {', '.join(sorted(overlap))}")
        return self


class UserPolicy(PolicyBase):
    username: str
    role: Role = Role.user
    created_at: float = 0
    updated_at: float = 0
    updated_by: str = ""

    @field_validator("username")
    @classmethod
    def username_valid(cls, value: str) -> str:
        if not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local username")
        return value


class GroupPolicy(PolicyBase):
    groupname: str
    created_at: float = 0
    updated_at: float = 0
    updated_by: str = ""

    @field_validator("groupname")
    @classmethod
    def groupname_valid(cls, value: str) -> str:
        if not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local group name")
        return value


class AdminCredential(BaseModel):
    admin_password: str = Field(min_length=1, max_length=1024)
    confirm: bool = True


class UserPolicyRequest(PolicyBase, AdminCredential):
    role: Role = Role.user


class GroupPolicyRequest(PolicyBase, AdminCredential):
    pass


class UserCreateRequest(UserPolicyRequest):
    username: str
    password: str = Field(min_length=1, max_length=1024)
    home: str | None = Field(default=None, max_length=512)
    shell: str | None = Field(default=None, max_length=256)
    gecos: str = Field(default="", max_length=256)
    groups: list[str] = Field(default_factory=list, max_length=64)
    uid: int | None = Field(default=None, ge=1, le=2_147_483_647)
    gid: int | None = Field(default=None, ge=1, le=2_147_483_647)
    create_home: bool = True
    force_password_change: bool = False
    system: bool = False

    @field_validator("username")
    @classmethod
    def username_valid(cls, value: str) -> str:
        if not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local username")
        return value


class UserPatchRequest(AdminCredential):
    new_username: str | None = None
    home: str | None = Field(default=None, max_length=512)
    shell: str | None = Field(default=None, max_length=256)
    gecos: str | None = Field(default=None, max_length=256)
    groups_add: list[str] = Field(default_factory=list, max_length=64)
    groups_remove: list[str] = Field(default_factory=list, max_length=64)
    move_home: bool = False
    force_password_change: bool | None = None

    @field_validator("new_username")
    @classmethod
    def new_username_valid(cls, value: str | None) -> str | None:
        if value is not None and not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local username")
        return value


class PasswordChangeRequest(AdminCredential):
    new_password: str = Field(min_length=1, max_length=1024)
    force_change: bool = False


class UserDeleteRequest(AdminCredential):
    remove_home: bool = False


class UserQuotaRequest(AdminCredential):
    soft_mb: int = Field(ge=0, le=10_000_000)
    hard_mb: int | None = Field(default=None, ge=0, le=10_000_000)
    mountpoint: str | None = Field(default=None, max_length=512)


class GroupCreateRequest(GroupPolicyRequest):
    groupname: str
    gid: int | None = Field(default=None, ge=1, le=2_147_483_647)
    system: bool = False

    @field_validator("groupname")
    @classmethod
    def groupname_valid(cls, value: str) -> str:
        if not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local group name")
        return value


class GroupPatchRequest(AdminCredential):
    new_name: str

    @field_validator("new_name")
    @classmethod
    def groupname_valid(cls, value: str) -> str:
        if not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local group name")
        return value


class GroupMemberRequest(AdminCredential):
    username: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, value: str) -> str:
        if not IDENTITY_NAME_RE.fullmatch(value):
            raise ValueError("invalid local username")
        return value


class AccessProfile(BaseModel):
    username: str
    role: Role
    role_source: Literal["linux-admin", "assignment", "default"]
    linux_admin: bool
    is_admin: bool
    permissions: list[str]
    denied_permissions: list[str]
    permission_sources: dict[str, list[str]]


class PermissionChange(BaseModel):
    id: int
    created_at: float
    actor: str
    subject_type: Literal["user", "group", "migration"]
    subject: str
    action: str
    previous: dict[str, Any]
    current: dict[str, Any]
    status: str
    error_code: str
