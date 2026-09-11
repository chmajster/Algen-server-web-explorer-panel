from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import BaseModel, ValidationError

from app import settings
from app.settings_pin_schema import enable_dynamic_application_ids


def test_dynamic_registry_application_ids_are_valid_desktop_pins():
    enable_dynamic_application_ids(settings.UserSettings, settings.MePatch)

    patch = settings.MePatch(
        pinned_apps=["files", "cron", "image-converter"],
        start_pinned_apps=["cron"],
        desktop_shortcut_apps=["image-converter"],
    )

    assert patch.pinned_apps == ["files", "cron", "image-converter"]
    assert patch.start_pinned_apps == ["cron"]
    assert patch.desktop_shortcut_apps == ["image-converter"]


def test_dynamic_registry_application_ids_remain_strictly_validated():
    enable_dynamic_application_ids(settings.UserSettings, settings.MePatch)

    with pytest.raises(ValidationError):
        settings.MePatch(pinned_apps=["files", "../../etc/passwd"])
    with pytest.raises(ValidationError):
        settings.MePatch(desktop_shortcut_apps=["Invalid App"])
    with pytest.raises(ValidationError):
        settings.MePatch(start_pinned_apps=["cron", "cron"])


def test_fastapi_route_adapter_uses_rebuilt_pin_schema(monkeypatch):
    # Route decorators in settings.py run before bootstrap enables dynamic app IDs.
    # This regression verifies the compatibility shim refreshes FastAPI's cached
    # body validator as well as the Pydantic model itself.
    enable_dynamic_application_ids(settings.UserSettings, settings.MePatch)
    monkeypatch.setattr(settings, "authorize", lambda user, permission: None)
    monkeypatch.setattr(settings, "_read_settings", lambda username: {})
    monkeypatch.setattr(settings, "_write_settings", lambda username, data: None)
    monkeypatch.setattr(settings, "_user_info", lambda username: {"username": username, "is_admin": False})

    app = FastAPI()
    app.include_router(settings.router)
    route = next(
        item for item in app.routes
        if getattr(item, "path", "") == "/api/settings/me" and "PATCH" in getattr(item, "methods", set())
    )
    body_field = getattr(route, "body_field", None)
    assert body_field is not None

    validated, errors = body_field.validate(
        {"pinned_apps": ["cron", "image-converter"]},
        {},
        loc=("body",),
    )
    assert errors is None
    assert isinstance(validated, BaseModel)
    assert validated.pinned_apps == ["cron", "image-converter"]

    _, invalid_errors = body_field.validate(
        {"pinned_apps": ["../../etc/passwd"]},
        {},
        loc=("body",),
    )
    assert invalid_errors
