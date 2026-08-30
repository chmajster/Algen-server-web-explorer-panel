from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class DirectoryType(StrEnum):
    ldap = "ldap"
    active_directory = "active_directory"
    freeipa = "freeipa"
    generic = "generic"


class SecurityMode(StrEnum):
    ldap = "ldap"
    starttls = "starttls"
    ldaps = "ldaps"


class ConnectionServer(BaseModel):
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=389, ge=1, le=65535)
    priority: int = Field(default=10, ge=0, le=65535)

    @field_validator("host")
    @classmethod
    def trim_host(cls, value: str) -> str:
        return value.strip()


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    directory_type: DirectoryType = DirectoryType.generic
    servers: list[ConnectionServer] = Field(min_length=1, max_length=32)
    security_mode: SecurityMode = SecurityMode.starttls
    verify_tls: bool = True
    ca_certificate: str = Field(default="", max_length=131072)
    base_dn: str = Field(min_length=1, max_length=2048)
    bind_dn: str = Field(min_length=1, max_length=2048)
    bind_password: str = Field(default="", max_length=32768)
    clear_bind_password: bool = False
    connect_timeout: float = Field(default=5.0, ge=0.5, le=60.0)
    operation_timeout: float = Field(default=15.0, ge=0.5, le=120.0)

    @field_validator("name", "base_dn", "bind_dn")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_secret(self) -> "ConnectionInput":
        if self.bind_password and self.clear_bind_password:
            raise ValueError("bind_password and clear_bind_password cannot be used together")
        return self


class SearchRequest(BaseModel):
    base_dn: str = Field(default="", max_length=2048)
    scope: Literal["base", "one", "subtree"] = "subtree"
    ldap_filter: str = Field(default="(objectClass=*)", min_length=1, max_length=4096)
    attributes: list[str] = Field(default_factory=lambda: ["*"], max_length=128)
    page_size: int = Field(default=100, ge=1, le=1000)
    cookie: str = Field(default="", max_length=8192)


class DirectoryCreateRequest(BaseModel):
    dn: str = Field(min_length=1, max_length=2048)
    object_classes: list[str] = Field(min_length=1, max_length=64)
    attributes: dict[str, Any] = Field(default_factory=dict)


class DirectoryUpdateRequest(BaseModel):
    attributes: dict[str, Any] = Field(default_factory=dict)
    delete_attributes: list[str] = Field(default_factory=list, max_length=128)


class DirectoryMoveRequest(BaseModel):
    new_rdn: str = Field(min_length=1, max_length=512)
    new_superior: str = Field(default="", max_length=2048)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=4096)
    force_change: bool = False


class MembershipRequest(BaseModel):
    member_dn: str = Field(min_length=1, max_length=2048)


class BulkOperationRequest(BaseModel):
    action: Literal["add_to_group", "remove_from_group", "enable", "disable", "move", "export"]
    target_dns: list[str] = Field(min_length=1, max_length=5000)
    group_dn: str = Field(default="", max_length=2048)
    new_parent_dn: str = Field(default="", max_length=2048)
    dry_run: bool = True


class CsvImportRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=10_000_000)
    dry_run: bool = True
    default_parent_dn: str = Field(default="", max_length=2048)


class LdifImportRequest(BaseModel):
    ldif_text: str = Field(min_length=1, max_length=10_000_000)
    dry_run: bool = True


class DiagnosticsRequest(BaseModel):
    include_schema: bool = False
