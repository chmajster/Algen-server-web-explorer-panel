from __future__ import annotations

import importlib
import urllib.parse
from typing import Any

import pytest

from app.modules.proxmox_manager.inventory import cluster_health, list_nodes, list_storage
from app.modules.proxmox_manager.models import (
    ProxmoxConnectionInput,
    ProxmoxDiskResizeInput,
    ProxmoxMigrationInput,
    ProxmoxSnapshotCreateInput,
)
from app.modules.proxmox_manager.operations import (
    create_snapshot,
    delete_snapshot,
    migrate_vm,
    resize_disk,
    rollback_snapshot,
    validate_migration,
)
from app.modules.proxmox_manager.runtime import configure_connection_runtime, ensure_runtime_schema
from app.modules.proxmox_manager.service import ProxmoxManagerService
from app.modules.proxmox_manager.tasks import get_task, register_task

service_module = importlib.import_module("app.modules.proxmox_manager.service")
operations_module = importlib.import_module("app.modules.proxmox_manager.operations")
scheduler_module = importlib.import_module("app.modules.proxmox_manager.scheduler")
tasks_module = importlib.import_module("app.modules.proxmox_manager.tasks")


class FakeRegistry:
    def __init__(self) -> None:
        self.operations: list[dict[str, Any]] = []

    def credentials(self) -> list[dict[str, Any]]:
        return [{
            "id": "credential-1",
            "name": "PVE API",
            "type": "proxmox_api",
            "username": "automation@pve!algen",
            "secret_configured": True,
            "active": True,
            "shared_with": ["proxmox-manager"],
        }]

    def verified_credential(self, *_args: Any, **_kwargs: Any) -> dict[str, str]:
        return {"id": "credential-1", "type": "proxmox_api", "username": "automation@pve!algen", "secret": "top-secret", "passphrase": ""}

    def operation(self, host_id: str | None, capability_id: str, actor: str, **kwargs: Any) -> dict[str, Any]:
        item = {"id": f"op-{len(self.operations) + 1}", "host_id": host_id, "capability_id": capability_id, "actor": actor, **kwargs}
        self.operations.append(item)
        return item


class FakeClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any] | None]] = []
        self.puts: list[tuple[str, dict[str, Any] | None]] = []
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.responses: dict[str, Any] = {}

    def get(self, path: str) -> Any:
        if path not in self.responses:
            raise AssertionError(f"unexpected GET {path}")
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    def post(self, path: str, data: dict[str, Any] | None = None) -> str:
        self.posts.append((path, data))
        return "UPID:pve01:00000001:task"

    def put(self, path: str, data: dict[str, Any] | None = None) -> str:
        self.puts.append((path, data))
        return "UPID:pve01:00000002:task"

    def delete(self, path: str, data: dict[str, Any] | None = None) -> str:
        self.requests.append(("DELETE", path, data))
        return "UPID:pve01:00000003:task"

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> str:
        self.requests.append((method, path, data))
        return "UPID:pve01:00000003:task"


def connection_input(**updates: Any) -> ProxmoxConnectionInput:
    values = {
        "name": "Lab PVE",
        "endpoint": "https://pve.example:8006",
        "credential_id": "credential-1",
        "sync_proxmox_tags": False,
        "auto_sync": False,
    }
    values.update(updates)
    return ProxmoxConnectionInput(**values)


def resource(*, node: str = "pve01", status: str = "stopped", resource_type: str = "qemu") -> dict[str, Any]:
    return {
        "vmid": 101,
        "name": "app-01",
        "node": node,
        "type": resource_type,
        "status": status,
        "template": False,
        "uptime": 100,
        "cpu": 0.1,
        "maxcpu": 2,
        "mem": 512 * 1024 * 1024,
        "maxmem": 2 * 1024 * 1024 * 1024,
        "disk": 0,
        "maxdisk": 20 * 1024 * 1024 * 1024,
        "tags": [],
    }


