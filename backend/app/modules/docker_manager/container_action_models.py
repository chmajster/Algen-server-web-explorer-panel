from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import DockerModel, _identifier, _image


class ContainerActionRequest(DockerModel):
    action: Literal[
        "start",
        "stop",
        "restart",
        "pause",
        "unpause",
        "kill",
        "rename",
        "remove",
        "duplicate",
        "recreate",
        "check_update",
        "update",
    ]
    timeout: int | None = None
    signal: Literal["KILL", "TERM", "HUP", "INT", "QUIT", "USR1", "USR2"] = "KILL"
    force: bool = False
    new_name: str | None = None
    image: str | None = None
    confirmation: str = ""
    pam_password: str | None = Field(default=None, max_length=1024)

    @field_validator("new_name")
    @classmethod
    def valid_new_name(cls, value: str | None) -> str | None:
        return _identifier(value, "container name") if value else None

    @field_validator("image")
    @classmethod
    def valid_image(cls, value: str | None) -> str | None:
        return _image(value) if value else None

    @model_validator(mode="after")
    def required_fields(self) -> "ContainerActionRequest":
        if self.action in {"rename", "duplicate"} and not self.new_name:
            raise ValueError("new container name is required")
        return self
