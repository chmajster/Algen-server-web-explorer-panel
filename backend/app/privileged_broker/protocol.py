from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROTOCOL_VERSION: Literal[1] = 1
MAX_FRAME_BYTES = 1024 * 1024
REQUEST_ID_RE = re.compile(r"^[a-f0-9]{32}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")


class Operation(StrEnum):
    SYSTEMD = "systemd"
    ACCOUNT = "account"
    OWNERSHIP = "ownership"
    MANAGED_FILE = "managed_file"
    POWER = "power"
    UPDATE_SERVICE = "update_service"
    PACKAGE = "package"


class BrokerRequest(BaseModel):
    """Versioned envelope. Operation-specific payload is validated again by policy."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = PROTOCOL_VERSION
    request_id: str = Field(min_length=32, max_length=32)
    actor: str = Field(min_length=1, max_length=128)
    operation: Operation
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id")
    @classmethod
    def valid_request_id(cls, value: str) -> str:
        if not REQUEST_ID_RE.fullmatch(value):
            raise ValueError("request_id must be 32 lowercase hexadecimal characters")
        return value

    @field_validator("actor")
    @classmethod
    def valid_actor(cls, value: str) -> str:
        if not ACTOR_RE.fullmatch(value):
            raise ValueError("actor contains unsupported characters")
        return value


class BrokerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = PROTOCOL_VERSION
    request_id: str
    ok: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    error_code: str | None = None


def encode_frame(model: BaseModel) -> bytes:
    payload = model.model_dump_json(exclude_none=True).encode("utf-8") + b"\n"
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("broker frame is too large")
    return payload
