import json
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
    assert values["pinned_modules"] == []
    assert values["start_pinned_apps"] == values["pinned_apps"]
    assert values["desktop_shortcut_apps"] == values["pinned_apps"]
    assert values["file_page_size"] == 50
    assert values["notification_limit"] == 5
    assert values["animations_enabled"] is True


def test_update_policy_checks_every_twelve_hours_by_default():
    state = settings._default_auto_update_state()

    assert state["check_enabled"] is True
    assert state["enabled"] is False
    assert state["interval_hours"] == 12


def test_scheduled_update_check_does_not_install_when_policy_requires_approval(monkeypatch):
    state = settings._default_auto_update_state()
    written = []
    monkeypatch.setattr(settings, "_read_auto_update_state", lambda: dict(state))
    monkeypatch.setattr(settings, "_update_status", lambda: {"available": True, "update_available": True})
    monkeypatch.setattr(settings, "_write_auto_update_state", lambda value: written.append(dict(value)) or value)
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: pytest.fail("automatic installation must remain disabled"))

    result = settings._run_auto_update_once()

    assert result["update_available"] is True
    assert result["updated"] is False
    assert written[-1]["next_check"] - written[-1]["last_checked"] == 12 * 3600


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
        ("pinned_modules", ["linux-updates", "linux-updates"]),
        ("pinned_modules", ["../../invalid"]),
        ("start_pinned_apps", ["files", "files"]),
        ("desktop_shortcut_apps", ["unknown-app"]),
    ],
)
def test_patch_rejects_invalid_preferences(field, value):
    with pytest.raises(ValidationError):
        settings.MePatch(**{field: value})


def test_wallpaper_validator_accepts_gallery_urls_and_rejects_unsafe_local_paths():
    uploaded = f"/api/settings/wallpapers/{'a' * 32}"

    assert settings._validate_wallpaper("/wallpapers/aurora.svg") == "/wallpapers/aurora.svg"
    assert settings._validate_wallpaper(uploaded) == uploaded
    with pytest.raises(settings.HTTPException):
        settings._validate_wallpaper("/wallpapers/../../etc/passwd")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\x89PNG\r\n\x1a\npayload", (".png", "image/png")),
        (b"\xff\xd8\xffpayload", (".jpg", "image/jpeg")),
        (b"GIF89apayload", (".gif", "image/gif")),
        (b"RIFF\x00\x00\x00\x00WEBPpayload", (".webp", "image/webp")),
    ],
)
def test_wallpaper_format_uses_file_signatures(payload, expected):
    assert settings._wallpaper_format(payload) == expected


def test_wallpaper_gallery_is_private_per_user(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path))))
    wallpaper_id = "b" * 32
    alice_directory = settings._wallpaper_directory("alice")
    (alice_directory / f"{wallpaper_id}.png").write_bytes(b"\x89PNG\r\n\x1a\npayload")
    (alice_directory / f"{wallpaper_id}.json").write_text(
        json.dumps({"name": "Moja tapeta.png", "created_at": 123, "media_type": "image/png"}),
        encoding="utf-8",
    )

    assert settings._wallpaper_items("alice") == [{
        "id": wallpaper_id,
        "name": "Moja tapeta.png",
        "url": f"/api/settings/wallpapers/{wallpaper_id}",
        "size": 15,
        "created_at": 123,
    }]
    assert settings._wallpaper_items("bob") == []


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


def test_patch_persists_each_application_pin_destination(monkeypatch):
    written = {}
    monkeypatch.setattr(settings, "_read_settings", lambda username: {})
    monkeypatch.setattr(settings, "_write_settings", lambda username, data: written.update(data))
    monkeypatch.setattr(settings, "_user_info", lambda username: {"username": username, "is_admin": False})

    settings.settings_patch(
        settings.MePatch(
            pinned_apps=["files"],
            pinned_modules=["linux-updates", "pihole"],
            start_pinned_apps=["monitor"],
            desktop_shortcut_apps=["settings"],
        ),
        SimpleNamespace(username="alice"),
    )

    assert written["pinned_apps"] == ["files"]
    assert written["pinned_modules"] == ["linux-updates", "pihole"]
    assert written["start_pinned_apps"] == ["monitor"]
    assert written["desktop_shortcut_apps"] == ["settings"]


