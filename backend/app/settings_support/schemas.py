from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


MAX_WALLPAPER_LENGTH = 2_000_000
MAX_WALLPAPER_FILE_SIZE = 10 * 1024 * 1024
MAX_WALLPAPER_FILES = 24
WALLPAPER_RE = re.compile(
    r"^(https?://[^\s\"'<>]{1,1800}|/api/settings/wallpapers/[a-f0-9]{32}|/wallpapers/[a-z0-9._-]{1,80}\.svg|data:image/(png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=]+)$"
)


class DesktopWidget(BaseModel):
    id: Literal["cpu", "ram", "disks", "transfers", "services", "alerts"]
    visible: bool = True
    x: int = Field(default=0, ge=0, le=11)
    y: int = Field(default=0, ge=0, le=20)
    width: int = Field(default=3, ge=2, le=12)
    height: int = Field(default=2, ge=1, le=6)


DEFAULT_DESKTOP_WIDGETS = [
    DesktopWidget(id="cpu", x=0, y=0, width=3, height=2),
    DesktopWidget(id="ram", x=3, y=0, width=3, height=2),
    DesktopWidget(id="disks", x=6, y=0, width=4, height=2),
    DesktopWidget(id="transfers", x=0, y=2, width=4, height=2),
    DesktopWidget(id="services", x=4, y=2, width=3, height=2),
    DesktopWidget(id="alerts", x=7, y=2, width=3, height=2),
]

PinnedAppId = Literal[
    "files",
    "transfers",
    "activity",
    "identity",
    "users",
    "groups",
    "mounts",
    "samba",
    "services",
    "store",
    "logs",
    "settings",
    "monitor",
    "modules",
    "access",
    "containers",
    "ansible",
    "module",
]
InterfaceFont = Literal["system", "segoe", "arial", "verdana", "tahoma", "georgia", "monospace"]
DEFAULT_PINNED_APPS: list[PinnedAppId] = ["files", "transfers", "monitor", "settings"]


def validate_wallpaper(value: str | None) -> str:
    if not value:
        return ""
    wallpaper = value.strip()
    if len(wallpaper) > MAX_WALLPAPER_LENGTH:
        raise ValueError("Wallpaper is too large")
    if not WALLPAPER_RE.fullmatch(wallpaper):
        raise ValueError("Wallpaper must be an http(s) image URL or a supported image data URL")
    return wallpaper


