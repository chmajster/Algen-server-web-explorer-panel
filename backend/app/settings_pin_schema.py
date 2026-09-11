from __future__ import annotations

import re
import sys
from typing import Annotated

from fastapi.dependencies.utils import (
    _should_embed_body_fields,
    get_body_field,
    get_dependant,
    get_flat_dependant,
    get_parameterless_sub_dependant,
)
from fastapi.routing import APIRoute, request_response
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


def _refresh_router_body_fields(model: type[BaseModel]) -> None:
    """Refresh FastAPI route adapters created before a Pydantic model rebuild.

    FastAPI snapshots request-body validators when an APIRoute is created. Rebuilding
    the Pydantic model alone therefore leaves already-decorated routes validating
    against the old Literal schema. The settings router is still an APIRouter at this
    point, so rebuilding its dependency/body metadata here makes later include_router()
    copies use the updated model without changing the public endpoint contract.
    """

    module = sys.modules.get(model.__module__)
    router = getattr(module, "router", None)
    routes = getattr(router, "routes", ())
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        dependant = get_dependant(path=route.path_format, call=route.endpoint, scope="function")
        for depends in route.dependencies[::-1]:
            dependant.dependencies.insert(
                0,
                get_parameterless_sub_dependant(depends=depends, path=route.path_format),
            )
        route.dependant = dependant
        route._flat_dependant = get_flat_dependant(dependant)
        route._embed_body_fields = _should_embed_body_fields(route._flat_dependant.body_params)
        route.body_field = get_body_field(
            flat_dependant=route._flat_dependant,
            name=route.unique_id,
            embed_body_fields=route._embed_body_fields,
        )
        route.app = request_response(route.get_route_handler())


def enable_dynamic_application_ids(user_settings: type[BaseModel], patch: type[BaseModel]) -> None:
    """Keep desktop pin validation aligned with the dynamic frontend registry.

    The frontend registry intentionally uses string application IDs because installable
    modules are discovered at build/runtime boundaries. Older settings models retained
    a closed Literal list, causing valid newer IDs (for example ``cron``) to fail with
    HTTP 422. Rebuild only the affected Pydantic fields with the same bounded ID format
    already used for module identifiers, then refresh FastAPI's already-created request
    adapters for the settings router.
    """

    for field_name in ("pinned_apps", "start_pinned_apps", "desktop_shortcut_apps"):
        _replace_field(user_settings, field_name, list[PinnedApplicationId])
        _replace_field(patch, field_name, list[PinnedApplicationId] | None)
    user_settings.model_rebuild(force=True)
    patch.model_rebuild(force=True)
    _refresh_router_body_fields(patch)