def test_update_status_uses_installed_revision_without_git_checkout(monkeypatch, tmp_path):
    revision = "a" * 40
    (tmp_path / ".webnas-revision").write_text(revision + "\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "webnas"\nversion = "1.4.2"\n', encoding="utf-8")
    monkeypatch.setattr(settings, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "_git_output", lambda args: f"{revision}\trefs/heads/main")
    monkeypatch.setattr(settings, "_remote_release_timestamp", lambda value: 1_720_000_000)
    monkeypatch.setattr(settings, "_remote_publication_version", lambda value: "1.5.0")

    result = settings._update_status()

    assert result == {"branch": "main", "local": revision, "remote": revision, "installed_version": "1.4.2", "available_version": "1.5.0", "update_available": False, "available": True, "error": "", "source": settings.UPDATE_SOURCE, "source_url": settings.UPDATE_SOURCE_URL, "released_at": 1_720_000_000}


def test_legacy_install_without_revision_offers_initial_update(monkeypatch, tmp_path):
    remote = "b" * 40
    monkeypatch.setattr(settings, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "_git_output", lambda args: f"{remote}\trefs/heads/main")
    monkeypatch.setattr(settings, "_remote_release_timestamp", lambda value: None)
    monkeypatch.setattr(settings, "_remote_publication_version", lambda value: "2.0.0")

    result = settings._update_status()

    assert result["local"] == "unknown"
    assert result["remote"] == remote
    assert result["update_available"] is True


def test_remote_release_timestamp_reads_github_commit_date(monkeypatch):
    monkeypatch.setattr(settings, "_tool", lambda name: name)
    monkeypatch.setattr(settings.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"commit":{"committer":{"date":"2026-07-17T12:00:00Z"}}}'))

    result = settings._remote_release_timestamp("a" * 40)

    assert result == 1_784_289_600


def test_remote_publication_version_reads_exact_revision_pyproject(monkeypatch):
    monkeypatch.setattr(settings, "_tool", lambda name: name)
    monkeypatch.setattr(settings.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='[project]\nname = "webnas"\nversion = "2.3.1"\n'))

    result = settings._remote_publication_version("b" * 40)

    assert result == "2.3.1"


def test_update_starts_in_a_separate_durable_systemd_unit(monkeypatch, tmp_path):
    paths = SimpleNamespace(data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "log"))
    calls: list[list[str]] = []
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(paths=paths))
    monkeypatch.setattr(settings, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "_tool", lambda name: name)
    monkeypatch.setattr(settings, "_audit", lambda *args: None)

    def run(args, **kwargs):
        calls.append(args)
        if args[0] == "curl":
            return SimpleNamespace(returncode=0, stdout=b"#!/usr/bin/env bash\nexit 0\n", stderr=b"")
        progress_path = tmp_path / "data" / "settings" / "update_progress.json"
        current = json.loads(progress_path.read_text(encoding="utf-8"))
        current["pid"] = 456
        progress_path.write_text(json.dumps(current), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Running as unit", stderr="")

    monkeypatch.setattr(settings.subprocess, "run", run)

    result = settings._start_update_process(False, actor="admin")

    launch = next(args for args in calls if args[0] == "systemd-run")
    assert "--collect" in launch
    assert "--no-block" in launch
    assert any(value.startswith("webnas-self-update-") for value in launch)
    assert result["pid"] == 456
    runner = (tmp_path / "data" / "settings" / "update-runner.sh").read_text(encoding="utf-8")
    assert "exec >>" in runner
    assert '"running":false' in runner


def test_update_progress_reconnects_to_active_systemd_unit(monkeypatch, tmp_path):
    progress_path = tmp_path / "update_progress.json"
    progress_path.write_text('{"running":true,"exit_code":null,"started_at":10,"finished_at":null,"pid":456,"unit":"webnas-self-update-10.service"}', encoding="utf-8")
    monkeypatch.setattr(settings, "_update_progress_path", lambda: progress_path)
    monkeypatch.setattr(settings, "_read_auto_update_state", lambda: {"last_pid": None})
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(log_dir=str(tmp_path))))
    monkeypatch.setattr(settings, "_tool", lambda name: name)
    monkeypatch.setattr(settings.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    result = settings._update_progress()

    assert result["state"] == "running"
    assert result["pid"] == 456
    assert result["unit"] == "webnas-self-update-10.service"


def test_update_progress_returns_persistent_state_and_bounded_log(monkeypatch, tmp_path):
    progress_path = tmp_path / "update_progress.json"
    progress_path.write_text('{"running":false,"exit_code":0,"started_at":10,"finished_at":20}', encoding="utf-8")
    log_path = tmp_path / "update.log"
    log_path.write_text("prepare\ninstall\ncomplete\n", encoding="utf-8")
    monkeypatch.setattr(settings, "_update_progress_path", lambda: progress_path)
    monkeypatch.setattr(settings, "_read_auto_update_state", lambda: {"last_pid": 123})
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(log_dir=str(tmp_path))))

    result = settings._update_progress()

    assert result["state"] == "completed"
    assert result["pid"] == 123
    assert result["exit_code"] == 0
    assert result["lines"] == ["prepare", "install", "complete"]