class UserSettings(BaseModel):
    language: Literal["pl-PL", "en-US"] = "pl-PL"
    theme: Literal["light", "dark", "system"] = "system"
    startup_windows: Literal["last", "none"] = "last"
    wallpaper: str = Field(default="", max_length=MAX_WALLPAPER_LENGTH)
    accent_color: Literal["blue", "teal", "green", "violet", "rose", "orange"] = "blue"
    wallpaper_fit: Literal["cover", "contain", "stretch", "center"] = "cover"
    taskbar_alignment: Literal["left", "center"] = "center"
    pinned_apps: list[PinnedAppId] = Field(default_factory=lambda: list(DEFAULT_PINNED_APPS), max_length=16)
    pinned_modules: list[str] = Field(default_factory=list, max_length=16)
    start_pinned_apps: list[PinnedAppId] = Field(default_factory=lambda: list(DEFAULT_PINNED_APPS), max_length=16)
    desktop_shortcut_apps: list[PinnedAppId] = Field(default_factory=lambda: list(DEFAULT_PINNED_APPS), max_length=16)
    show_desktop_shortcuts: bool = True
    desktop_shortcut_size: Literal["small", "medium", "large"] = "medium"
    show_welcome_widget: bool = True
    show_notifications: bool = True
    show_transfer_indicator: bool = True
    show_background_actions_indicator: bool = True
    window_transparency: bool = True
    animations_enabled: bool = True
    clock_show_seconds: bool = False
    date_format: Literal["locale", "short", "long", "iso"] = "short"
    time_format: Literal["12", "24"] = "24"
    interface_scale: int = Field(default=100, ge=50, le=200)
    interface_font: InterfaceFont = "system"
    larger_text: bool = False
    high_contrast: bool = False
    reduced_motion: bool = False
    strong_active_borders: bool = False
    always_show_focus: bool = False
    file_default_view: Literal["list", "grid", "large"] = "list"
    file_compact_rows: bool = False
    file_show_hidden: bool = False
    file_confirm_delete: bool = True
    file_confirm_overwrite: bool = True
    file_page_size: Literal[25, 50, 100, 200] = 50
    file_default_sort: Literal["name", "size", "type", "modified"] = "name"
    file_sort_direction: Literal["asc", "desc"] = "asc"
    file_remember_last_path: bool = True
    transfer_success_notifications: bool = True
    transfer_error_notifications: bool = True
    transfer_open_failed_details: bool = False
    transfer_remember_filter: bool = True
    notification_transfer: bool = True
    notification_errors: bool = True
    notification_admin: bool = True
    notification_auto_hide: bool = True
    notification_limit: int = Field(default=5, ge=1, le=10)
    first_day_of_week: Literal["monday", "sunday", "locale"] = "locale"
    widgets_enabled: bool = True
    desktop_widgets: list[DesktopWidget] = Field(default_factory=lambda: [item.model_copy() for item in DEFAULT_DESKTOP_WIDGETS], max_length=6)

    @field_validator("desktop_widgets")
    @classmethod
    def unique_widgets(cls, values: list[DesktopWidget]) -> list[DesktopWidget]:
        identifiers = [item.id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("desktop widget identifiers must be unique")
        return values

    @field_validator("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps")
    @classmethod
    def unique_pinned_apps(cls, values: list[PinnedAppId]) -> list[PinnedAppId]:
        if len(values) != len(set(values)):
            raise ValueError("pinned application identifiers must be unique")
        return values

    @field_validator("pinned_modules")
    @classmethod
    def valid_pinned_modules(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("pinned module identifiers must be unique")
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", value) for value in values):
            raise ValueError("pinned module identifiers are invalid")
        return values

    @field_validator("wallpaper")
    @classmethod
    def validate_wallpaper_value(cls, value: str) -> str:
        return validate_wallpaper(value)


class MePatch(BaseModel):
    language: Literal["pl-PL", "en-US"] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    startup_windows: Literal["last", "none"] | None = None
    wallpaper: str | None = Field(default=None, max_length=MAX_WALLPAPER_LENGTH)
    accent_color: Literal["blue", "teal", "green", "violet", "rose", "orange"] | None = None
    wallpaper_fit: Literal["cover", "contain", "stretch", "center"] | None = None
    taskbar_alignment: Literal["left", "center"] | None = None
    pinned_apps: list[PinnedAppId] | None = Field(default=None, max_length=16)
    pinned_modules: list[str] | None = Field(default=None, max_length=16)
    start_pinned_apps: list[PinnedAppId] | None = Field(default=None, max_length=16)
    desktop_shortcut_apps: list[PinnedAppId] | None = Field(default=None, max_length=16)
    show_desktop_shortcuts: bool | None = None
    desktop_shortcut_size: Literal["small", "medium", "large"] | None = None
    show_welcome_widget: bool | None = None
    show_notifications: bool | None = None
    show_transfer_indicator: bool | None = None
    show_background_actions_indicator: bool | None = None
    window_transparency: bool | None = None
    animations_enabled: bool | None = None
    clock_show_seconds: bool | None = None
    date_format: Literal["locale", "short", "long", "iso"] | None = None
    time_format: Literal["12", "24"] | None = None
    interface_scale: int | None = Field(default=None, ge=50, le=200)
    interface_font: InterfaceFont | None = None
    larger_text: bool | None = None
    high_contrast: bool | None = None
    reduced_motion: bool | None = None
    strong_active_borders: bool | None = None
    always_show_focus: bool | None = None
    file_default_view: Literal["list", "grid", "large"] | None = None
    file_compact_rows: bool | None = None
    file_show_hidden: bool | None = None
    file_confirm_delete: bool | None = None
    file_confirm_overwrite: bool | None = None
    file_page_size: Literal[25, 50, 100, 200] | None = None
    file_default_sort: Literal["name", "size", "type", "modified"] | None = None
    file_sort_direction: Literal["asc", "desc"] | None = None
    file_remember_last_path: bool | None = None
    transfer_success_notifications: bool | None = None
    transfer_error_notifications: bool | None = None
    transfer_open_failed_details: bool | None = None
    transfer_remember_filter: bool | None = None
    notification_transfer: bool | None = None
    notification_errors: bool | None = None
    notification_admin: bool | None = None
    notification_auto_hide: bool | None = None
    notification_limit: int | None = Field(default=None, ge=1, le=10)
    first_day_of_week: Literal["monday", "sunday", "locale"] | None = None
    widgets_enabled: bool | None = None
    desktop_widgets: list[DesktopWidget] | None = Field(default=None, max_length=6)

    @field_validator("desktop_widgets")
    @classmethod
    def unique_widgets(cls, values: list[DesktopWidget] | None) -> list[DesktopWidget] | None:
        if values is not None and len({item.id for item in values}) != len(values):
            raise ValueError("desktop widget identifiers must be unique")
        return values

    @field_validator("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps")
    @classmethod
    def unique_pinned_apps(cls, values: list[PinnedAppId] | None) -> list[PinnedAppId] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("pinned application identifiers must be unique")
        return values

    @field_validator("pinned_modules")
    @classmethod
    def valid_pinned_modules(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("pinned module identifiers must be unique")
        if values is not None and any(not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", value) for value in values):
            raise ValueError("pinned module identifiers are invalid")
        return values

    @field_validator("wallpaper")
    @classmethod
    def validate_wallpaper_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_wallpaper(value)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminPassword(BaseModel):
    confirm: bool = True


class AdminSessionAction(BaseModel):
    confirm: bool = True


class ShutdownAction(AdminSessionAction):
    delay_seconds: int = Field(default=10, ge=0, le=10)


class ShutdownPolicy(BaseModel):
    detailed_information: bool = False


class ServiceAction(BaseModel):
    confirm_restart: bool = False


class UpdateAction(AdminSessionAction):
    update_config: bool = False
    npm_audit_fix: bool = False


class UpdateCompletionAck(BaseModel):
    update_id: str = Field(min_length=1, max_length=128)


class AutoUpdatePatch(AdminSessionAction):
    check_enabled: bool = True
    enabled: bool
    interval_hours: int = Field(default=12, ge=1, le=168)
    update_config: bool = False
    npm_audit_fix: bool = False


class UserCreate(AdminPassword):
    username: str
    password: str
    groups: list[str] = Field(default_factory=list)
    shell: str | None = None
    gecos: str | None = None
    create_home: bool = True
    force_password_change: bool = False
    system: bool = False


class UserPatch(AdminPassword):
    groups_add: list[str] = Field(default_factory=list)
    groups_remove: list[str] = Field(default_factory=list)
    shell: str | None = None
    gecos: str | None = None
    create_home: bool = False
    force_password_change: bool | None = None


class AdminChangePassword(AdminPassword):
    new_password: str
    force_change: bool = False


class UserQuota(AdminPassword):
    soft_mb: int
    hard_mb: int | None = None
    mountpoint: str | None = None


class GroupCreate(AdminPassword):
    groupname: str
    system: bool = False


class GroupPatch(AdminPassword):
    new_name: str | None = None


class GroupMember(AdminPassword):
    username: str


class ChownRequest(AdminPassword):
    path: str
    owner: str | None = None
    group: str | None = None
