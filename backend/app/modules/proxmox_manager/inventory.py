from __future__ import annotations

import math
import re
import urllib.parse
from typing import Any, cast

from ..hosts_manager.public import provider_hosts as shared_provider_hosts
from .service import PROVIDER, ProxmoxApiError, ProxmoxManagerService


_DISK_KEY = re.compile(r"^(?:ide|sata|scsi|virtio)\d+$")
_NET_KEY = re.compile(r"^net\d+$")
_BACKUP_VMID = re.compile(r"vzdump-(?:qemu|lxc)-(\d+)-")


def _safe_int(value: object, default: int = 0, *, minimum: int | None = None) -> int:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if minimum is not None and number < minimum:
        return default
    return number


def _safe_float(value: object, default: float = 0.0, *, minimum: float | None = None) -> float:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        return default
    return number


def _safe_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "online"}:
            return True
        if normalized in {"0", "false", "no", "off", "offline"}:
            return False
    return default


def _connections(manager: ProxmoxManagerService, connection_id: str = "") -> list[dict[str, Any]]:
    if connection_id:
        item = manager.connection(connection_id)
        if not item or not item.get("active"):
            raise KeyError("Proxmox connection not found")
        return [item]
    return manager.connections(active_only=True)


def _safe_get(client: Any, path: str) -> tuple[Any, str]:
    try:
        return client.get(path), ""
    except (ProxmoxApiError, KeyError, ValueError) as error:
        return None, str(error)[:1000]


def _as_dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _host_map(manager: ProxmoxManagerService, connection_id: str = "") -> dict[tuple[str, str], dict[str, Any]]:
    return {
        identity: host
        for host in shared_provider_hosts(PROVIDER, connection_id)
        if (identity := manager._host_identity(host)) is not None
    }


def _parse_kv(value: Any) -> tuple[str, dict[str, str]]:
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    first = parts[0] if parts else ""
    options: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, item = part.split("=", 1)
            options[key] = item
        else:
            options[part] = "1"
    return first, options


def _hardware_from_config(config: dict[str, Any], resource_type: str) -> dict[str, Any]:
    disks: list[dict[str, Any]] = []
    networks: list[dict[str, Any]] = []
    for key, raw in config.items():
        if _DISK_KEY.fullmatch(str(key)):
            volume, options = _parse_kv(raw)
            storage = volume.split(":", 1)[0] if ":" in volume else ""
            disks.append(
                {
                    "device": key,
                    "volume": volume,
                    "storage": storage,
                    "size": options.get("size", ""),
                    "cache": options.get("cache", ""),
                    "discard": options.get("discard", ""),
                    "iothread": options.get("iothread", ""),
                    "ssd": options.get("ssd", ""),
                }
            )
        if _NET_KEY.fullmatch(str(key)):
            first, options = _parse_kv(raw)
            model = ""
            mac = ""
            if "=" in first:
                model, mac = first.split("=", 1)
            elif resource_type == "lxc":
                options = dict(options)
                if "=" in first:
                    _, _ = first.split("=", 1)
            networks.append(
                {
                    "device": key,
                    "model": model or ("veth" if resource_type == "lxc" else first),
                    "mac": mac or options.get("hwaddr", ""),
                    "bridge": options.get("bridge", ""),
                    "vlan": options.get("tag", ""),
                    "name": options.get("name", ""),
                    "firewall": options.get("firewall", ""),
                }
            )
    return {
        "cores": _safe_int(config.get("cores"), 0, minimum=0),
        "sockets": _safe_int(config.get("sockets"), 1, minimum=1),
        "cpu_type": str(config.get("cpu") or config.get("cputype") or ""),
        "memory_mb": _safe_int(config.get("memory"), 0, minimum=0),
        "balloon_mb": _safe_int(config.get("balloon"), 0, minimum=0),
        "machine": str(config.get("machine") or ""),
        "bios": str(config.get("bios") or "seabios"),
        "agent": config.get("agent", ""),
        "disks": disks,
        "network_adapters": networks,
    }


