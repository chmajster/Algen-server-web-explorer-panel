from __future__ import annotations

from pathlib import Path

import pytest

from app import run as run_module
from app.config import AppConfig


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


def test_direct_plaintext_public_bind_requires_explicit_policy():
    cfg = AppConfig.model_validate({"security": {"allow_insecure_http": False}})

    with pytest.raises(RuntimeError, match="plaintext HTTP"):
        run_module._validate_transport(cfg, "0.0.0.0", behind_gateway=False)


def test_direct_plaintext_loopback_remains_available_for_local_development():
    cfg = AppConfig.model_validate({"security": {"allow_insecure_http": False}})

    run_module._validate_transport(cfg, "127.0.0.1", behind_gateway=False)
    run_module._validate_transport(cfg, "::1", behind_gateway=False)
    run_module._validate_transport(cfg, "localhost", behind_gateway=False)


def test_explicit_insecure_http_policy_allows_isolated_lab_bind():
    cfg = AppConfig.model_validate({"security": {"allow_insecure_http": True}})

    run_module._validate_transport(cfg, "0.0.0.0", behind_gateway=False)


def test_legacy_plaintext_config_is_upgrade_compatible_but_warns(capfd):
    cfg = AppConfig()

    run_module._validate_transport(cfg, "0.0.0.0", behind_gateway=False)

    assert "legacy configuration exposes plaintext HTTP" in capfd.readouterr().err


def test_blue_green_backend_transport_is_owned_by_gateway():
    cfg = AppConfig.model_validate({"security": {"allow_insecure_http": False}})

    run_module._validate_transport(cfg, "127.0.0.1", behind_gateway=True)


def test_direct_tls_requires_configured_certificate_files(tmp_path: Path):
    cfg = AppConfig.model_validate(
        {
            "server": {
                "use_https": True,
                "tls_cert": str(tmp_path / "missing.crt"),
                "tls_key": str(tmp_path / "missing.key"),
            }
        }
    )

    with pytest.raises(RuntimeError, match="TLS is enabled"):
        run_module._validate_transport(cfg, "0.0.0.0", behind_gateway=False)


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
