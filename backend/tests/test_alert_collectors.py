from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.alerts.collectors import collect_host_health, collect_module_health
from app.alerts.service import AlertService


class FakeRegistry:
    def __init__(self, diagnostics: list[dict]) -> None:
        self.diagnostics = diagnostics

    async def health(self) -> list[dict]:
        return self.diagnostics


@pytest.mark.asyncio
async def test_module_health_collector_fires_and_resolves_same_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AlertService(tmp_path / "alerts.sqlite3", tmp_path / "alerts.key")
    monkeypatch.setattr("app.alerts.collectors.service", lambda: manager)
    registry = FakeRegistry([
        {"module_id": "proxmox-manager", "state": "broken", "message": "token=secret-value failed"},
    ])

    assert await collect_module_health(registry) == 1  # type: ignore[arg-type]
    active = manager.list_alerts(state="firing")
    assert len(active) == 1
    assert active[0]["source"] == "module.health"
    assert active[0]["event_key"] == "proxmox-manager"
    assert "secret-value" not in str(active[0]["details"])

    registry.diagnostics = [{"module_id": "proxmox-manager", "state": "active", "message": "ok"}]
    assert await collect_module_health(registry) == 1  # type: ignore[arg-type]
    resolved = manager.list_alerts(state="resolved")
    assert len(resolved) == 1
    assert resolved[0]["id"] == active[0]["id"]


def test_host_collector_uses_existing_hosts_manager_status_and_resolves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AlertService(tmp_path / "alerts.sqlite3", tmp_path / "alerts.key")
    monkeypatch.setattr("app.alerts.collectors.service", lambda: manager)
    registry = SimpleNamespace(
        list_hosts=lambda **_kwargs: [
            {
                "id": "host-1",
                "name": "node01",
                "address": "10.0.0.10",
                "active": True,
                "status": "offline",
                "connection_status": "offline",
                "agent_status": "offline",
                "agent": {"last_heartbeat_at": 123.0},
            }
        ]
    )
    monkeypatch.setattr("app.alerts.collectors.hosts_registry", lambda: registry)

    assert collect_host_health() == 1
    active = manager.list_alerts(state="firing")
    assert len(active) == 1
    assert active[0]["source"] == "host.offline"

    registry.list_hosts = lambda **_kwargs: [
        {
            "id": "host-1",
            "name": "node01",
            "address": "10.0.0.10",
            "active": True,
            "status": "online",
            "connection_status": "online",
            "agent_status": "online",
            "agent": {"last_heartbeat_at": 456.0},
        }
    ]
    assert collect_host_health() == 1
    assert manager.list_alerts(state="resolved")[0]["id"] == active[0]["id"]
