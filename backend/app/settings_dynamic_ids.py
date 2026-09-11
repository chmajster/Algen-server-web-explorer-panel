from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

APP_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
DynamicAppId = Annotated[str, StringConstraints(pattern=APP_ID_PATTERN)]


def _replace_list_annotation(model: type[BaseModel], field_name: str, *, optional: bool) -> None:
    field = model.model_fields[field_name]
    field.annotation = list[DynamicAppId] | None if optional else list[DynamicAppId]


def enable_dynamic_app_ids(settings_module: object) -> None:
    """Align settings validation with the manifest-based frontend registry.

    Core applications used to be represented by a closed Literal in settings.py.
    WebNAS now discovers managed applications dynamically, so pin/start/desktop
    destinations must accept any safe manifest id rather than a hard-coded list.
    """
    user_settings = getattr(settings_module, "UserSettings")
    me_patch = getattr(settings_module, "MePatch")
    field_names = ("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps")
    for field_name in field_names:
        _replace_list_annotation(user_settings, field_name, optional=False)
        _replace_list_annotation(me_patch, field_name, optional=True)
    user_settings.model_rebuild(force=True)
    me_patch.model_rebuild(force=True)
