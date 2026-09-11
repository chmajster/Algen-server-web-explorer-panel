from __future__ import annotations

import pytest
from pydantic import ValidationError

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
