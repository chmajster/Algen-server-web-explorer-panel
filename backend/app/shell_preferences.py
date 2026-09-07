from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .config import get_config
from .security import SessionUser, get_session_user, require_csrf

router = APIRouter(prefix="/api/shell", tags=["shell"])
_lock = threading.RLock()
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")


class Point(BaseModel):
    x: int = Field(ge=0, le=100000)
    y: int = Field(ge=0, le=100000)


class Size(BaseModel):
    width: int = Field(ge=1, le=100000)
    height: int = Field(ge=1, le=100000)


class DesktopEntry(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    kind: Literal["app", "module", "file", "directory", "url", "folder"]
    name: str = Field(min_length=1, max_length=240)
    target: str = Field(default="", max_length=4096)
    position: Point = Field(default_factory=lambda: Point(x=0, y=0))
    parent_id: str | None = Field(default=None, max_length=256)
    created_at: int = Field(default=0, ge=0)

    @field_validator("id", "parent_id")
    @classmethod
    def valid_identifier(cls, value: str | None) -> str | None:
        if value is not None and not SAFE_ID.fullmatch(value):
            raise ValueError("invalid shell identifier")
        return value

    @field_validator("target")
    @classmethod
    def safe_target(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("invalid target")
        return value


class WidgetState(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    position: Point
    size: Size
    visible: bool = True

    @field_validator("id")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("invalid widget identifier")
        return value


class WindowState(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    app: str = Field(min_length=1, max_length=80)
    x: int = Field(ge=-100000, le=100000)
    y: int = Field(ge=-100000, le=100000)
    width: int = Field(ge=1, le=100000)
    height: int = Field(ge=1, le=100000)
    minimized: bool = False
    maximized: bool = False
    initial_path: str | None = Field(default=None, max_length=4096)
    module_id: str | None = Field(default=None, max_length=80)


class ShellPreferences(BaseModel):
    version: int = Field(default=1, ge=1, le=100)
    desktop: dict = Field(default_factory=dict)
    desktop_entries: list[DesktopEntry] = Field(default_factory=list, max_length=512)
    taskbar_order: list[str] = Field(default_factory=list, max_length=128)
    start_order: list[str] = Field(default_factory=list, max_length=256)
    start_hidden: list[str] = Field(default_factory=list, max_length=256)
    recent_files: list[str] = Field(default_factory=list, max_length=50)
    windows: list[WindowState] = Field(default_factory=list, max_length=64)
    widgets: list[WidgetState] = Field(default_factory=list, max_length=64)
    notifications: dict = Field(default_factory=dict)
    mobile: dict = Field(default_factory=dict)

    @field_validator("taskbar_order", "start_order", "start_hidden")
    @classmethod
    def valid_id_lists(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate identifiers")
        if any(not SAFE_ID.fullmatch(value) for value in values):
            raise ValueError("invalid identifier")
        return values

    @field_validator("recent_files")
    @classmethod
    def valid_recent_files(cls, values: list[str]) -> list[str]:
        if any("\x00" in value or len(value) > 4096 for value in values):
            raise ValueError("invalid recent file path")
        return values


def _root() -> Path:
    path = Path(get_config().paths.data_dir) / "shell-preferences"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _path(username: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", username)[:128]
    if not safe:
        raise HTTPException(400, "Invalid username")
    return _root() / f"{safe}.json"


def _load(username: str) -> ShellPreferences:
    path = _path(username)
    if not path.exists():
        return ShellPreferences()
    try:
        return ShellPreferences.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ShellPreferences()


def _save(username: str, value: ShellPreferences) -> None:
    path = _path(username)
    payload = value.model_dump_json(indent=2)
    with _lock:
        fd, temp_name = tempfile.mkstemp(prefix=".shell-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


@router.get("/preferences", response_model=ShellPreferences)
def get_shell_preferences(user: SessionUser = Depends(get_session_user)) -> ShellPreferences:
    return _load(user.username)


@router.put("/preferences", response_model=ShellPreferences)
def put_shell_preferences(
    payload: ShellPreferences,
    request: Request,
    user: SessionUser = Depends(get_session_user),
) -> ShellPreferences:
    require_csrf(request, user)
    _save(user.username, payload)
    return payload
