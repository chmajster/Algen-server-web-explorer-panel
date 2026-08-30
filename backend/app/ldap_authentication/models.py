from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..identity.models import Role


class LdapSecurityMode(StrEnum):
    ldap = "ldap"
    starttls = "starttls"
    ldaps = "ldaps"


class LdapFailoverStrategy(StrEnum):
    priority = "priority"
    round_robin = "round_robin"


class LdapDirectoryType(StrEnum):
    auto = "auto"
    ldap = "ldap"
    active_directory = "active_directory"
    freeipa = "freeipa"


class LdapServerInput(BaseModel):
    id: str = Field(default="", max_length=64)
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=389, ge=1, le=65535)
    priority: int = Field(default=10, ge=0, le=65535)
    enabled: bool = True

    @field_validator("id", "host")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()


class LdapAuthenticationSettingsInput(BaseModel):
    enabled: bool = False
    directory_type: LdapDirectoryType = LdapDirectoryType.auto
    servers: list[LdapServerInput] = Field(default_factory=list, max_length=32)
    # Legacy single-server fields remain accepted only for a lossless upgrade.
    server: str = Field(default="", max_length=512)
    port: int = Field(default=389, ge=1, le=65535)
    failover_strategy: LdapFailoverStrategy = LdapFailoverStrategy.priority
    dns_srv_domain: str = Field(default="", max_length=512)
    security_mode: LdapSecurityMode = LdapSecurityMode.starttls
    verify_tls: bool = True
    ca_certificate: str = Field(default="", max_length=131072)
    connect_timeout: float = Field(default=5.0, ge=0.5, le=60.0)
    operation_timeout: float = Field(default=10.0, ge=0.5, le=120.0)
    base_dn: str = Field(default="", max_length=2048)
    user_search_base: str = Field(default="", max_length=2048)
    user_search_filter: str = Field(default="(uid={username})", max_length=4096)
    username_attribute: str = Field(default="uid", min_length=1, max_length=128)
    immutable_id_attribute: str = Field(default="", max_length=128)
    bind_dn: str = Field(default="", max_length=2048)
    bind_password: str = Field(default="", max_length=32768)
    clear_bind_password: bool = False
    display_name_attribute: str = Field(default="displayName", max_length=128)
    email_attribute: str = Field(default="mail", max_length=128)
    group_search_base: str = Field(default="", max_length=2048)
    group_search_filter: str = Field(
        default="(|(member={dn})(uniqueMember={dn})(memberUid={username}))",
        max_length=4096,
    )
    group_membership_attribute: str = Field(default="memberOf", max_length=128)
    group_cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)

    @field_validator(
        "server",
        "dns_srv_domain",
        "base_dn",
        "user_search_base",
        "user_search_filter",
        "username_attribute",
        "immutable_id_attribute",
        "bind_dn",
        "display_name_attribute",
        "email_attribute",
        "group_search_base",
        "group_search_filter",
        "group_membership_attribute",
    )
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_configuration(self) -> "LdapAuthenticationSettingsInput":
        if self.clear_bind_password and self.bind_password:
            raise ValueError("bind_password and clear_bind_password cannot be used together")
        if self.user_search_filter.count("{username}") != 1:
            raise ValueError("LDAP user search filter must contain {username} exactly once")
        if self.group_search_filter and not ({"{username}", "{dn}"} & set(
            token for token in ("{username}", "{dn}") if token in self.group_search_filter
        )):
            raise ValueError("LDAP group search filter must contain {username} or {dn}")
        configured_servers = [item for item in self.servers if item.enabled]
        if not configured_servers and self.server:
            configured_servers = [LdapServerInput(host=self.server, port=self.port)]
        if self.enabled:
            missing: list[str] = []
            if not configured_servers and not self.dns_srv_domain:
                missing.append("servers")
            for name, value in (
                ("base_dn", self.base_dn),
                ("user_search_base", self.user_search_base),
                ("bind_dn", self.bind_dn),
            ):
                if not value:
                    missing.append(name)
            if missing:
                raise ValueError(f"LDAP authentication configuration is incomplete: {', '.join(missing)}")
        return self


class LdapGroupMappingInput(BaseModel):
    group_dn: str = Field(min_length=1, max_length=2048)
    role: Role = Role.user
    allow: list[str] = Field(default_factory=list, max_length=256)
    deny: list[str] = Field(default_factory=list, max_length=256)
    priority: int = Field(default=100, ge=0, le=65535)

    @field_validator("group_dn")
    @classmethod
    def trim_dn(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def disjoint(self) -> "LdapGroupMappingInput":
        overlap = set(self.allow) & set(self.deny)
        if overlap:
            raise ValueError(f"permissions cannot be both allowed and denied: {', '.join(sorted(overlap))}")
        return self


class LdapAccessPolicyInput(BaseModel):
    mode: Literal["allow_all", "mapped_groups"] = "allow_all"
    allow_groups: list[str] = Field(default_factory=list, max_length=256)
    deny_groups: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("allow_groups", "deny_groups")
    @classmethod
    def normalize_dns(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result


class LdapDiagnosticsRequest(BaseModel):
    username: str = Field(default="", max_length=256)


class LdapRefreshRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)


class LdapDiagnosticStep(BaseModel):
    name: str
    status: Literal["ok", "warning", "error", "skipped"]
    detail: str = ""


class LdapDiagnosticsResult(BaseModel):
    overall: Literal["healthy", "degraded", "unhealthy"]
    server: str = ""
    steps: list[LdapDiagnosticStep]
    identity: dict[str, str | int | None] = Field(default_factory=dict)
