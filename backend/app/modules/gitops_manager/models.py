from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RepositoryInput(BaseModel):
    remote: str = Field(default="", max_length=2048)
    branch: str = Field(default="main", min_length=1, max_length=128)
    confirm: bool = False

    @field_validator("branch")
    @classmethod
    def branch_name(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("-") or ".." in value or any(ch.isspace() for ch in value) or any(ch in value for ch in "~^:?*[\\"):
            raise ValueError("invalid Git branch")
        return value

    @field_validator("remote")
    @classmethod
    def remote_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        if "@" in value.split("://", 1)[-1].split("/", 1)[0]:
            raise ValueError("credentials in Git remote URLs are not allowed; use Secrets Manager/SSH agent")
        if not (value.startswith("https://") or value.startswith("ssh://") or value.startswith("git@")):
            raise ValueError("only HTTPS or SSH Git remotes are allowed")
        return value


class CommitInput(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    push: bool = False
    confirm: bool = False


class RefInput(BaseModel):
    ref: str = Field(min_length=1, max_length=128)
    confirm: bool = False


class FileRestoreInput(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    ref: str = Field(default="HEAD", min_length=1, max_length=128)
    confirm: bool = False