def list_nodes(manager: ProxmoxManagerService, connection_id: str = "") -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for connection in _connections(manager, connection_id):
        client = manager._client(connection)
        try:
            raw_nodes = client.get("nodes") or []
            resources = manager._resources(connection, client)
        except (ProxmoxApiError, KeyError, ValueError) as error:
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": str(error)})
            continue
        counts: dict[str, dict[str, int]] = {}
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            bucket = counts.setdefault(str(resource.get("node") or ""), {"vms": 0, "lxc": 0})
            bucket["vms" if resource.get("type") == "qemu" else "lxc"] += 1
        if not isinstance(raw_nodes, list):
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": "Proxmox nodes response is invalid"})
            continue
        for raw in raw_nodes:
            if not isinstance(raw, dict) or not raw.get("node"):
                continue
            node_name = str(raw["node"])
            encoded = urllib.parse.quote(node_name, safe="")
            status_raw, status_error = _safe_get(client, f"nodes/{encoded}/status")
            status = _as_dict(status_raw)
            rootfs = _as_dict(status.get("rootfs"))
            cpuinfo = _as_dict(status.get("cpuinfo"))
            memory = _as_dict(status.get("memory"))
            loadavg = status.get("loadavg")
            values.append(
                {
                    "connection_id": connection["id"],
                    "connection_name": connection["name"],
                    "node": node_name,
                    "status": str(raw.get("status") or status.get("status") or "unknown"),
                    "uptime": _safe_int(status.get("uptime") or raw.get("uptime"), 0, minimum=0),
                    "cpu": _safe_float(status.get("cpu") or raw.get("cpu"), 0.0, minimum=0.0),
                    "maxcpu": _safe_int(cpuinfo.get("cpus") or raw.get("maxcpu"), 0, minimum=0),
                    "mem": _safe_int(memory.get("used") or raw.get("mem"), 0, minimum=0),
                    "maxmem": _safe_int(memory.get("total") or raw.get("maxmem"), 0, minimum=0),
                    "storage_used": _safe_int(rootfs.get("used") or raw.get("disk"), 0, minimum=0),
                    "storage_total": _safe_int(rootfs.get("total") or raw.get("maxdisk"), 0, minimum=0),
                    "kernel": str(status.get("kversion") or ""),
                    "proxmox_version": str(status.get("pveversion") or ""),
                    "load_average": list(loadavg)[:16] if isinstance(loadavg, (list, tuple)) else [],
                    "vms": counts.get(node_name, {}).get("vms", 0),
                    "lxc": counts.get(node_name, {}).get("lxc", 0),
                    "error": status_error,
                }
            )
    return {"nodes": values, "errors": errors, "total": len(values)}


def node_details(manager: ProxmoxManagerService, connection_id: str, node: str) -> dict[str, Any]:
    connection = _connections(manager, connection_id)[0]
    client = manager._client(connection)
    encoded = urllib.parse.quote(node, safe="")
    known = client.get("nodes") or []
    if not isinstance(known, list) or not any(isinstance(item, dict) and str(item.get("node") or "") == node for item in known):
        raise KeyError("Proxmox node not found")
    paths = {
        "status": f"nodes/{encoded}/status",
        "network": f"nodes/{encoded}/network",
        "dns": f"nodes/{encoded}/dns",
        "subscription": f"nodes/{encoded}/subscription",
        "repositories": f"nodes/{encoded}/apt/repositories",
        "services": f"nodes/{encoded}/services",
    }
    result: dict[str, Any] = {"connection_id": connection_id, "connection_name": connection["name"], "node": node, "errors": {}}
    for key, path in paths.items():
        value, error = _safe_get(client, path)
        result[key] = value
        if error:
            result["errors"][key] = error
    return result


