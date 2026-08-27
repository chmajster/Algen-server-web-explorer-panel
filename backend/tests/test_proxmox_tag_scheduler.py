from __future__ import annotations

from typing import Any

from app.modules.proxmox_manager import scheduler
from app.modules.proxmox_manager.service import ProxmoxManagerService


class FakeClient:
    def __init__(self) -> None:
        self.puts: list[tuple[str, dict[str, Any]]] = []

    def put(self, path: str, data: dict[str, Any] | None = None) -> str:
        self.puts.append((path, dict(data or {})))
        return "UPID:pve01:auto-tag"


class FakeManager:
    def __init__(self, resources: list[dict[str, Any]], client: FakeClient) -> None:
        self.resources = resources
        self.client = client

    def _client(self, _connection: dict[str, Any]) -> FakeClient:
        return self.client

    def _resources(self, _connection: dict[str, Any], _client: FakeClient | None = None) -> list[dict[str, Any]]:
        return [dict(item) for item in self.resources]

    @staticmethod
    def _host_identity(host: dict[str, Any]) -> tuple[str, str] | None:
        return ProxmoxManagerService._host_identity(host)

    @staticmethod
    def _parse_proxmox_tags(value: Any) -> list[str]:
        return ProxmoxManagerService._parse_proxmox_tags(value)

    @staticmethod
    def _managed_proxmox_tags(
        connection: dict[str, Any],
        resource: dict[str, Any],
        host: dict[str, Any],
    ) -> list[str]:
        return ProxmoxManagerService._managed_proxmox_tags(connection, resource, host)



def connection(**overrides: Any) -> dict[str, Any]:
    value = {
        "id": "connection-1",
        "active": True,
        "project": "Atlas Project",
        "environment": "Prod EU",
        "location": "Rack A",
        "tags": ["proxmox", "api"],
        "sync_proxmox_tags": True,
    }
    value.update(overrides)
    return value



def resource(tags: str = "manual") -> dict[str, Any]:
    return {
        "vmid": 101,
        "name": "app-01",
        "node": "pve01",
        "type": "qemu",
        "tags": ProxmoxManagerService._parse_proxmox_tags(tags),
    }



def test_auto_tag_new_vm_does_not_require_host_or_guest_address(monkeypatch):
    client = FakeClient()
    manager = FakeManager([resource("manual")], client)
    monkeypatch.setattr(scheduler, "shared_provider_hosts", lambda _provider, _connection_id="": [])

    result = scheduler.sync_connection_tags(manager, connection())  # type: ignore[arg-type]

    assert result["checked"] == 1
    assert result["updated"] == 1
    assert result["errors"] == []
    assert len(client.puts) == 1
    path, payload = client.puts[0]
    assert path == "nodes/pve01/qemu/101/config"
    assert set(str(payload["tags"]).split(";")) == {
        "manual",
        "algen",
        "project-atlas-project",
        "env-prod-eu",
        "location-rack-a",
        "type-vm",
        "proxmox",
        "api",
    }



def test_auto_tag_replaces_previous_managed_tags_and_preserves_manual_tags(monkeypatch):
    client = FakeClient()
    manager = FakeManager([resource("manual;algen;project-atlas-project;env-old;type-vm;proxmox")], client)
    host = {
        "id": "host-1",
        "environment": "staging",
        "location": "rack-b",
        "tags": ["proxmox", "worker"],
        "variables": {
            "algen_provider": "proxmox",
            "algen_provider_instance_id": "connection-1",
            "algen_provider_resource_id": "101",
            "algen_project": "Atlas Project",
            "proxmox_managed_tags": [
                "algen",
                "project-atlas-project",
                "env-old",
                "type-vm",
                "proxmox",
            ],
        },
    }
    monkeypatch.setattr(scheduler, "shared_provider_hosts", lambda _provider, _connection_id="": [host])

    result = scheduler.sync_connection_tags(manager, connection())  # type: ignore[arg-type]

    assert result["updated"] == 1
    tags = set(str(client.puts[0][1]["tags"]).split(";"))
    assert "manual" in tags
    assert "env-old" not in tags
    assert {"env-staging", "location-rack-b", "worker", "project-atlas-project", "type-vm"} <= tags



def test_auto_tag_skips_connections_with_tag_sync_disabled(monkeypatch):
    client = FakeClient()
    manager = FakeManager([resource()], client)
    monkeypatch.setattr(scheduler, "shared_provider_hosts", lambda _provider, _connection_id="": [])

    result = scheduler.sync_connection_tags(manager, connection(sync_proxmox_tags=False))  # type: ignore[arg-type]

    assert result == {"connection_id": "connection-1", "checked": 0, "updated": 0, "errors": []}
    assert client.puts == []
