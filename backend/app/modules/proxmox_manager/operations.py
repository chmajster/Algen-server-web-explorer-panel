from __future__ import annotations

import math
import re
import urllib.parse
from typing import Any

from ..hosts_manager.public import provider_hosts as shared_provider_hosts
from .inventory import vm_details
from .models import (
    ProxmoxCloneInput,
    ProxmoxCreateVmInput,
    ProxmoxDiskResizeInput,
    ProxmoxHardwareUpdateInput,
    ProxmoxMigrationInput,
    ProxmoxSnapshotCreateInput,
)
from .service import PROVIDER, ProxmoxApiError, ProxmoxManagerService
from .tasks import register_task


_SIZE_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([KMGTPE]?)$", re.IGNORECASE)


def _context(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
) -> tuple[dict[str, Any], dict[str, Any], Any, dict[str, Any] | None]:
    connection = manager.connection(connection_id)
    if not connection or not connection.get("active"):
        raise KeyError("Proxmox connection not found")
    resource = next((item for item in manager._resources(connection) if int(item.get("vmid") or -1) == vmid), None)
    if not resource:
        raise KeyError("Proxmox VM not found")
    host = next(
        (
            item
            for item in shared_provider_hosts(PROVIDER, connection_id)
            if manager._host_identity(item) == (connection_id, str(vmid))
        ),
        None,
    )
    return connection, resource, manager._client(connection), host


def _base(resource: dict[str, Any]) -> str:
    node = urllib.parse.quote(str(resource["node"]), safe="")
    return f"nodes/{node}/{resource['type']}/{int(resource['vmid'])}"


def _require_name_confirmation(resource: dict[str, Any], confirm: bool, confirmation_text: str) -> None:
    if not confirm or confirmation_text != str(resource["name"]):
        raise PermissionError("operation requires confirmation with the exact VM name")


def _task_result(
    manager: ProxmoxManagerService,
    connection: dict[str, Any],
    resource: dict[str, Any],
    task_value: Any,
    *,
    action: str,
    actor: str,
    host: dict[str, Any] | None = None,
    sync_on_complete: bool = False,
) -> dict[str, Any]:
    if isinstance(task_value, str) and task_value.startswith("UPID:"):
        task = register_task(
            manager,
            connection,
            task_value,
            action=action,
            actor=actor,
            vmid=int(resource["vmid"]),
            node=str(resource["node"]),
            resource_type=str(resource["type"]),
            host_id=str(host["id"]) if host else None,
            sync_on_complete=sync_on_complete,
        )
        return {"task": task, "status": task["status"]}
    return {"task": None, "status": "Completed"}


def list_snapshots(manager: ProxmoxManagerService, connection_id: str, vmid: int) -> list[dict[str, Any]]:
    _connection, resource, client, _host = _context(manager, connection_id, vmid)
    data = client.get(f"{_base(resource)}/snapshot")
    values: list[dict[str, Any]] = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        values.append(
            {
                "name": str(item.get("name") or ""),
                "description": str(item.get("description") or ""),
                "date": int(item.get("snaptime") or 0),
                "parent": str(item.get("parent") or ""),
                "vmstate": bool(item.get("vmstate")),
                "current": str(item.get("name") or "") == "current",
            }
        )
    return values


