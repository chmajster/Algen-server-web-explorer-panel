from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated, Any, cast, get_args

from pydantic import AfterValidator, BaseModel, StringConstraints

APP_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
MODULE_APP_ALIASES = {
    "ansible-controller": "ansible",
    "docker": "containers",
    "hosts-manager": "hosts",
}


def _allowed_app_ids(settings_module: object, module_ids: Iterable[str]) -> frozenset[str]:
    pinned_type = getattr(settings_module, "PinnedAppId")
    core_ids = {value for value in get_args(pinned_type) if isinstance(value, str)}
    discovered = {value for value in module_ids if re.fullmatch(APP_ID_PATTERN, value)}
    aliases = {MODULE_APP_ALIASES[value] for value in discovered if value in MODULE_APP_ALIASES}
    return frozenset(core_ids | discovered | aliases)


def _app_list_annotation(allowed: frozenset[str], *, optional: bool) -> type[Any]:
    def registered(value: str) -> str:
        if value not in allowed:
            raise ValueError("unknown application identifier")
        return value

    app_id = Annotated[
        str,
        StringConstraints(pattern=APP_ID_PATTERN),
        AfterValidator(registered),
    ]
    list_annotation = list[app_id]  # type: ignore[valid-type]
    return cast(type[Any], list_annotation | None if optional else list_annotation)


def _replace_list_annotation(
    model: type[BaseModel],
    field_name: str,
    allowed: frozenset[str],
    *,
    optional: bool,
) -> None:
    model.model_fields[field_name].annotation = _app_list_annotation(allowed, optional=optional)


def enable_dynamic_app_ids(settings_module: object, module_ids: Iterable[str] = ()) -> None:
    """Align settings validation with the manifest-based application registry.

    Core application ids remain valid. Discovered backend module ids and the
    small set of frontend aliases are added to that allow-list, while arbitrary
    strings are still rejected. This keeps settings strict without requiring a
    new backend release every time a same-id managed module is added.
    """
    allowed = _allowed_app_ids(settings_module, module_ids)
    user_settings = getattr(settings_module, "UserSettings")
    me_patch = getattr(settings_module, "MePatch")
    field_names = ("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps")
    for field_name in field_names:
        _replace_list_annotation(user_settings, field_name, allowed, optional=False)
        _replace_list_annotation(me_patch, field_name, allowed, optional=True)
    user_settings.model_rebuild(force=True)
    me_patch.model_rebuild(force=True)