def configured_manager(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[ProxmoxManagerService, dict[str, Any], FakeRegistry]:
    registry = FakeRegistry()
    monkeypatch.setattr(service_module, "host_registry", lambda: registry)
    monkeypatch.setattr(tasks_module, "host_registry", lambda: registry)
    monkeypatch.setattr(operations_module, "shared_provider_hosts", lambda *_args, **_kwargs: [])
    manager = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")
    ensure_runtime_schema(manager)
    connection = manager.save_connection(connection_input(), "admin")
    return manager, connection, registry


def test_runtime_schema_stores_scheduler_and_tasks_without_secrets(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    configure_connection_runtime(manager, connection["id"], auto_sync=True, sync_interval_seconds=120)

    with manager.connect() as db:
        connection_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(connections)").fetchall()}
        task_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(proxmox_tasks)").fetchall()}
        row = dict(db.execute("SELECT * FROM connections WHERE id=?", (connection["id"],)).fetchone())

    assert {"sync_interval_seconds", "next_sync_at", "last_sync_duration", "consecutive_sync_failures"} <= connection_columns
    assert {"upid", "action", "status", "exitstatus", "progress", "operation_id"} <= task_columns
    assert not ({"token", "secret", "password"} & task_columns)
    assert row["sync_interval_seconds"] == 120
    assert "top-secret" not in str(row)


def test_task_polling_uses_node_encoded_in_upid(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    client = FakeClient()
    upid = "UPID:pve-source:00000001:task"
    encoded = urllib.parse.quote(upid, safe="")
    client.responses[f"nodes/pve-source/tasks/{encoded}/status"] = {"status": "stopped", "exitstatus": "OK", "starttime": 10, "endtime": 20}
    monkeypatch.setattr(manager, "_client", lambda _connection: client)

    registered = register_task(manager, connection, upid, action="clone", actor="admin", vmid=202, node="pve-target")
    result = get_task(manager, upid, connection_id=connection["id"])

    assert registered["node"] == "pve-source"
    assert result["node"] == "pve-source"
    assert result["status"] == "Completed"
    assert result["exitstatus"] == "OK"
    assert result["progress"] == 100


def test_task_failure_is_terminal(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    client = FakeClient()
    upid = "UPID:pve01:00000009:task"
    encoded = urllib.parse.quote(upid, safe="")
    client.responses[f"nodes/pve01/tasks/{encoded}/status"] = {"status": "stopped", "exitstatus": "migration failed"}
    monkeypatch.setattr(manager, "_client", lambda _connection: client)
    register_task(manager, connection, upid, action="migrate", actor="admin", vmid=101)

    result = get_task(manager, upid, connection_id=connection["id"])

    assert result["status"] == "Failed"
    assert result["last_error"] == "migration failed"


def test_nodes_storage_and_cluster_are_read_from_rest_api(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    client = FakeClient()
    client.responses.update({
        "nodes": [{"node": "pve01", "status": "online"}],
        "nodes/pve01/status": {
            "uptime": 7200,
            "cpu": 0.25,
            "cpuinfo": {"cpus": 8},
            "memory": {"used": 4 * 1024**3, "total": 16 * 1024**3},
            "rootfs": {"used": 20 * 1024**3, "total": 100 * 1024**3},
            "kversion": "Linux 6.x",
            "pveversion": "pve-manager/9.0",
            "loadavg": ["0.2", "0.3", "0.4"],
        },
        "nodes/pve01/storage": [{"storage": "local-lvm", "type": "lvmthin", "active": 1, "total": 1000, "used": 400, "avail": 600, "shared": 0, "content": "images,rootdir"}],
        "cluster/status": [{"type": "cluster", "name": "lab", "quorate": 1}, {"type": "node", "name": "pve01", "online": 1, "votes": 1}],
        "cluster/ha/resources": [{"sid": "vm:101", "state": "started"}],
        "cluster/ha/groups": [{"group": "default"}],
    })
    monkeypatch.setattr(manager, "_client", lambda _connection: client)
    monkeypatch.setattr(manager, "_resources", lambda _connection, _client=None: [resource(), resource(resource_type="lxc") | {"vmid": 102}])

    nodes = list_nodes(manager, connection["id"])["nodes"]
    storage = list_storage(manager, connection["id"])["storage"]
    cluster = cluster_health(manager, connection["id"])["clusters"]

    assert nodes[0]["node"] == "pve01"
    assert nodes[0]["vms"] == 1 and nodes[0]["lxc"] == 1
    assert nodes[0]["proxmox_version"] == "pve-manager/9.0"
    assert storage[0]["storage"] == "local-lvm"
    assert storage[0]["utilization"] == pytest.approx(0.4)
    assert cluster[0]["quorate"] is True
    assert len(cluster[0]["ha_resources"]) == 1


def test_snapshot_operations_require_exact_vm_confirmation(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    client = FakeClient()
    monkeypatch.setattr(manager, "_client", lambda _connection: client)
    monkeypatch.setattr(manager, "_resources", lambda _connection, _client=None: [resource()])

    created = create_snapshot(manager, connection["id"], 101, ProxmoxSnapshotCreateInput(name="before-upgrade"), "admin")
    assert created["task"]["action"] == "snapshot.create"
    assert client.posts[0][0] == "nodes/pve01/qemu/101/snapshot"

    with pytest.raises(PermissionError):
        delete_snapshot(manager, connection["id"], 101, "before-upgrade", actor="admin", confirm=True, confirmation_text="wrong")

    delete_snapshot(manager, connection["id"], 101, "before-upgrade", actor="admin", confirm=True, confirmation_text="app-01")
    rollback_snapshot(manager, connection["id"], 101, "before-upgrade", actor="admin", confirm=True, confirmation_text="app-01")

    assert client.requests[-1][0] == "DELETE"
    assert client.requests[-1][1].endswith("/snapshot/before-upgrade")
    assert client.posts[-1][0].endswith("/snapshot/before-upgrade/rollback")


def test_migration_validation_and_execution_keep_stable_resource_identity(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    client = FakeClient()
    client.responses["nodes"] = [{"node": "pve01", "status": "online"}, {"node": "pve02", "status": "online"}]
    client.responses["nodes/pve02/storage"] = [{"storage": "shared", "active": 1}]
    monkeypatch.setattr(manager, "_client", lambda _connection: client)
    monkeypatch.setattr(manager, "_resources", lambda _connection, _client=None: [resource()])
    payload = ProxmoxMigrationInput(target_node="pve02", target_storage="shared", online=False, confirm=True, confirmation_text="app-01")

    validation = validate_migration(manager, connection["id"], 101, payload)
    result = migrate_vm(manager, connection["id"], 101, payload, "admin")

    assert validation["valid"] is True
    assert client.posts[-1] == ("nodes/pve01/qemu/101/migrate", {"target": "pve02", "online": 0, "with-local-disks": 1, "targetstorage": "shared"})
    assert result["task"]["vmid"] == 101
    assert result["task"]["sync_on_complete"] is True


def test_disk_resize_rejects_shrink_and_only_sends_growth(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    client = FakeClient()
    client.responses["nodes/pve01/qemu/101/config"] = {"scsi0": "local-lvm:vm-101-disk-0,size=20G"}
    monkeypatch.setattr(manager, "_client", lambda _connection: client)
    monkeypatch.setattr(manager, "_resources", lambda _connection, _client=None: [resource()])

    with pytest.raises(ValueError, match="only be increased"):
        resize_disk(manager, connection["id"], 101, ProxmoxDiskResizeInput(disk="scsi0", new_size_gb=20, confirm=True, confirmation_text="app-01"), "admin")

    result = resize_disk(manager, connection["id"], 101, ProxmoxDiskResizeInput(disk="scsi0", new_size_gb=30, confirm=True, confirmation_text="app-01"), "admin")
    assert result["current_gb"] == 20
    assert result["new_gb"] == 30
    assert client.puts[-1] == ("nodes/pve01/qemu/101/resize", {"disk": "scsi0", "size": "+10G"})


def test_auto_sync_error_isolated_and_lock_prevents_overlap(monkeypatch, tmp_path):
    manager, connection, _registry = configured_manager(monkeypatch, tmp_path)
    second = manager.save_connection(connection_input(name="Second PVE"), "admin")
    ensure_runtime_schema(manager)
    calls: list[str] = []

    def sync(connection_id: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(connection_id)
        if connection_id == connection["id"]:
            raise RuntimeError("first cluster failed")
        return {"created": 0, "updated": 1, "disabled": 0, "tagged": 0, "skipped": [], "tag_errors": []}

    monkeypatch.setattr(manager, "sync", sync)
    monkeypatch.setattr(scheduler_module, "_record_sync_activity", lambda *_args, **_kwargs: None)
    first_state = dict(connection) | {"active": True, "auto_sync": True, "next_sync_at": 0, "backoff_until": 0}
    second_state = dict(second) | {"active": True, "auto_sync": True, "next_sync_at": 0, "backoff_until": 0}

    assert scheduler_module._auto_sync_connection(manager, first_state) is False
    assert scheduler_module._auto_sync_connection(manager, second_state) is True
    assert calls == [connection["id"], second["id"]]

    lock = scheduler_module.connection_lock(second["id"])
    assert lock.acquire(blocking=False)
    try:
        assert scheduler_module._auto_sync_connection(manager, second_state) is False
    finally:
        lock.release()
