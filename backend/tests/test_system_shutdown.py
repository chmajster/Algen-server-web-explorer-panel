from contextlib import nullcontext
from types import SimpleNamespace

from app import settings


def test_shutdown_waits_for_copy_or_move_before_poweroff(monkeypatch):
    active = SimpleNamespace(type="copy", status=SimpleNamespace(value="running"))
    blockers = iter([[active], [], []])
    commands: list[list[str]] = []

    monkeypatch.setattr(settings, "_shutdown_blockers", lambda: next(blockers))
    monkeypatch.setattr(settings, "coordination_lock", nullcontext)
    monkeypatch.setattr(settings, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(settings, "_run", lambda command: commands.append(command))
    monkeypatch.setattr(settings.time, "sleep", lambda _seconds: None)
    settings._shutdown_generation = 7
    settings._shutdown_state = {"state": "scheduled", "deadline": 0, "blocker_count": 0, "requested_by": "admin", "error": ""}

    settings._shutdown_worker(7)

    assert commands == [["/usr/bin/systemctl", "poweroff"]]
    assert settings._shutdown_state["state"] == "shutting_down"


def test_shutdown_blockers_include_paused_transfers(monkeypatch):
    tasks = [
        SimpleNamespace(type="move", status=SimpleNamespace(value="paused")),
        SimpleNamespace(type="copy", status=SimpleNamespace(value="completed")),
        SimpleNamespace(type="delete", status=SimpleNamespace(value="running")),
    ]
    monkeypatch.setattr(settings.task_store, "list_all", lambda: tasks)

    assert settings._shutdown_blockers() == [tasks[0]]


def test_shutdown_information_policy_is_persisted(monkeypatch, tmp_path):
    path = tmp_path / "settings" / "shutdown_policy.json"
    monkeypatch.setattr(settings, "_shutdown_policy_path", lambda: path)

    assert settings._read_shutdown_policy().detailed_information is False
    settings._write_shutdown_policy(settings.ShutdownPolicy(detailed_information=True))

    assert settings._read_shutdown_policy().detailed_information is True
    assert path.is_file()
