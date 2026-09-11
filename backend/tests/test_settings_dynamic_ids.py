import pytest
from pydantic import ValidationError

from app import settings
from app.settings_dynamic_ids import enable_dynamic_app_ids


MODULE_IDS = {"dhcp", "cron", "apmid", "hosts-manager", "os-repositories"}


def test_dynamic_application_ids_are_accepted_for_user_destinations():
    enable_dynamic_app_ids(settings, MODULE_IDS)
    value = settings.UserSettings(
        pinned_apps=["files", "dhcp"],
        start_pinned_apps=["cron", "hosts"],
        desktop_shortcut_apps=["apmid", "os-repositories"],
    )
    assert value.pinned_apps == ["files", "dhcp"]
    assert value.start_pinned_apps == ["cron", "hosts"]
    assert value.desktop_shortcut_apps == ["apmid", "os-repositories"]


def test_dynamic_application_ids_remain_strictly_validated():
    enable_dynamic_app_ids(settings, MODULE_IDS)
    with pytest.raises(ValidationError):
        settings.UserSettings(pinned_apps=["../../etc/passwd"])
    with pytest.raises(ValidationError):
        settings.MePatch(start_pinned_apps=["bad id"])
    with pytest.raises(ValidationError):
        settings.MePatch(desktop_shortcut_apps=["unknown-app"])
    with pytest.raises(ValidationError):
        settings.MePatch(desktop_shortcut_apps=["files", "files"])
