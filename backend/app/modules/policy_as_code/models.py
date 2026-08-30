from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


POLICY_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
RULE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$")
PolicyFormat = Literal["yaml", "json"]
PolicySeverity = Literal["critical", "high", "medium", "low", "info"]


class PolicyMetadata(BaseModel):
    name: str
    description: str = Field(default="", max_length=2048)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not POLICY_ID.fullmatch(value):
            raise ValueError("metadata.name must use lowercase kebab-case")
        return value

    @field_validator("labels")
    @classmethod
    def valid_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 32:
            raise ValueError("metadata.labels supports at most 32 entries")
        if any(not key or len(key) > 64 or len(item) > 256 for key, item in value.items()):
            raise ValueError("metadata.labels contains an invalid key or value")
        return value


class PolicyRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    description: str = Field(default="", max_length=2048)
    severity: PolicySeverity = "medium"
    message: str = Field(default="", max_length=2048)
    assertion: dict[str, Any] = Field(alias="assert")

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not RULE_ID.fullmatch(value):
            raise ValueError("rule id contains unsupported characters")
        return value


class PolicySpec(BaseModel):
    enabled: bool = True
    rules: list[PolicyRule] = Field(min_length=1, max_length=512)

    @field_validator("rules")
    @classmethod
    def unique_rules(cls, value: list[PolicyRule]) -> list[PolicyRule]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return value


class PolicyDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: Literal["webnas/v1"] = Field(alias="apiVersion")
    kind: Literal["PolicySet"]
    metadata: PolicyMetadata
    spec: PolicySpec


class PolicySourceRequest(BaseModel):
    format: PolicyFormat
    source: str = Field(min_length=1, max_length=262_144)


class PolicyEvaluateRequest(BaseModel):
    policy_id: str | None = None
    format: PolicyFormat | None = None
    source: str | None = Field(default=None, max_length=262_144)
    facts: dict[str, Any] = Field(default_factory=dict)

    @field_validator("policy_id")
    @classmethod
    def valid_policy_id(cls, value: str | None) -> str | None:
        if value is not None and not POLICY_ID.fullmatch(value):
            raise ValueError("policy_id must use lowercase kebab-case")
        return value

    @model_validator(mode="after")
    def valid_source_choice(self) -> PolicyEvaluateRequest:
        if self.policy_id is not None and self.source is not None:
            raise ValueError("policy_id and source are mutually exclusive")
        if self.source is not None and self.format is None:
            raise ValueError("format is required when source is supplied")
        if self.source is None and self.format is not None:
            raise ValueError("format requires source")
        return self
