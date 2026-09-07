from pathlib import Path

import pytest
from pydantic import ValidationError

from app import shell_preferences as shell


def test_shell_preferences_round_trip_is_per_user_and_atomic(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(shell, "_root", lambda: tmp_path)
    value = shell.ShellPreferences(
        desktop_entries=[
            shell.DesktopEntry(
                id="app:files",
                kind="app",
                name="Files",
                target="files",
                position=shell.Point(x=4, y=8),
                created_at=1,
            )
        ],
        taskbar_order=["files", "settings"],
    )
    shell._save("alice", value)
    loaded = shell._load("alice")
    assert loaded == value
    assert shell._load("bob") == shell.ShellPreferences()
    assert (tmp_path / "alice.json").exists()


def test_shell_preferences_reject_duplicate_order_entries():
    with pytest.raises(ValidationError):
        shell.ShellPreferences(taskbar_order=["files", "files"])


def test_shell_preferences_reject_unsafe_identifiers_and_nul_targets():
    with pytest.raises(ValidationError):
        shell.DesktopEntry(
            id="../../etc/passwd",
            kind="file",
            name="bad",
            target="/tmp/a",
            position=shell.Point(x=0, y=0),
        )
    with pytest.raises(ValidationError):
        shell.DesktopEntry(
            id="file:one",
            kind="file",
            name="bad",
            target="/tmp/a\x00b",
            position=shell.Point(x=0, y=0),
        )


def test_shell_preferences_bounds_desktop_and_window_state():
    with pytest.raises(ValidationError):
        shell.Point(x=-1, y=0)
    with pytest.raises(ValidationError):
        shell.WindowState(id="w", app="files", x=0, y=0, width=0, height=100)
