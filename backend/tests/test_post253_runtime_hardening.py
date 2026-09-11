from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import settings
from app.modules.dhcp.service import DhcpService
from app.modules.hosts_manager.service import HostRegistryService
from app.modules.providers import dhcp as dhcp_provider_module


def test_admin_rate_limiter_serializes_window_mutation(monkeypatch):
    cfg = SimpleNamespace(security=SimpleNamespace(rate_limit_admin_per_minute=100))
    monkeypatch.setattr(settings, "get_config", lambda: cfg)
    limiter = settings.AdminRateLimiter()

    class ObservedDeque(deque):
        guard = threading.Lock()
        active = 0
        maximum = 0

        def __len__(self):
            with type(self).guard:
                type(self).active += 1
                type(self).maximum = max(type(self).maximum, type(self).active)
            try:
                time.sleep(0.005)
                return super().__len__()
            finally:
                with type(self).guard:
                    type(self).active -= 1

    limiter._attempts["admin"] = ObservedDeque()
    gate = threading.Barrier(8)
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            gate.wait(timeout=2)
            limiter.check("admin")
        except BaseException as error:  # pragma: no cover - asserted below
            failures.append(error)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    assert ObservedDeque.maximum == 1
    assert len(limiter._attempts["admin"]) == 8


def test_settings_run_does_not_expose_command_stderr(monkeypatch):
    monkeypatch.setattr(settings, "broker_required", lambda: False)
    monkeypatch.setattr(
        settings.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "SECRET /etc/shadow token=abc"),
    )
    with pytest.raises(HTTPException) as caught:
        settings._run(["/usr/sbin/usermod", "demo"])
    assert caught.value.status_code == 400
    assert caught.value.detail == "System command failed"
    assert "SECRET" not in str(caught.value.detail)


def test_shutdown_failure_state_does_not_expose_exception(monkeypatch):
    monkeypatch.setattr(settings, "_shutdown_generation", 77)
    monkeypatch.setattr(
        settings,
        "_shutdown_state",
        {"state": "scheduled", "deadline": time.time() - 1, "blocker_count": 0, "requested_by": "admin", "error": ""},
    )
    monkeypatch.setattr(settings, "_shutdown_blockers", lambda: [])

    def fail_tool(name: str) -> str:
        raise RuntimeError("SECRET /root/private")

    monkeypatch.setattr(settings, "_tool", fail_tool)
    settings._shutdown_worker(77)
    payload = settings._shutdown_payload()
    assert payload["state"] == "failed"
    assert payload["error"] == "System shutdown failed"
    assert "SECRET" not in str(payload["error"])


def test_hosts_settings_corrupt_json_falls_back_to_default(tmp_path):
    repository = HostRegistryService(
        tmp_path / "hosts" / "hosts.sqlite3",
        tmp_path / "secrets" / "hosts.key",
        tmp_path / "missing-controller.sqlite3",
    )
    with repository.connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO hosts_manager_settings(key,value_json,updated_at,updated_by) VALUES('heartbeat_interval_seconds','{',1,'admin')"
        )
    payload = repository.settings()
    assert payload["heartbeat_interval_seconds"] == 30


def test_dhcp_read_input_normalizes_missing_or_corrupt_payload(tmp_path):
    service = DhcpService(tmp_path / "dhcp")
    reference = service.stage_input({"configuration": {}})
    staged = service.inputs_root / f"{reference}.json"
    staged.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid staged DHCP payload"):
        service.read_input(reference)
    staged.unlink()
    with pytest.raises(ValueError, match="invalid staged DHCP payload"):
        service.read_input(reference)


def test_dhcp_provider_discards_bad_staged_input(monkeypatch):
    discarded: list[str] = []

    class FakeService:
        def read_input(self, reference: str):
            raise ValueError("invalid staged DHCP payload")

        def discard_input(self, reference: str) -> None:
            discarded.append(reference)

    fake = FakeService()
    monkeypatch.setattr(dhcp_provider_module, "service", lambda: fake)
    provider = dhcp_provider_module.DhcpProvider()
    reference = "a" * 32
    with pytest.raises(ValueError, match="invalid staged DHCP payload"):
        provider.manage(
            "config_apply",
            {"input_ref": reference},
            "admin",
            lambda *_: None,
            lambda *_: None,
            lambda: False,
        )
    assert discarded == [reference]
