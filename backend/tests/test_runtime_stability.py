from __future__ import annotations

from pathlib import Path

from app import run as run_module


REPOSITORY = Path(__file__).resolve().parents[2]


def test_runtime_watchdog_is_disabled_outside_supervised_install(monkeypatch):
    monkeypatch.delenv("WEBNAS_SLOT", raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WEBNAS_RUNTIME_WATCHDOG_SEC", raising=False)

    assert run_module._runtime_watchdog_timeout() is None


def test_blue_green_slot_enables_runtime_watchdog(monkeypatch):
    monkeypatch.setenv("WEBNAS_SLOT", "blue")
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setenv("WEBNAS_RUNTIME_WATCHDOG_SEC", "45")

    assert run_module._runtime_watchdog_timeout() == 45.0


def test_runtime_watchdog_has_safe_minimum_timeout(monkeypatch):
    monkeypatch.setenv("WEBNAS_SLOT", "green")
    monkeypatch.setenv("WEBNAS_RUNTIME_WATCHDOG_SEC", "1")

    assert run_module._runtime_watchdog_timeout() == 15.0


def test_runtime_watchdog_expiry_uses_monotonic_deadline():
    watchdog = run_module.RuntimeWatchdog(60.0)
    started = watchdog._last_heartbeat

    assert watchdog.expired(started + 60.0) is False
    assert watchdog.expired(started + 60.01) is True


def test_systemd_watchdog_interval_uses_half_of_configured_deadline(monkeypatch):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")

    assert run_module._watchdog_interval() == 30.0


def test_legacy_service_uses_systemd_watchdog_and_restart_limits():
    unit = (REPOSITORY / "packaging" / "webnas.service").read_text(encoding="utf-8")

    assert "Type=notify" in unit
    assert "NotifyAccess=main" in unit
    assert "WatchdogSec=60s" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=30" in unit
    assert "StartLimitIntervalSec=120" in unit
    assert "StartLimitBurst=4" in unit


def test_blue_green_environment_arms_internal_watchdog():
    source = (REPOSITORY / "scripts" / "webnas_release.py").read_text(encoding="utf-8")

    assert 'f"WEBNAS_SLOT={self.new_slot}"' in source
    assert '"Restart=on-failure"' in source
    assert '"RestartSec=30"' in source
