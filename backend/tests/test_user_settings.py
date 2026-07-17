from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app import settings


def request(language: str = "en-US") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/settings/me", "headers": [(b"accept-language", language.encode())]})


def test_defaults_cover_every_user_preference():
    values = settings._normalize_user_settings({}, default_language="en-US")

    assert values["language"] == "en-US"
    assert values["theme"] == "system"
    assert values["taskbar_alignment"] == "center"
    assert values["pinned_apps"] == ["files", "transfers", "monitor", "settings"]
    assert values["start_pinned_apps"] == values["pinned_apps"]
    assert values["desktop_shortcut_apps"] == values["pinned_apps"]
    assert values["file_page_size"] == 50
    assert values["notification_limit"] == 5
    assert values["animations_enabled"] is True


def test_old_settings_file_keeps_valid_fields_and_repairs_invalid_fields(monkeypatch):
    monkeypatch.setattr(settings, "_read_settings", lambda username: {
        "language": "pl-PL",
        "theme": "dark",
        "startup_windows": "last",
        "wallpaper": "https://example.com/wallpaper.jpg",
        "notification_limit": 999,
        "legacy_unknown_field": "ignored",
    })
    monkeypatch.setattr(settings, "_user_info", lambda username: {"username": username, "is_admin": False})

    result = settings.settings_me(request(), SimpleNamespace(username="alice"))

    assert result["language"] == "pl-PL"
    assert result["theme"] == "dark"
    assert result["wallpaper"] == "https://example.com/wallpaper.jpg"
    assert result["notification_limit"] == 5
    assert "legacy_unknown_field" not in result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("accent_color", "expression(alert(1))"),
        ("taskbar_alignment", "right"),
        ("interface_scale", 500),
        ("file_page_size", 20),
        ("notification_limit", 0),
        ("wallpaper", "javascript:alert(1)"),
        ("pinned_apps", ["files", "unknown-app"]),
        ("pinned_apps", ["files", "files"]),
        ("start_pinned_apps", ["files", "files"]),
        ("desktop_shortcut_apps", ["unknown-app"]),
    ],
)
def test_patch_rejects_invalid_preferences(field, value):
    with pytest.raises(ValidationError):
        settings.MePatch(**{field: value})


def test_settings_are_written_and_read_atomically_per_user(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path))))
    payload = settings.UserSettings(theme="dark", file_page_size=100).model_dump()

    settings._write_settings("alice", payload)

    assert settings._read_settings("alice") == payload
    assert not (tmp_path / "settings" / "alice.tmp").exists()
    assert not (tmp_path / "settings" / "bob.json").exists()


def test_legacy_pins_are_migrated_to_each_destination():
    values = settings._normalize_user_settings({"pinned_apps": ["files", "monitor"]})

    assert values["pinned_apps"] == ["files", "monitor"]
    assert values["start_pinned_apps"] == ["files", "monitor"]
    assert values["desktop_shortcut_apps"] == ["files", "monitor"]


def test_patch_merges_a_partial_legacy_file(monkeypatch):
    written = {}
    monkeypatch.setattr(settings, "_read_settings", lambda username: {"theme": "dark", "startup_windows": "none"})
    monkeypatch.setattr(settings, "_write_settings", lambda username, data: written.update(data))
    monkeypatch.setattr(settings, "_user_info", lambda username: {"username": username, "is_admin": False})

    result = settings.settings_patch(settings.MePatch(taskbar_alignment="left"), SimpleNamespace(username="alice"))

    assert written["theme"] == "dark"
    assert written["startup_windows"] == "none"
    assert written["taskbar_alignment"] == "left"
    assert result["username"] == "alice"
