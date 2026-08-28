from types import SimpleNamespace

from app import resource_dashboard
from app.log_system import sources


def test_resource_monitor_treats_active_blue_green_backend_as_active(monkeypatch):
    states = {
        "webnas-backend-blue.service": "inactive",
        "webnas-backend-green.service": "active",
        "webnas.service": "inactive",
    }
    calls: list[str] = []

    monkeypatch.setattr(resource_dashboard.shutil, "which", lambda command: "/usr/bin/systemctl")

    def fake_run(args, **kwargs):
        unit = args[-1]
        calls.append(unit)
        return SimpleNamespace(stdout=f"{states[unit]}\n")

    monkeypatch.setattr(resource_dashboard.subprocess, "run", fake_run)

    assert resource_dashboard.webnas_service_status() == "active"
    assert calls == ["webnas-backend-blue.service", "webnas-backend-green.service"]


def test_resource_monitor_falls_back_to_legacy_service(monkeypatch):
    states = {
        "webnas-backend-blue.service": "inactive",
        "webnas-backend-green.service": "inactive",
        "webnas.service": "active",
    }

    monkeypatch.setattr(resource_dashboard.shutil, "which", lambda command: "/usr/bin/systemctl")
    monkeypatch.setattr(
        resource_dashboard.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(stdout=f"{states[args[-1]]}\n"),
    )

    assert resource_dashboard.webnas_service_status() == "active"


def test_webnas_log_source_reads_blue_green_and_legacy_units(monkeypatch):
    captured: list[str] = []

    monkeypatch.setattr(sources.shutil, "which", lambda command: "/usr/bin/journalctl")

    def fake_run_bounded(args, **kwargs):
        captured.extend(args)
        return 0, "", ""

    monkeypatch.setattr(sources, "run_bounded", fake_run_bounded)

    result = sources.journal_entries(
        "webnas",
        limit=20,
        priority=[],
        unit="",
        pid=None,
        uid=None,
        identifier="",
        transport="",
        hostname="",
        device="",
        username="",
        group="",
        boot_id="",
        since=None,
        until=None,
        continuation={},
        direction="older",
    )

    assert result == []
    assert [captured[index + 1] for index, value in enumerate(captured[:-1]) if value == "--unit"] == [
        "webnas-backend-blue.service",
        "webnas-backend-green.service",
        "webnas.service",
    ]
