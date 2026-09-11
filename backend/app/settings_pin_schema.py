from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel


APP_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


def _validated_app_id(value: str) -> str:
    if not APP_ID_RE.fullmatch(value):
        raise ValueError("pinned application identifiers are invalid")
    return value


PinnedApplicationId = Annotated[str, AfterValidator(_validated_app_id)]


def _replace_field(model: type[BaseModel], field_name: str, annotation: object) -> None:
    field = model.model_fields[field_name]
    field.annotation = annotation


def enable_dynamic_application_ids(user_settings: type[BaseModel], patch: type[BaseModel]) -> None:
    """Keep desktop pin validation aligned with the dynamic frontend registry.

    The frontend registry intentionally uses string application IDs because installable
    modules are discovered at build/runtime boundaries. Older settings models retained
    a closed Literal list, causing valid newer IDs (for example ``cron``) to fail with
    HTTP 422. Rebuild only the affected Pydantic fields with the same bounded ID format
    already used for module identifiers.
    """

    for field_name in ("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps"):
        _replace_field(user_settings, field_name, list[PinnedApplicationId])
        _replace_field(patch, field_name, list[PinnedApplicationId] | None)
    user_settings.model_rebuild(force=True)
    patch.model_rebuild(force=True)
