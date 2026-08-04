from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


MODULE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
IMPORT_PATH = re.compile(r"^app(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+:[a-zA-Z_][a-zA-Z0-9_]*$")


class ModuleState(StrEnum):
    active = "active"
    disabled = "disabled"
    unavailable = "unavailable"
    broken = "broken"


class ModuleMenuItem(BaseModel):
    id: str
    label: str
    icon: str
    permission: str | None = None
    hidden: bool = False


class ModuleManifest(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    category: str
    icon: str
    permissions: list[str] = Field(default_factory=list)
    routers: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    system_capabilities: list[str] = Field(default_factory=list)
    menu: list[ModuleMenuItem] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not MODULE_ID.fullmatch(value):
            raise ValueError("module id must use lowercase kebab-case")
        return value

    @field_validator("dependencies")
    @classmethod
    def valid_dependencies(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not MODULE_ID.fullmatch(value) for value in values):
            raise ValueError("module dependencies must be unique module ids")
        return values

    @field_validator("routers")
    @classmethod
    def valid_routers(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not IMPORT_PATH.fullmatch(value) for value in values):
            raise ValueError("router references must be unique app.module:attribute paths")
        return values

    @classmethod
    def from_yaml(cls, path: Path) -> ModuleManifest:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("module manifest must be an object")
        return cls.model_validate(value)