def list_storage(manager: ProxmoxManagerService, connection_id: str = "") -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for connection in _connections(manager, connection_id):
        client = manager._client(connection)
        try:
            raw_nodes = client.get("nodes") or []
        except ProxmoxApiError as error:
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": str(error)})
            continue
        if not isinstance(raw_nodes, list):
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": "Proxmox nodes response is invalid"})
            continue
        for node in raw_nodes:
            if not isinstance(node, dict) or not node.get("node"):
                continue
            node_name = str(node["node"])
            encoded = urllib.parse.quote(node_name, safe="")
            raw_storage, storage_error = _safe_get(client, f"nodes/{encoded}/storage")
            if storage_error:
                errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": storage_error})
                continue
            if not isinstance(raw_storage, list):
                errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": f"Invalid storage response for {node_name}"})
                continue
            for item in raw_storage:
                if not isinstance(item, dict):
                    continue
                total = _safe_int(item.get("total"), 0, minimum=0)
                used = _safe_int(item.get("used"), 0, minimum=0)
                values.append(
                    {
                        "connection_id": connection["id"],
                        "connection_name": connection["name"],
                        "node": node_name,
                        "storage": str(item.get("storage") or ""),
                        "type": str(item.get("type") or ""),
                        "status": "available" if _safe_bool(item.get("active"), True) else "unavailable",
                        "total": total,
                        "used": used,
                        "free": _safe_int(item.get("avail"), max(0, total - used), minimum=0),
                        "utilization": (used / total) if total else 0.0,
                        "shared": _safe_bool(item.get("shared"), False),
                        "content": str(item.get("content") or ""),
                        "enabled": _safe_bool(item.get("enabled"), True),
                    }
                )
    return {"storage": values, "errors": errors, "total": len(values)}


def cluster_health(manager: ProxmoxManagerService, connection_id: str = "") -> dict[str, Any]:
    clusters: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for connection in _connections(manager, connection_id):
        client = manager._client(connection)
        try:
            status = client.get("cluster/status") or []
        except ProxmoxApiError as error:
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": str(error)})
            continue
        if not isinstance(status, list):
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": "Proxmox cluster status response is invalid"})
            continue
        ha_resources, ha_resource_error = _safe_get(client, "cluster/ha/resources")
        ha_groups, ha_group_error = _safe_get(client, "cluster/ha/groups")
        cluster_row = next((item for item in status if isinstance(item, dict) and item.get("type") == "cluster"), {})
        node_rows = [item for item in status if isinstance(item, dict) and item.get("type") == "node"]
        errors_map = {}
        if ha_resource_error:
            errors_map["ha_resources"] = ha_resource_error
        if ha_group_error:
            errors_map["ha_groups"] = ha_group_error
        clusters.append(
            {
                "connection_id": connection["id"],
                "connection_name": connection["name"],
                "name": str(cluster_row.get("name") or connection["name"]),
                "quorate": _safe_bool(cluster_row.get("quorate"), True),
                "nodes": node_rows,
                "votes": sum(_safe_int(item.get("votes"), 0, minimum=0) for item in node_rows),
                "online_nodes": sum(_safe_bool(item.get("online"), str(item.get("status") or "") == "online") for item in node_rows),
                "ha_resources": [dict(item) for item in ha_resources if isinstance(item, dict)] if isinstance(ha_resources, list) else [],
                "ha_groups": [dict(item) for item in ha_groups if isinstance(item, dict)] if isinstance(ha_groups, list) else [],
                "errors": errors_map,
            }
        )
    return {"clusters": clusters, "errors": errors, "total": len(clusters)}


def _resource(manager: ProxmoxManagerService, connection: dict[str, Any], vmid: int) -> dict[str, Any]:
    resource = next(
        (
            item
            for item in manager._resources(connection)
            if isinstance(item, dict) and _safe_int(item.get("vmid"), -1, minimum=0) == vmid
        ),
        None,
    )
    if resource is None:
        raise KeyError("Proxmox VM not found")
    return resource


def vm_details(manager: ProxmoxManagerService, connection_id: str, vmid: int) -> dict[str, Any]:
    connection = _connections(manager, connection_id)[0]
    resource = _resource(manager, connection, vmid)
    client = manager._client(connection)
    node = urllib.parse.quote(str(resource["node"]), safe="")
    resource_type = str(resource["type"])
    base = f"nodes/{node}/{resource_type}/{vmid}"
    config = client.get(f"{base}/config")
    if not isinstance(config, dict):
        raise ProxmoxApiError("Proxmox VM configuration response is invalid")
    status, status_error = _safe_get(client, f"{base}/status/current")
    status = status if isinstance(status, dict) else {}
    os_info: Any = None
    guest_network: Any = None
    guest_error = ""
    if resource_type == "qemu" and resource.get("status") == "running":
        os_info, os_error = _safe_get(client, f"{base}/agent/get-osinfo")
        guest_network, network_error = _safe_get(client, f"{base}/agent/network-get-interfaces")
        guest_error = os_error or network_error
    elif resource_type == "lxc":
        guest_network, guest_error = _safe_get(client, f"{base}/interfaces")
    hosts = _host_map(manager, connection_id)
    host = hosts.get((connection_id, str(vmid)))
    hardware = _hardware_from_config(config, resource_type)
    return {
        **resource,
        "connection_id": connection_id,
        "connection_name": connection["name"],
        "host_id": host.get("id") if host else None,
        "host_address": host.get("address") if host else "",
        "host_active": bool(host.get("active")) if host else False,
        "host_approved": bool(host.get("approved")) if host else False,
        "host_tags": list(host.get("tags") or []) if host else [],
        "config": config,
        "current_status": status,
        "hardware": hardware,
        "os": os_info or config.get("ostype") or "",
        "guest_network": guest_network,
        "qemu_guest_agent": bool(resource_type == "qemu" and not guest_error and guest_network is not None),
        "errors": {key: value for key, value in {"status": status_error, "guest": guest_error}.items() if value},
    }