def create_snapshot(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxSnapshotCreateInput,
    actor: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    data: dict[str, Any] = {"snapname": payload.name}
    if payload.description:
        data["description"] = payload.description
    if resource["type"] == "qemu" and payload.include_ram:
        data["vmstate"] = 1
    task_value = client.post(f"{_base(resource)}/snapshot", data)
    return {"snapshot": payload.name, **_task_result(manager, connection, resource, task_value, action="snapshot.create", actor=actor, host=host)}


def delete_snapshot(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    snapshot: str,
    *,
    actor: str,
    confirm: bool,
    confirmation_text: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    _require_name_confirmation(resource, confirm, confirmation_text)
    snapshot_name = urllib.parse.quote(snapshot, safe="")
    task_value = client.request("DELETE", f"{_base(resource)}/snapshot/{snapshot_name}")
    return {"snapshot": snapshot, **_task_result(manager, connection, resource, task_value, action="snapshot.delete", actor=actor, host=host)}


def rollback_snapshot(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    snapshot: str,
    *,
    actor: str,
    confirm: bool,
    confirmation_text: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    _require_name_confirmation(resource, confirm, confirmation_text)
    snapshot_name = urllib.parse.quote(snapshot, safe="")
    task_value = client.post(f"{_base(resource)}/snapshot/{snapshot_name}/rollback")
    return {"snapshot": snapshot, **_task_result(manager, connection, resource, task_value, action="snapshot.rollback", actor=actor, host=host, sync_on_complete=True)}


def clone_vm(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxCloneInput,
    actor: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    data: dict[str, Any] = {"newid": payload.new_vmid, "full": int(payload.full)}
    data["name" if resource["type"] == "qemu" else "hostname"] = payload.name
    if payload.target_node:
        data["target"] = payload.target_node
    if payload.target_storage:
        data["storage"] = payload.target_storage
    if payload.pool:
        data["pool"] = payload.pool
    task_value = client.post(f"{_base(resource)}/clone", data)
    result = _task_result(
        manager,
        connection,
        resource | {"vmid": payload.new_vmid, "name": payload.name, "node": payload.target_node or resource["node"]},
        task_value,
        action="clone",
        actor=actor,
        host=None,
        sync_on_complete=payload.sync_to_host_registry,
    )
    return {"source_vmid": vmid, "new_vmid": payload.new_vmid, "name": payload.name, **result}


def validate_migration(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxMigrationInput,
) -> dict[str, Any]:
    connection, resource, client, _host = _context(manager, connection_id, vmid)
    issues: list[str] = []
    warnings: list[str] = []
    if payload.target_node == resource["node"]:
        issues.append("target node must be different from the current node")
    nodes = client.get("nodes") or []
    target = next((item for item in nodes if isinstance(item, dict) and str(item.get("node") or "") == payload.target_node), None)
    if target is None:
        issues.append("target node does not exist in this Proxmox connection")
    elif str(target.get("status") or "online") not in {"online", "running"}:
        issues.append("target node is not online")
    if resource["type"] == "lxc" and payload.online:
        issues.append("online migration is not exposed for LXC; use offline migration")
    if payload.target_storage and target is not None:
        encoded = urllib.parse.quote(payload.target_node, safe="")
        stores = client.get(f"nodes/{encoded}/storage") or []
        store = next((item for item in stores if isinstance(item, dict) and str(item.get("storage") or "") == payload.target_storage), None)
        if store is None or not bool(store.get("active", 1)):
            issues.append("target storage is not available on the destination node")
    if payload.online and str(resource.get("status") or "") != "running":
        warnings.append("resource is not running; Proxmox may perform this as an offline migration")
    return {
        "valid": not issues,
        "connection_id": connection["id"],
        "vmid": vmid,
        "name": resource["name"],
        "resource_type": resource["type"],
        "source_node": resource["node"],
        "target_node": payload.target_node,
        "issues": issues,
        "warnings": warnings,
    }


def migrate_vm(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxMigrationInput,
    actor: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    _require_name_confirmation(resource, payload.confirm, payload.confirmation_text)
    validation = validate_migration(manager, connection_id, vmid, payload)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["issues"]))
    data: dict[str, Any] = {"target": payload.target_node}
    if resource["type"] == "qemu":
        data["online"] = int(payload.online)
        data["with-local-disks"] = int(payload.with_local_disks)
        if payload.migration_network:
            data["migration_network"] = payload.migration_network
    if payload.target_storage:
        data["targetstorage"] = payload.target_storage
    task_value = client.post(f"{_base(resource)}/migrate", data)
    return {
        "validation": validation,
        **_task_result(manager, connection, resource, task_value, action="migrate", actor=actor, host=host, sync_on_complete=True),
    }


def hardware_plan(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxHardwareUpdateInput,
) -> dict[str, Any]:
    details = vm_details(manager, connection_id, vmid)
    hardware = details["hardware"]
    requested = {
        "cores": payload.cores,
        "sockets": payload.sockets,
        "memory_mb": payload.memory_mb,
        "balloon_mb": payload.balloon_mb,
    }
    changes = []
    for key, new_value in requested.items():
        if new_value is None:
            continue
        current = int(hardware.get(key) or 0)
        if current != new_value:
            changes.append({"field": key, "current": current, "new": new_value})
    return {"connection_id": connection_id, "vmid": vmid, "name": details["name"], "changes": changes}


def update_hardware(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxHardwareUpdateInput,
    actor: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    _require_name_confirmation(resource, payload.confirm, payload.confirmation_text)
    plan = hardware_plan(manager, connection_id, vmid, payload)
    if not plan["changes"]:
        return {"changes": [], "task": None, "status": "Completed"}
    key_map = {"memory_mb": "memory", "balloon_mb": "balloon", "cores": "cores", "sockets": "sockets"}
    data = {key_map[item["field"]]: item["new"] for item in plan["changes"]}
    task_value = client.put(f"{_base(resource)}/config", data)
    return {"changes": plan["changes"], **_task_result(manager, connection, resource, task_value, action="hardware.update", actor=actor, host=host)}


def _size_gb(value: str) -> float:
    match = _SIZE_PATTERN.fullmatch(value.strip())
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2).upper()
    scale = {"": 1 / (1024 ** 3), "K": 1 / (1024 ** 2), "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 ** 2, "E": 1024 ** 3}[unit]
    return number * scale


def resize_disk(
    manager: ProxmoxManagerService,
    connection_id: str,
    vmid: int,
    payload: ProxmoxDiskResizeInput,
    actor: str,
) -> dict[str, Any]:
    connection, resource, client, host = _context(manager, connection_id, vmid)
    _require_name_confirmation(resource, payload.confirm, payload.confirmation_text)
    if resource["type"] != "qemu":
        raise ValueError("disk resize is currently supported for QEMU VMs only")
    config = client.get(f"{_base(resource)}/config")
    if not isinstance(config, dict) or payload.disk not in config:
        raise KeyError("Proxmox disk not found")
    raw = str(config[payload.disk])
    options = {key: value for key, value in (part.split("=", 1) for part in raw.split(",")[1:] if "=" in part)}
    current_gb = _size_gb(options.get("size", ""))
    if current_gb <= 0:
        raise ValueError("current disk size cannot be determined safely")
    if payload.new_size_gb <= current_gb:
        raise ValueError("disk size can only be increased")
    delta = max(1, math.ceil(payload.new_size_gb - current_gb))
    task_value = client.put(f"{_base(resource)}/resize", {"disk": payload.disk, "size": f"+{delta}G"})
    return {
        "disk": payload.disk,
        "current_gb": current_gb,
        "new_gb": payload.new_size_gb,
        **_task_result(manager, connection, resource, task_value, action="disk.resize", actor=actor, host=host),
    }


def create_vm(
    manager: ProxmoxManagerService,
    connection_id: str,
    payload: ProxmoxCreateVmInput,
    actor: str,
) -> dict[str, Any]:
    connection = manager.connection(connection_id)
    if not connection or not connection.get("active"):
        raise KeyError("Proxmox connection not found")
    if payload.start_after_create:
        raise ValueError("start_after_create is not supported for asynchronous VM creation; start the VM after the create task completes")
    client = manager._client(connection)
    nodes = client.get("nodes") or []
    if not any(isinstance(item, dict) and str(item.get("node") or "") == payload.node for item in nodes):
        raise KeyError("Proxmox node not found")
    encoded_node = urllib.parse.quote(payload.node, safe="")
    stores = client.get(f"nodes/{encoded_node}/storage") or []
    store = next((item for item in stores if isinstance(item, dict) and str(item.get("storage") or "") == payload.storage), None)
    if store is None or not bool(store.get("active", 1)):
        raise ValueError("selected storage is not available")
    net0 = f"virtio,bridge={payload.bridge}"
    if payload.vlan is not None:
        net0 += f",tag={payload.vlan}"
    data: dict[str, Any] = {
        "vmid": payload.vmid,
        "name": payload.name,
        "cores": payload.cores,
        "sockets": payload.sockets,
        "memory": payload.memory_mb,
        "scsihw": "virtio-scsi-pci",
        "scsi0": f"{payload.storage}:{payload.disk_size_gb}",
        "net0": net0,
        "ide2": f"{payload.storage}:cloudinit",
        "ipconfig0": "ip=dhcp" if payload.ipv4_mode == "dhcp" else f"ip={payload.ipv4_address},gw={payload.gateway}",
    }
    if payload.cloud_init_user:
        data["ciuser"] = payload.cloud_init_user
    if payload.ssh_public_key:
        data["sshkeys"] = payload.ssh_public_key
    if payload.dns:
        data["nameserver"] = payload.dns
    task_value = client.post(f"nodes/{encoded_node}/qemu", data)
    resource = {"vmid": payload.vmid, "name": payload.name, "node": payload.node, "type": "qemu"}
    return {
        "vmid": payload.vmid,
        "name": payload.name,
        **_task_result(manager, connection, resource, task_value, action="create", actor=actor, sync_on_complete=payload.sync_to_host_registry),
    }
