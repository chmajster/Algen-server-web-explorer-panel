from __future__ import annotations

import importlib
from typing import Any

proxmox_module = importlib.import_module("app.modules.proxmox_manager.service")
from app.modules.proxmox_manager.models import ProxmoxConnectionInput
from app.modules.proxmox_manager.service import ProxmoxManagerService


class FakeHostRegistry:
    def __init__(self) -> None:
        self.hosts: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []
        self.saved_sources: list[str] = []
        self.capabilities: list[Any] = []
        self._credentials = [{
            "id": "proxmox-credential",
            "name": "PVE API",
            "type": "proxmox_api",
            "username": "automation@pve!algen",
            "secret_configured": True,
            "active": True,
        }]

    def credentials(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._credentials]

    def verified_credential(self, credential_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
        assert credential_id == "proxmox-credential"
        assert module_id == "proxmox-manager"
        assert purpose == "proxmox-api"
        return {
            "id": credential_id,
            "type": "proxmox_api",
            "username": "automation@pve!algen",
            "secret": "token-secret",
            "passphrase": "",
        }

    def list_hosts(self, **_: Any) -> list[dict[str, Any]]:
        return [dict(item) | {"variables": dict(item.get("variables") or {})} for item in self.hosts]

    def save_host(self, payload: Any, actor: str, host_id: str | None = None, *, source: str = "manual") -> dict[str, Any]:
        value = payload.model_dump(mode="json")
        self.saved_sources.append(source)
        if host_id:
            existing = next(item for item in self.hosts if item["id"] == host_id)
            created_by = existing.get("created_by", actor)
            existing.clear()
            existing.update(value | {"id": host_id, "created_by": created_by})
            return dict(existing)
        next_id = f"host-{len(self.hosts) + 1}"
        item = value | {"id": next_id, "created_by": actor}
        self.hosts.append(item)
        return dict(item)

    def operation(self, host_id: str | None, capability_id: str, actor: str, **kwargs: Any) -> dict[str, Any]:
        item = {"id": f"op-{len(self.operations) + 1}", "host_id": host_id, "capability_id": capability_id, "actor": actor, **kwargs}
        self.operations.append(item)
        return item

    def register_capability(self, provider: Any) -> None:
        self.capabilities.append(provider)


def patch_registry(monkeypatch, registry: FakeHostRegistry) -> None:
    monkeypatch.setattr(proxmox_module, "host_registry", lambda: registry)

    def provider_hosts(provider: str, instance_id: str = "") -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in registry.hosts:
            variables = dict(item.get("variables") or {})
            if variables.get("algen_provider") != provider:
                continue
            if instance_id and str(variables.get("algen_provider_instance_id") or "") != instance_id:
                continue
            result.append(dict(item) | {"variables": variables})
        return result

    monkeypatch.setattr(proxmox_module, "shared_provider_hosts", provider_hosts)
    monkeypatch.setattr(
        proxmox_module,
        "shared_host_names",
        lambda: {str(item.get("name") or "").casefold() for item in registry.hosts if item.get("name")},
    )


def resource(status: str = "running", *, node: str = "pve01") -> dict[str, Any]:
    return {
        "vmid": 101,
        "name": "app-01",
        "node": node,
        "type": "qemu",
        "status": status,
        "template": False,
        "uptime": 100,
        "cpu": 0.1,
        "maxcpu": 2,
        "mem": 512 * 1024 * 1024,
        "maxmem": 2 * 1024 * 1024 * 1024,
        "disk": 0,
        "maxdisk": 20 * 1024 * 1024 * 1024,
    }


def connection_input() -> ProxmoxConnectionInput:
    return ProxmoxConnectionInput(
        name="Lab PVE",
        endpoint="https://pve.example:8006",
        credential_id="proxmox-credential",
        default_ssh_user="algen-ansible",
        environment="lab",
        location="rack-a",
        tags=["proxmox", "lab"],
    )


def configured_manager(monkeypatch, tmp_path) -> tuple[FakeHostRegistry, ProxmoxManagerService, dict[str, Any], list[dict[str, Any]]]:
    registry = FakeHostRegistry()
    patch_registry(monkeypatch, registry)
    manager = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")
    connection = manager.save_connection(connection_input(), "admin")
    monkeypatch.setattr(manager, "_client", lambda _: object())
    current = [resource()]
    monkeypatch.setattr(manager, "_resources", lambda _connection, _client=None: [dict(item) for item in current])
    monkeypatch.setattr(manager, "_resolve_address", lambda _client, _resource: "10.0.10.21")
    return registry, manager, connection, current


def test_sync_uses_one_shared_host_identity_and_disables_missing(monkeypatch, tmp_path):
    registry, manager, connection, current = configured_manager(monkeypatch, tmp_path)

    first = manager.sync(connection["id"], "admin")
    assert first["created"] == 1
    assert first["updated"] == 0
    assert len(registry.hosts) == 1
    host_id = registry.hosts[0]["id"]
    assert registry.hosts[0]["address"] == "10.0.10.21"
    assert registry.hosts[0]["environment"] == "lab"
    assert registry.hosts[0]["variables"]["algen_provider"] == "proxmox"
    assert registry.hosts[0]["variables"]["algen_provider_instance_id"] == connection["id"]
    assert registry.hosts[0]["variables"]["algen_provider_resource_id"] == "101"
    assert registry.saved_sources == ["proxmox"]

    current[:] = [resource("stopped")]
    second = manager.sync(connection["id"], "admin")
    assert second["created"] == 0
    assert second["updated"] == 1
    assert len(registry.hosts) == 1
    assert registry.hosts[0]["id"] == host_id
    assert registry.hosts[0]["variables"]["proxmox_status"] == "stopped"

    current.clear()
    third = manager.sync(connection["id"], "admin")
    assert third["disabled"] == 1
    assert len(registry.hosts) == 1
    assert registry.hosts[0]["id"] == host_id
    assert registry.hosts[0]["active"] is False
    assert registry.hosts[0]["variables"]["proxmox_present"] is False

    current[:] = [resource()]
    fourth = manager.sync(connection["id"], "admin")
    assert fourth["updated"] == 1
    assert registry.hosts[0]["id"] == host_id
    assert registry.hosts[0]["active"] is True
    assert registry.hosts[0]["variables"]["proxmox_present"] is True


def test_sync_preserves_manual_disable_and_empty_user_owned_fields(monkeypatch, tmp_path):
    registry, manager, connection, _current = configured_manager(monkeypatch, tmp_path)
    manager.sync(connection["id"], "admin")

    registry.hosts[0]["active"] = False
    registry.hosts[0]["environment"] = ""
    registry.hosts[0]["location"] = ""
    registry.hosts[0]["tags"] = []

    result = manager.sync(connection["id"], "admin")

    assert result["updated"] == 1
    assert registry.hosts[0]["active"] is False
    assert registry.hosts[0]["environment"] == ""
    assert registry.hosts[0]["location"] == ""
    assert registry.hosts[0]["tags"] == []
    assert registry.hosts[0]["variables"]["proxmox_present"] is True


def test_connection_database_never_stores_token_secret(monkeypatch, tmp_path):
    registry = FakeHostRegistry()
    patch_registry(monkeypatch, registry)
    manager = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")
    saved = manager.save_connection(connection_input(), "admin")

    assert saved["credential_id"] == "proxmox-credential"
    with manager.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(connections)").fetchall()}
        raw = dict(connection.execute("SELECT * FROM connections WHERE id=?", (saved["id"],)).fetchone())
    assert "token" not in columns
    assert "secret" not in columns
    assert "password" not in columns
    assert "token-secret" not in str(raw)


def test_power_action_uses_current_node_after_vm_migration(monkeypatch, tmp_path):
    registry, manager, connection, current = configured_manager(monkeypatch, tmp_path)
    manager.sync(connection["id"], "admin")
    assert registry.hosts[0]["variables"]["proxmox_node"] == "pve01"

    current[:] = [resource(node="pve02")]
    posted: list[str] = []

    class FakeClient:
        def post(self, path: str, data: dict[str, Any] | None = None) -> str:
            posted.append(path)
            return "UPID:pve02:task"

    monkeypatch.setattr(manager, "_client", lambda _: FakeClient())
    result = manager.execute_vm_action(connection["id"], 101, "reboot", "admin")

    assert posted == ["nodes/pve02/qemu/101/status/reboot"]
    assert result["host_id"] == registry.hosts[0]["id"]
    assert registry.operations[-1]["details"]["node"] == "pve02"


def test_host_capabilities_are_registered_from_shared_provider(monkeypatch):
    registry = FakeHostRegistry()
    patch_registry(monkeypatch, registry)
    proxmox_module.register_host_capabilities()

    assert {item.id for item in registry.capabilities} == {
        "proxmox-manager.start",
        "proxmox-manager.stop",
        "proxmox-manager.shutdown",
        "proxmox-manager.reboot",
    }
    host = {
        "id": "host-1",
        "name": "app-01",
        "active": True,
        "variables": {
            "algen_provider": "proxmox",
            "algen_provider_instance_id": "connection-1",
            "proxmox_node": "pve01",
            "proxmox_present": True,
        },
    }
    assert all(item.supports(host) for item in registry.capabilities)

    host["active"] = False
    assert not any(item.supports(host) for item in registry.capabilities)