def templates(manager: ProxmoxManagerService, connection_id: str = "") -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for connection in _connections(manager, connection_id):
        try:
            raw = manager._client(connection).get("cluster/resources?type=vm") or []
        except ProxmoxApiError as error:
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": str(error)})
            continue
        if not isinstance(raw, list):
            errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": "Proxmox template response is invalid"})
            continue
        for item in raw:
            if not isinstance(item, dict) or not _safe_bool(item.get("template"), False):
                continue
            resource_type = manager._resource_type(item)
            vmid = _safe_int(item.get("vmid"), -1, minimum=0)
            if not resource_type or vmid < 0:
                continue
            values.append(
                {
                    "connection_id": connection["id"],
                    "connection_name": connection["name"],
                    "vmid": vmid,
                    "name": str(item.get("name") or f"{resource_type}-{vmid}"),
                    "node": str(item.get("node") or ""),
                    "type": resource_type,
                    "tags": manager._parse_proxmox_tags(item.get("tags")),
                    "maxcpu": _safe_int(item.get("maxcpu"), 0, minimum=0),
                    "maxmem": _safe_int(item.get("maxmem"), 0, minimum=0),
                    "maxdisk": _safe_int(item.get("maxdisk"), 0, minimum=0),
                }
            )
    return {"templates": values, "errors": errors, "total": len(values)}


def backups(manager: ProxmoxManagerService, connection_id: str, vmid: int) -> dict[str, Any]:
    connection = _connections(manager, connection_id)[0]
    client = manager._client(connection)
    nodes = client.get("nodes") or []
    values: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if not isinstance(nodes, list):
        return {"backups": values, "errors": [{"node": "", "storage": "", "error": "Proxmox nodes response is invalid"}], "total": 0}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("node"):
            continue
        node_name = str(node["node"])
        encoded_node = urllib.parse.quote(node_name, safe="")
        stores, store_error = _safe_get(client, f"nodes/{encoded_node}/storage")
        if store_error:
            errors.append({"node": node_name, "storage": "", "error": store_error})
            continue
        if not isinstance(stores, list):
            errors.append({"node": node_name, "storage": "", "error": "Proxmox storage response is invalid"})
            continue
        for store in stores:
            if not isinstance(store, dict) or not store.get("storage"):
                continue
            content = str(store.get("content") or "")
            if "backup" not in content:
                continue
            storage_name = str(store["storage"])
            encoded_storage = urllib.parse.quote(storage_name, safe="")
            items, item_error = _safe_get(client, f"nodes/{encoded_node}/storage/{encoded_storage}/content?content=backup")
            if item_error:
                errors.append({"node": node_name, "storage": storage_name, "error": item_error})
                continue
            if not isinstance(items, list):
                errors.append({"node": node_name, "storage": storage_name, "error": "Proxmox backup response is invalid"})
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                volid = str(item.get("volid") or "")
                match = _BACKUP_VMID.search(volid)
                if not match or _safe_int(match.group(1), -1) != vmid:
                    continue
                values.append(
                    {
                        "backup": volid.rsplit("/", 1)[-1],
                        "volid": volid,
                        "vmid": vmid,
                        "date": _safe_int(item.get("ctime"), 0, minimum=0),
                        "size": _safe_int(item.get("size"), 0, minimum=0),
                        "storage": storage_name,
                        "node": node_name,
                    }
                )
    values.sort(key=lambda item: item["date"], reverse=True)
    return {"backups": values, "errors": errors, "total": len(values)}
