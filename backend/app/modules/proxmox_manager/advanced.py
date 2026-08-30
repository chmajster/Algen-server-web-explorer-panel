from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from collections import defaultdict
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import Permission, authorize, require_permission
from ...security import SessionUser
from .inventory import cluster_health, list_nodes, list_storage, templates, vm_details
from .service import ProxmoxApiError, ProxmoxApiClient, ProxmoxManagerService, service


router = APIRouter(prefix="/api/modules/proxmox-manager/advanced", tags=["proxmox-manager-advanced"])


FEATURES: list[dict[str, Any]] = [
    {"id": 361, "slug": "cluster-health", "name": "Proxmox Cluster Health", "scope": "quorum, corosync, nodes, storage, HA"},
    {"id": 362, "slug": "placement-advisor", "name": "Proxmox VM Placement Advisor", "scope": "CPU/RAM/storage based node recommendation"},
    {"id": 363, "slug": "capacity-planner", "name": "Proxmox Capacity Planner", "scope": "estimated remaining VM capacity"},
    {"id": 364, "slug": "storage-balancer", "name": "Proxmox Storage Balancer", "scope": "VM/storage distribution recommendations"},
    {"id": 365, "slug": "backup-analyzer", "name": "Proxmox Backup Analyzer", "scope": "vzdump/PBS coverage and missing backups"},
    {"id": 366, "slug": "pbs-manager", "name": "PBS Manager", "scope": "PVE-integrated PBS datastores, snapshots, jobs"},
    {"id": 367, "slug": "replication-manager", "name": "Proxmox Replication Manager", "scope": "ZFS replication jobs"},
    {"id": 368, "slug": "ha-manager", "name": "Proxmox HA Manager", "scope": "HA groups, resources and state"},
    {"id": 369, "slug": "migration-planner", "name": "Proxmox Migration Planner", "scope": "live/offline migration preview"},
    {"id": 370, "slug": "network-planner", "name": "Proxmox Network Planner", "scope": "bridges, bonds, VLAN-aware interfaces"},
    {"id": 371, "slug": "sdn-manager", "name": "Proxmox SDN Manager", "scope": "zones, VNets and subnets"},
    {"id": 372, "slug": "cloud-init-profiles", "name": "Proxmox Cloud-Init Profiles", "scope": "reusable provisioning profiles"},
    {"id": 373, "slug": "vm-policy-manager", "name": "Proxmox VM Policy Manager", "scope": "naming, tags, limits and backup requirement"},
    {"id": 374, "slug": "orphan-detector", "name": "Proxmox Orphan Detector", "scope": "unused volumes and stale resources"},
    {"id": 375, "slug": "snapshot-retention", "name": "Proxmox Snapshot Retention", "scope": "old snapshot detection and cleanup preview"},
    {"id": 376, "slug": "guest-agent-audit", "name": "Proxmox Guest Agent Audit", "scope": "QGA configured/running status"},
    {"id": 377, "slug": "template-lifecycle", "name": "Proxmox Template Lifecycle", "scope": "template inventory and version metadata"},
    {"id": 378, "slug": "iso-lifecycle", "name": "Proxmox ISO Lifecycle", "scope": "ISO inventory and cleanup candidates"},
    {"id": 379, "slug": "drift-manager", "name": "Proxmox VM Drift Manager", "scope": "expected vs actual CPU/RAM/network/storage"},
    {"id": 380, "slug": "bulk-operations", "name": "Proxmox Bulk Operations", "scope": "group power, snapshot and migration operations"},
]
FEATURE_BY_SLUG = {item["slug"]: item for item in FEATURES}
_DISK_KEY = re.compile(r"^(?:ide|sata|scsi|virtio)\d+$")
_NET_KEY = re.compile(r"^net\d+$")
_VERSION_TAG = re.compile(r"^(?:version|ver|v)-?(.+)$", re.IGNORECASE)
_VM_STORAGE_CONTENT = {"images", "rootdir"}


class CloudInitProfileInput(BaseModel):
    connection_id: str = ""
    name: str = Field(min_length=1, max_length=80)
    username: str = Field(default="", max_length=80)
    ssh_keys: list[str] = Field(default_factory=list, max_length=20)
    ipconfig: str = Field(default="ip=dhcp", max_length=512)
    nameserver: str = Field(default="", max_length=255)
    searchdomain: str = Field(default="", max_length=255)
    packages: list[str] = Field(default_factory=list, max_length=100)
    cicustom: str = Field(default="", max_length=512)
    notes: str = Field(default="", max_length=1000)


class VmPolicyInput(BaseModel):
    connection_id: str = ""
    name: str = Field(min_length=1, max_length=80)
    naming_regex: str = Field(default="", max_length=300)
    required_tags: list[str] = Field(default_factory=list, max_length=50)
    max_cpu: int = Field(default=0, ge=0, le=1024)
    max_memory_mb: int = Field(default=0, ge=0, le=16_777_216)
    require_backup: bool = False

    @field_validator("naming_regex")
    @classmethod
    def validate_regex(cls, value: str) -> str:
        if value:
            re.compile(value)
        return value


class DriftBaselineInput(BaseModel):
    connection_id: str
    vmid: int = Field(ge=1)
    expected: dict[str, Any]


class SnapshotRetentionApplyInput(BaseModel):
    connection_id: str
    max_age_days: int = Field(default=30, ge=1, le=3650)
    vmids: list[int] = Field(default_factory=list, max_length=500)
    confirmation_text: str


class BulkOperationInput(BaseModel):
    connection_id: str
    action: str
    vmids: list[int] = Field(min_length=1, max_length=500)
    target_node: str = Field(default="", max_length=128)
    snapshot_name: str = Field(default="", max_length=80)
    confirmation_text: str

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"start", "shutdown", "reboot", "stop", "snapshot", "migrate"}:
            raise ValueError("unsupported bulk action")
        return normalized


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, *, failed: bool = False) -> None:
    record_activity(
        ActivityCategory.module,
        action,
        actor,
        target=target,
        details=details or {},
        status=ActivityStatus.failure if failed else ActivityStatus.success,
        source="proxmox-manager",
    )


def _connection(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    if connection_id:
        item = manager.connection(connection_id)
        if not item or not item.get("active"):
            raise KeyError("Proxmox connection not found")
        return item
    active = manager.connections(active_only=True)
    if not active:
        raise KeyError("No active Proxmox connection")
    if len(active) > 1:
        raise ValueError("Multiple Proxmox connections are active; provide connection_id")
    return active[0]


def _client(manager: ProxmoxManagerService, connection_id: str) -> tuple[dict[str, Any], ProxmoxApiClient]:
    item = _connection(manager, connection_id)
    return item, manager._client(item)


def _quote(value: object) -> str:
    return urllib.parse.quote(str(value), safe="")


def _public_error(error: Exception) -> str:
    if isinstance(error, ProxmoxApiError):
        return "Proxmox API request failed"
    if isinstance(error, KeyError):
        return "Requested Proxmox resource was not found"
    if isinstance(error, ValueError):
        return "Invalid Proxmox request"
    return "Proxmox operation failed"


def _safe_get(client: ProxmoxApiClient, path: str, default: Any = None) -> tuple[Any, str]:
    try:
        return client.get(path), ""
    except (ProxmoxApiError, KeyError, ValueError) as error:
        return default, _public_error(error)


def _safe_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _raw_resources(client: ProxmoxApiClient) -> list[dict[str, Any]]:
    raw = client.get("cluster/resources?type=vm")
    resources: list[dict[str, Any]] = []
    for value in raw or []:
        if not isinstance(value, dict):
            continue
        resource_type = str(value.get("type") or "")
        if resource_type not in {"qemu", "lxc"}:
            continue
        try:
            vmid = int(value["vmid"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_tags = value.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(item).strip() for item in raw_tags if str(item).strip()]
        else:
            tags = [item.strip() for item in str(raw_tags or "").split(";") if item.strip()]
        resources.append(
            {
                "vmid": vmid,
                "name": str(value.get("name") or f"{resource_type}-{vmid}"),
                "node": str(value.get("node") or ""),
                "type": resource_type,
                "status": str(value.get("status") or "unknown"),
                "template": bool(value.get("template")),
                "uptime": int(value.get("uptime") or 0),
                "cpu": _safe_number(value.get("cpu")),
                "maxcpu": int(value.get("maxcpu") or 0),
                "mem": int(value.get("mem") or 0),
                "maxmem": int(value.get("maxmem") or 0),
                "disk": int(value.get("disk") or 0),
                "maxdisk": int(value.get("maxdisk") or 0),
                "tags": list(dict.fromkeys(tags)),
            }
        )
    return resources


def _storage_content_tokens(row: dict[str, Any]) -> set[str]:
    raw = row.get("content")
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip() for item in raw if str(item).strip()}
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def _eligible_vm_storage(row: dict[str, Any]) -> bool:
    return (
        bool(row.get("enabled", True))
        and str(row.get("status") or "") != "unavailable"
        and bool(_storage_content_tokens(row) & _VM_STORAGE_CONTENT)
    )


def _unique_storage_slots(storage_rows: list[dict[str, Any]], disk_gb: int) -> int:
    requested_bytes = disk_gb * 1024 * 1024 * 1024
    if requested_bytes <= 0:
        return 0
    pool_free: dict[tuple[str, ...], int] = {}
    for row in storage_rows:
        if not _eligible_vm_storage(row):
            continue
        free_bytes = max(0, int(row.get("total") or 0) - int(row.get("used") or 0))
        storage_name = str(row.get("storage") or "")
        node_name = str(row.get("node") or "")
        key = ("shared", storage_name) if bool(row.get("shared")) else ("local", node_name, storage_name)
        if key[0] == "shared":
            pool_free[key] = max(pool_free.get(key, 0), free_bytes)
        else:
            pool_free[key] = free_bytes
    return sum(free_bytes // requested_bytes for free_bytes in pool_free.values())


def _score_node(
    cpu_utilization: float,
    memory_utilization: float,
    storage_utilization: float,
    *,
    online: bool = True,
) -> float:
    if not online:
        return -1.0
    pressure = (cpu_utilization * 0.40) + (memory_utilization * 0.40) + (storage_utilization * 0.20)
    return round(max(0.0, 100.0 * (1.0 - pressure)), 2)


def _capacity_count(
    free_cpu_cores: float,
    free_memory_bytes: float,
    free_storage_bytes: float,
    cpu_cores: int,
    memory_mb: int,
    disk_gb: int,
) -> int:
    limits: list[int] = []
    if cpu_cores > 0:
        limits.append(max(0, math.floor(free_cpu_cores / cpu_cores)))
    if memory_mb > 0:
        limits.append(max(0, math.floor(free_memory_bytes / (memory_mb * 1024 * 1024))))
    if disk_gb > 0:
        limits.append(max(0, math.floor(free_storage_bytes / (disk_gb * 1024 * 1024 * 1024))))
    return min(limits) if limits else 0


def _parse_storage_from_disk(raw: Any) -> str:
    first = str(raw or "").split(",", 1)[0]
    return first.split(":", 1)[0] if ":" in first else ""


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    disks: dict[str, str] = {}
    networks: dict[str, str] = {}
    for key, value in config.items():
        if _DISK_KEY.fullmatch(str(key)):
            disks[str(key)] = str(value)
        elif _NET_KEY.fullmatch(str(key)):
            networks[str(key)] = str(value)
    return {
        "cores": int(config.get("cores") or 0),
        "sockets": int(config.get("sockets") or 1),
        "memory_mb": int(config.get("memory") or 0),
        "balloon_mb": int(config.get("balloon") or 0),
        "cpu": str(config.get("cpu") or config.get("cputype") or ""),
        "bios": str(config.get("bios") or ""),
        "machine": str(config.get("machine") or ""),
        "agent": config.get("agent", ""),
        "tags": str(config.get("tags") or ""),
        "disks": disks,
        "networks": networks,
    }


def _ensure_advanced_schema(manager: ProxmoxManagerService) -> None:
    with manager.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS advanced_profiles(
                kind TEXT NOT NULL,
                connection_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                updated_by TEXT NOT NULL,
                PRIMARY KEY(kind, connection_id, name)
            );
            CREATE TABLE IF NOT EXISTS advanced_drift_baselines(
                connection_id TEXT NOT NULL,
                vmid INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                updated_by TEXT NOT NULL,
                PRIMARY KEY(connection_id, vmid)
            );
            """
        )


def _save_profile(manager: ProxmoxManagerService, kind: str, connection_id: str, name: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
    _ensure_advanced_schema(manager)
    now = time.time()
    with manager.connect() as connection:
        connection.execute(
            """
            INSERT INTO advanced_profiles(kind,connection_id,name,payload_json,updated_at,updated_by)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(kind,connection_id,name) DO UPDATE SET
                payload_json=excluded.payload_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by
            """,
            (kind, connection_id, name, json.dumps(payload, separators=(",", ":")), now, actor),
        )
    return {"kind": kind, "connection_id": connection_id, "name": name, "payload": payload, "updated_at": now, "updated_by": actor}


def _profiles(manager: ProxmoxManagerService, kind: str, connection_id: str = "") -> list[dict[str, Any]]:
    _ensure_advanced_schema(manager)
    query = "SELECT * FROM advanced_profiles WHERE kind=?"
    params: list[Any] = [kind]
    if connection_id:
        query += " AND connection_id IN ('',?)"
        params.append(connection_id)
    query += " ORDER BY connection_id,name COLLATE NOCASE"
    with manager.connect() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    result = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        result.append(
            {
                "kind": row["kind"],
                "connection_id": row["connection_id"],
                "name": row["name"],
                "payload": payload,
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            }
        )
    return result


def _delete_profile(manager: ProxmoxManagerService, kind: str, connection_id: str, name: str) -> bool:
    _ensure_advanced_schema(manager)
    with manager.connect() as connection:
        return bool(
            connection.execute(
                "DELETE FROM advanced_profiles WHERE kind=? AND connection_id=? AND name=?",
                (kind, connection_id, name),
            ).rowcount
        )


def _save_baseline(manager: ProxmoxManagerService, payload: DriftBaselineInput, actor: str) -> dict[str, Any]:
    _ensure_advanced_schema(manager)
    _connection(manager, payload.connection_id)
    now = time.time()
    normalized = _normalize_expected(payload.expected)
    with manager.connect() as connection:
        connection.execute(
            """
            INSERT INTO advanced_drift_baselines(connection_id,vmid,payload_json,updated_at,updated_by)
            VALUES(?,?,?,?,?)
            ON CONFLICT(connection_id,vmid) DO UPDATE SET
                payload_json=excluded.payload_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by
            """,
            (payload.connection_id, payload.vmid, json.dumps(normalized, separators=(",", ":")), now, actor),
        )
    return {"connection_id": payload.connection_id, "vmid": payload.vmid, "expected": normalized, "updated_at": now, "updated_by": actor}


def _baselines(manager: ProxmoxManagerService, connection_id: str = "") -> list[dict[str, Any]]:
    _ensure_advanced_schema(manager)
    query = "SELECT * FROM advanced_drift_baselines"
    params: tuple[Any, ...] = ()
    if connection_id:
        query += " WHERE connection_id=?"
        params = (connection_id,)
    query += " ORDER BY connection_id,vmid"
    with manager.connect() as connection:
        rows = connection.execute(query, params).fetchall()
    result = []
    for row in rows:
        try:
            expected = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            expected = {}
        result.append({"connection_id": row["connection_id"], "vmid": int(row["vmid"]), "expected": expected, "updated_at": row["updated_at"], "updated_by": row["updated_by"]})
    return result


def _normalize_expected(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"cores", "sockets", "memory_mb", "balloon_mb", "cpu", "bios", "machine", "agent", "tags", "disks", "networks"}
    return {key: value[key] for key in allowed if key in value}


def _policy_violations(vm: dict[str, Any], policy: dict[str, Any], has_backup: bool) -> list[str]:
    violations: list[str] = []
    regex = str(policy.get("naming_regex") or "")
    if regex and not re.fullmatch(regex, str(vm.get("name") or "")):
        violations.append("name")
    required_tags = {str(item) for item in policy.get("required_tags") or []}
    vm_tags = {str(item) for item in vm.get("tags") or []}
    if not required_tags.issubset(vm_tags):
        violations.append("tags")
    max_cpu = int(policy.get("max_cpu") or 0)
    if max_cpu and int(vm.get("maxcpu") or 0) > max_cpu:
        violations.append("cpu")
    max_memory_mb = int(policy.get("max_memory_mb") or 0)
    if max_memory_mb and int(vm.get("maxmem") or 0) > max_memory_mb * 1024 * 1024:
        violations.append("memory")
    if bool(policy.get("require_backup")) and not has_backup:
        violations.append("backup")
    return violations


def _list_storage_content(client: ProxmoxApiClient, nodes: Iterable[dict[str, Any]], content: str = "") -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for node in nodes:
        node_name = str(node.get("node") or "")
        if not node_name:
            continue
        storage_rows, error = _safe_get(client, f"nodes/{_quote(node_name)}/storage", [])
        if error:
            errors.append(error)
            continue
        for storage in storage_rows or []:
            if not isinstance(storage, dict) or not storage.get("storage"):
                continue
            if content and content not in str(storage.get("content") or "").split(","):
                continue
            storage_name = str(storage["storage"])
            params = f"?content={urllib.parse.quote(content)}" if content else ""
            content_rows, content_error = _safe_get(
                client,
                f"nodes/{_quote(node_name)}/storage/{_quote(storage_name)}/content{params}",
                [],
            )
            if content_error:
                errors.append(content_error)
                continue
            for item in content_rows or []:
                if isinstance(item, dict):
                    rows.append({"node": node_name, "storage": storage_name, **dict(item)})
    return rows, errors


def _backup_vmids(rows: Iterable[dict[str, Any]]) -> set[int]:
    values: set[int] = set()
    for row in rows:
        try:
            if row.get("vmid") is not None:
                values.add(int(row["vmid"]))
                continue
        except (TypeError, ValueError):
            pass
        match = re.search(r"vzdump-(?:qemu|lxc)-(\d+)-", str(row.get("volid") or ""))
        if match:
            values.add(int(match.group(1)))
    return values


def _node_storage_utilization(storage_rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in storage_rows:
        node = str(row.get("node") or "")
        if not node or not row.get("enabled", True):
            continue
        totals[node][0] += int(row.get("used") or 0)
        totals[node][1] += int(row.get("total") or 0)
    return {node: (used / total if total else 0.0) for node, (used, total) in totals.items()}


def _report_cluster_health(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection, client = _client(manager, connection_id)
    base = cluster_health(manager, str(connection["id"]))
    nodes = list_nodes(manager, str(connection["id"]))
    storage = list_storage(manager, str(connection["id"]))
    corosync_nodes, corosync_nodes_error = _safe_get(client, "cluster/config/nodes", [])
    corosync_totem, corosync_totem_error = _safe_get(client, "cluster/config/totem", {})
    ha_status, ha_status_error = _safe_get(client, "cluster/ha/status/current", [])
    warnings: list[str] = []
    for row in nodes["nodes"]:
        if str(row.get("status")) not in {"online", "running"}:
            warnings.append(f"Node {row.get('node')} is {row.get('status')}")
        if _safe_number(row.get("cpu")) >= 0.90:
            warnings.append(f"Node {row.get('node')} CPU utilization is >= 90%")
        maxmem = int(row.get("maxmem") or 0)
        if maxmem and int(row.get("mem") or 0) / maxmem >= 0.90:
            warnings.append(f"Node {row.get('node')} RAM utilization is >= 90%")
    for row in storage["storage"]:
        if _safe_number(row.get("utilization")) >= 0.90:
            warnings.append(f"Storage {row.get('storage')} on {row.get('node')} is >= 90% full")
    cluster = base["clusters"][0] if base["clusters"] else {}
    if cluster and not cluster.get("quorate", True):
        warnings.insert(0, "Cluster is not quorate")
    return {
        "feature": FEATURE_BY_SLUG["cluster-health"],
        "connection": {"id": connection["id"], "name": connection["name"]},
        "health": "degraded" if warnings or base["errors"] else "healthy",
        "warnings": warnings,
        "cluster": cluster,
        "nodes": nodes["nodes"],
        "storage": storage["storage"],
        "corosync": {"nodes": corosync_nodes, "totem": corosync_totem},
        "ha_status": ha_status,
        "errors": [*base["errors"], *nodes["errors"], *storage["errors"], *[value for value in [corosync_nodes_error, corosync_totem_error, ha_status_error] if value]],
    }


def _placement_rows(
    manager: ProxmoxManagerService,
    connection_id: str,
    cpu_cores: int,
    memory_mb: int,
    disk_gb: int,
    *,
    nodes: list[dict[str, Any]] | None = None,
    storage_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    connection = _connection(manager, connection_id)
    if nodes is None:
        nodes = list_nodes(manager, str(connection["id"]))["nodes"]
    if storage_rows is None:
        storage_rows = list_storage(manager, str(connection["id"]))["storage"]
    storage_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in storage_rows:
        if _eligible_vm_storage(row):
            storage_by_node[str(row.get("node") or "")].append(row)
    result: list[dict[str, Any]] = []
    for node in nodes:
        maxcpu = max(0, int(node.get("maxcpu") or 0))
        cpu_used = _safe_number(node.get("cpu")) * maxcpu
        free_cpu = max(0.0, maxcpu - cpu_used)
        maxmem = int(node.get("maxmem") or 0)
        free_mem = max(0, maxmem - int(node.get("mem") or 0))
        node_storage = storage_by_node.get(str(node.get("node") or ""), [])
        storage_used = sum(int(row.get("used") or 0) for row in node_storage)
        storage_total = sum(int(row.get("total") or 0) for row in node_storage)
        free_storage = max(
            (max(0, int(row.get("total") or 0) - int(row.get("used") or 0)) for row in node_storage),
            default=0,
        )
        cpu_util = _safe_number(node.get("cpu"))
        mem_util = (int(node.get("mem") or 0) / maxmem) if maxmem else 1.0
        storage_util = (storage_used / storage_total) if storage_total else 1.0
        fits = free_cpu >= cpu_cores and free_mem >= memory_mb * 1024 * 1024 and free_storage >= disk_gb * 1024 * 1024 * 1024
        result.append(
            {
                "node": node.get("node"),
                "online": str(node.get("status")) in {"online", "running"},
                "score": _score_node(cpu_util, mem_util, storage_util, online=str(node.get("status")) in {"online", "running"}) if fits else -1.0,
                "fits": fits,
                "free_cpu_cores": round(free_cpu, 2),
                "free_memory_bytes": free_mem,
                "free_storage_bytes": free_storage,
                "cpu_utilization": cpu_util,
                "memory_utilization": mem_util,
                "storage_utilization": storage_util,
            }
        )
    return sorted(result, key=lambda item: (item["fits"], item["score"]), reverse=True)


def _report_placement(manager: ProxmoxManagerService, connection_id: str, cpu_cores: int, memory_mb: int, disk_gb: int) -> dict[str, Any]:
    rows = _placement_rows(manager, connection_id, cpu_cores, memory_mb, disk_gb)
    return {
        "feature": FEATURE_BY_SLUG["placement-advisor"],
        "request": {"cpu_cores": cpu_cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
        "recommendation": next((row for row in rows if row["fits"] and row["online"]), None),
        "nodes": rows,
    }


def _report_capacity(manager: ProxmoxManagerService, connection_id: str, cpu_cores: int, memory_mb: int, disk_gb: int) -> dict[str, Any]:
    connection = _connection(manager, connection_id)
    storage_rows = list_storage(manager, str(connection["id"]))["storage"]
    rows = _placement_rows(manager, str(connection["id"]), cpu_cores, memory_mb, disk_gb, storage_rows=storage_rows)
    result = []
    compute_slots = 0
    for row in rows:
        count = _capacity_count(
            row["free_cpu_cores"],
            row["free_memory_bytes"],
            row["free_storage_bytes"],
            cpu_cores,
            memory_mb,
            disk_gb,
        ) if row["online"] else 0
        compute_slots += _capacity_count(
            row["free_cpu_cores"],
            row["free_memory_bytes"],
            0,
            cpu_cores,
            memory_mb,
            0,
        ) if row["online"] else 0
        result.append({**row, "estimated_vm_capacity": count})
    storage_slots = _unique_storage_slots(storage_rows, disk_gb)
    return {
        "feature": FEATURE_BY_SLUG["capacity-planner"],
        "request": {"cpu_cores": cpu_cores, "memory_mb": memory_mb, "disk_gb": disk_gb},
        "estimated_vm_capacity": min(compute_slots, storage_slots),
        "compute_limited_capacity": compute_slots,
        "unique_storage_limited_capacity": storage_slots,
        "nodes": result,
        "method": "cluster total is min(sum node CPU/RAM capacity, unique VM-capable storage slots); shared datastores are counted once",
    }


def _report_storage_balancer(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection = _connection(manager, connection_id)
    storage = list_storage(manager, str(connection["id"]))["storage"]
    vms = manager.list_vms(str(connection["id"]))["vms"]
    per_storage: dict[tuple[str, str], dict[str, Any]] = {}
    for row in storage:
        per_storage[(str(row.get("node") or ""), str(row.get("storage") or ""))] = {
            "node": row.get("node"),
            "storage": row.get("storage"),
            "type": row.get("type"),
            "used": int(row.get("used") or 0),
            "total": int(row.get("total") or 0),
            "utilization": _safe_number(row.get("utilization")),
            "shared": bool(row.get("shared")),
            "vmids": [],
        }
    config_errors: list[str] = []
    for vm in vms:
        if vm.get("template"):
            continue
        try:
            details = vm_details(manager, str(connection["id"]), int(vm["vmid"]))
        except (ProxmoxApiError, KeyError, ValueError) as error:
            config_errors.append(_public_error(error))
            continue
        node = str(vm.get("node") or "")
        for disk in details.get("hardware", {}).get("disks", []):
            storage_name = str(disk.get("storage") or "")
            bucket = per_storage.get((node, storage_name))
            if bucket is not None:
                bucket["vmids"].append(int(vm["vmid"]))
    rows = list(per_storage.values())
    rows.sort(key=lambda item: item["utilization"], reverse=True)
    targets = [item for item in rows if item["total"] and item["utilization"] < 0.65]
    recommendations = []
    for source in [item for item in rows if item["utilization"] >= 0.80 and item["vmids"]]:
        target = next(
            (item for item in reversed(targets) if item["node"] == source["node"] and item["storage"] != source["storage"]),
            None,
        ) or next((item for item in reversed(targets) if item["shared"] and item["storage"] != source["storage"]), None)
        if target:
            recommendations.append(
                {
                    "source": {"node": source["node"], "storage": source["storage"], "utilization": source["utilization"]},
                    "target": {"node": target["node"], "storage": target["storage"], "utilization": target["utilization"]},
                    "candidate_vmids": source["vmids"],
                    "reason": "source >= 80% and target < 65%",
                }
            )
    return {"feature": FEATURE_BY_SLUG["storage-balancer"], "storage": rows, "recommendations": recommendations, "errors": config_errors}


def _report_backup(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection, client = _client(manager, connection_id)
    nodes, node_error = _safe_get(client, "nodes", [])
    backups, errors = _list_storage_content(client, nodes or [], "backup")
    jobs, jobs_error = _safe_get(client, "cluster/backup", [])
    resources = [item for item in manager._resources(connection, client) if not item.get("template")]
    backed_up = _backup_vmids(backups)
    missing = [
        {"vmid": int(vm["vmid"]), "name": vm["name"], "node": vm["node"], "type": vm["type"]}
        for vm in resources
        if int(vm["vmid"]) not in backed_up
    ]
    return {
        "feature": FEATURE_BY_SLUG["backup-analyzer"],
        "backup_jobs": jobs or [],
        "backups": backups,
        "covered_vmids": sorted(backed_up),
        "missing_backups": missing,
        "coverage_percent": round(100.0 * (len(resources) - len(missing)) / len(resources), 2) if resources else 100.0,
        "errors": [value for value in [node_error, jobs_error, *errors] if value],
    }


def _report_pbs(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection, client = _client(manager, connection_id)
    nodes, node_error = _safe_get(client, "nodes", [])
    storage = list_storage(manager, str(connection["id"]))["storage"]
    pbs_rows = [row for row in storage if str(row.get("type") or "").lower() == "pbs"]
    snapshots: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in pbs_rows:
        content, error = _safe_get(
            client,
            f"nodes/{_quote(row['node'])}/storage/{_quote(row['storage'])}/content?content=backup",
            [],
        )
        if error:
            errors.append(error)
        for item in content or []:
            if isinstance(item, dict):
                snapshots.append({"node": row["node"], "storage": row["storage"], **dict(item)})
    backup_jobs, backup_error = _safe_get(client, "cluster/backup", [])
    return {
        "feature": FEATURE_BY_SLUG["pbs-manager"],
        "datastores": pbs_rows,
        "snapshots": snapshots,
        "backup_jobs": backup_jobs or [],
        "actions": {
            "verify": "Direct PBS verify jobs require a dedicated PBS API connection/credential; PVE exposes datastore content but not the full PBS admin API.",
            "prune": "Prune policy is visible through backup/storage configuration; direct PBS prune execution is intentionally not proxied with a PVE token.",
            "sync": "PBS sync jobs are managed by PBS itself and require a PBS API connection.",
        },
        "errors": [value for value in [node_error, backup_error, *errors] if value],
        "nodes": nodes or [],
    }


def _report_replication(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    jobs, error = _safe_get(client, "cluster/replication", [])
    return {"feature": FEATURE_BY_SLUG["replication-manager"], "jobs": jobs or [], "errors": [error] if error else []}


def _report_ha(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    resources, e1 = _safe_get(client, "cluster/ha/resources", [])
    groups, e2 = _safe_get(client, "cluster/ha/groups", [])
    status, e3 = _safe_get(client, "cluster/ha/status/current", [])
    return {
        "feature": FEATURE_BY_SLUG["ha-manager"],
        "resources": resources or [],
        "groups": groups or [],
        "status": status or [],
        "errors": [value for value in [e1, e2, e3] if value],
    }


def _report_migration(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection, client = _client(manager, connection_id)
    nodes = list_nodes(manager, str(connection["id"]))["nodes"]
    storage_rows = list_storage(manager, str(connection["id"]))["storage"]
    rows: list[dict[str, Any]] = []
    for vm in [item for item in _raw_resources(client) if not item.get("template")]:
        required_cpu = max(1, int(vm.get("maxcpu") or 1))
        required_memory_mb = max(128, math.ceil(int(vm.get("maxmem") or 0) / (1024 * 1024)))
        required_disk_gb = max(1, math.ceil(int(vm.get("maxdisk") or 0) / (1024 * 1024 * 1024)))
        placements = {
            row["node"]: row
            for row in _placement_rows(
                manager,
                str(connection["id"]),
                required_cpu,
                required_memory_mb,
                required_disk_gb,
                nodes=nodes,
                storage_rows=storage_rows,
            )
        }
        candidates = [
            {
                "node": node.get("node"),
                "online": str(node.get("status")) in {"online", "running"},
                "fits": bool(placements.get(str(node.get("node")), {}).get("fits")),
                "score": placements.get(str(node.get("node")), {}).get("score", -1),
                "live_supported": vm.get("type") == "qemu" and vm.get("status") == "running",
            }
            for node in nodes
            if str(node.get("node") or "") != str(vm.get("node") or "")
        ]
        candidates.sort(key=lambda item: (item["fits"], item["score"]), reverse=True)
        rows.append(
            {
                "vmid": vm["vmid"],
                "name": vm["name"],
                "type": vm["type"],
                "status": vm["status"],
                "source_node": vm["node"],
                "required": {"cpu_cores": required_cpu, "memory_mb": required_memory_mb, "disk_gb": required_disk_gb},
                "recommended_target": next((item for item in candidates if item["online"] and item["fits"]), None),
                "targets": candidates,
            }
        )
    return {"feature": FEATURE_BY_SLUG["migration-planner"], "vms": rows}


def _report_network(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    nodes, node_error = _safe_get(client, "nodes", [])
    interfaces: list[dict[str, Any]] = []
    errors: list[str] = []
    for node in nodes or []:
        name = str(node.get("node") or "")
        if not name:
            continue
        values, error = _safe_get(client, f"nodes/{_quote(name)}/network", [])
        if error:
            errors.append(error)
        for item in values or []:
            if isinstance(item, dict):
                interfaces.append(
                    {
                        "node": name,
                        **dict(item),
                        "vlan_aware": bool(item.get("bridge_vlan_aware")),
                    }
                )
    return {
        "feature": FEATURE_BY_SLUG["network-planner"],
        "interfaces": interfaces,
        "bridges": [item for item in interfaces if str(item.get("type") or "") in {"bridge", "OVSBridge"}],
        "bonds": [item for item in interfaces if "bond" in str(item.get("type") or "").lower()],
        "errors": [value for value in [node_error, *errors] if value],
    }


def _report_sdn(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    zones, e1 = _safe_get(client, "cluster/sdn/zones", [])
    vnets, e2 = _safe_get(client, "cluster/sdn/vnets", [])
    subnets, e3 = _safe_get(client, "cluster/sdn/subnets", [])
    controllers, e4 = _safe_get(client, "cluster/sdn/controllers", [])
    return {
        "feature": FEATURE_BY_SLUG["sdn-manager"],
        "zones": zones or [],
        "vnets": vnets or [],
        "subnets": subnets or [],
        "controllers": controllers or [],
        "errors": [value for value in [e1, e2, e3, e4] if value],
    }


def _report_cloud_init(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection = _connection(manager, connection_id)
    profiles = _profiles(manager, "cloud-init", str(connection["id"]))
    detected: list[dict[str, Any]] = []
    for vm in manager._resources(connection):
        if vm.get("type") != "qemu" or vm.get("template"):
            continue
        try:
            details = vm_details(manager, str(connection["id"]), int(vm["vmid"]))
        except (ProxmoxApiError, KeyError, ValueError):
            continue
        config = details.get("config") or {}
        cloud_init_keys = {key: config.get(key) for key in ("ciuser", "cipassword", "sshkeys", "ipconfig0", "nameserver", "searchdomain", "cicustom") if config.get(key) not in (None, "")}
        has_cloudinit_disk = any("cloudinit" in str(value).lower() for key, value in config.items() if _DISK_KEY.fullmatch(str(key)))
        if cloud_init_keys or has_cloudinit_disk:
            detected.append({"vmid": vm["vmid"], "name": vm["name"], "node": vm["node"], "settings": cloud_init_keys, "cloudinit_disk": has_cloudinit_disk})
    return {"feature": FEATURE_BY_SLUG["cloud-init-profiles"], "profiles": profiles, "detected_vms": detected}


def _report_vm_policy(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection, client = _client(manager, connection_id)
    policies = _profiles(manager, "vm-policy", str(connection["id"]))
    nodes, _ = _safe_get(client, "nodes", [])
    backups, _ = _list_storage_content(client, nodes or [], "backup")
    covered = _backup_vmids(backups)
    resources = [item for item in manager._resources(connection, client) if not item.get("template")]
    audit: list[dict[str, Any]] = []
    for profile in policies:
        policy = profile["payload"]
        for vm in resources:
            violations = _policy_violations(vm, policy, int(vm["vmid"]) in covered)
            if violations:
                audit.append({"policy": profile["name"], "vmid": vm["vmid"], "name": vm["name"], "violations": violations})
    return {"feature": FEATURE_BY_SLUG["vm-policy-manager"], "policies": policies, "violations": audit, "compliant": not audit}


def _report_orphans(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    nodes, node_error = _safe_get(client, "nodes", [])
    content, errors = _list_storage_content(client, nodes or [])
    known_vmids = {int(item["vmid"]) for item in _raw_resources(client)}
    orphans = []
    for row in content:
        content_type = str(row.get("content") or "")
        if content_type not in {"images", "rootdir"}:
            continue
        try:
            vmid = int(str(row.get("vmid") or ""))
        except (TypeError, ValueError):
            match = re.search(r"(?:vm|base)-(\d+)-", str(row.get("volid") or ""))
            vmid = int(match.group(1)) if match else 0
        if vmid and vmid not in known_vmids:
            orphans.append({**row, "detected_vmid": vmid, "reason": "volume references a VMID that is not present in cluster resources"})
    return {"feature": FEATURE_BY_SLUG["orphan-detector"], "orphans": orphans, "known_vmids": sorted(known_vmids), "errors": [value for value in [node_error, *errors] if value]}


def _snapshot_candidates(manager: ProxmoxManagerService, connection_id: str, max_age_days: int, only_vmids: set[int] | None = None) -> list[dict[str, Any]]:
    connection, client = _client(manager, connection_id)
    cutoff = time.time() - max_age_days * 86400
    candidates: list[dict[str, Any]] = []
    for vm in manager._resources(connection, client):
        if vm.get("template") or (only_vmids and int(vm["vmid"]) not in only_vmids):
            continue
        base = f"nodes/{_quote(vm['node'])}/{vm['type']}/{int(vm['vmid'])}/snapshot"
        rows, error = _safe_get(client, base, [])
        if error:
            continue
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if not name or name == "current":
                continue
            created = _safe_number(row.get("snaptime"))
            if created and created < cutoff:
                candidates.append(
                    {
                        "vmid": int(vm["vmid"]),
                        "vm_name": vm["name"],
                        "node": vm["node"],
                        "type": vm["type"],
                        "snapshot": name,
                        "snaptime": created,
                        "age_days": round((time.time() - created) / 86400, 1),
                    }
                )
    return candidates


def _report_snapshot_retention(manager: ProxmoxManagerService, connection_id: str, max_age_days: int) -> dict[str, Any]:
    connection = _connection(manager, connection_id)
    candidates = _snapshot_candidates(manager, str(connection["id"]), max_age_days)
    return {"feature": FEATURE_BY_SLUG["snapshot-retention"], "max_age_days": max_age_days, "candidates": candidates, "count": len(candidates), "destructive_action": "POST /snapshot-retention/apply with confirmation_text=DELETE OLD SNAPSHOTS"}


def _report_guest_agent(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection, client = _client(manager, connection_id)
    rows = []
    for vm in [item for item in manager._resources(connection, client) if item.get("type") == "qemu" and not item.get("template")]:
        base = f"nodes/{_quote(vm['node'])}/qemu/{int(vm['vmid'])}"
        config, config_error = _safe_get(client, f"{base}/config", {})
        configured = bool(str((config or {}).get("agent") or "").split(",", 1)[0] not in {"", "0"})
        running = vm.get("status") == "running"
        ping_ok = False
        ping_error = ""
        if running and configured:
            _, ping_error = _safe_get(client, f"{base}/agent/ping", None)
            ping_ok = not ping_error
        rows.append(
            {
                "vmid": vm["vmid"],
                "name": vm["name"],
                "node": vm["node"],
                "status": vm["status"],
                "configured": configured,
                "running": ping_ok,
                "state": "ok" if configured and (ping_ok or not running) else "missing" if not configured else "not_responding",
                "error": ping_error or config_error,
            }
        )
    return {
        "feature": FEATURE_BY_SLUG["guest-agent-audit"],
        "vms": rows,
        "ok": sum(item["state"] == "ok" for item in rows),
        "missing": sum(item["state"] == "missing" for item in rows),
        "not_responding": sum(item["state"] == "not_responding" for item in rows),
    }


def _report_templates(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection = _connection(manager, connection_id)
    result = templates(manager, str(connection["id"]))
    rows = []
    for vm in result["templates"]:
        try:
            details = vm_details(manager, str(connection["id"]), int(vm["vmid"]))
            config = details.get("config") or {}
        except (ProxmoxApiError, KeyError, ValueError):
            config = {}
        tags = list(vm.get("tags") or [])
        version = next((match.group(1) for tag in tags if (match := _VERSION_TAG.match(str(tag)))), "")
        rows.append(
            {
                **vm,
                "version": version,
                "description": str(config.get("description") or ""),
                "ostype": str(config.get("ostype") or ""),
                "machine": str(config.get("machine") or ""),
                "bios": str(config.get("bios") or ""),
                "cloud_init": any("cloudinit" in str(value).lower() for key, value in config.items() if _DISK_KEY.fullmatch(str(key))),
            }
        )
    return {"feature": FEATURE_BY_SLUG["template-lifecycle"], "templates": rows, "errors": result["errors"]}


def _report_iso(manager: ProxmoxManagerService, connection_id: str, max_age_days: int) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    nodes, node_error = _safe_get(client, "nodes", [])
    isos, errors = _list_storage_content(client, nodes or [], "iso")
    cutoff = time.time() - max_age_days * 86400
    cleanup = []
    for row in isos:
        created = _safe_number(row.get("ctime"))
        if created and created < cutoff:
            cleanup.append({**row, "age_days": round((time.time() - created) / 86400, 1)})
    return {"feature": FEATURE_BY_SLUG["iso-lifecycle"], "isos": isos, "cleanup_candidates": cleanup, "max_age_days": max_age_days, "errors": [value for value in [node_error, *errors] if value]}


def _report_drift(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    connection = _connection(manager, connection_id)
    baselines = _baselines(manager, str(connection["id"]))
    rows = []
    for baseline in baselines:
        vmid = int(baseline["vmid"])
        try:
            details = vm_details(manager, str(connection["id"]), vmid)
            actual = _config_summary(details.get("config") or {})
            expected = baseline["expected"]
            differences = {
                key: {"expected": expected[key], "actual": actual.get(key)}
                for key in expected
                if actual.get(key) != expected[key]
            }
            rows.append({"vmid": vmid, "name": details.get("name"), "node": details.get("node"), "drifted": bool(differences), "differences": differences, "expected": expected, "actual": actual})
        except (ProxmoxApiError, KeyError, ValueError) as error:
            rows.append({"vmid": vmid, "drifted": True, "differences": {"resource": {"expected": "present", "actual": "missing"}}, "error": _public_error(error)})
    return {"feature": FEATURE_BY_SLUG["drift-manager"], "baselines": baselines, "vms": rows, "drifted": sum(item["drifted"] for item in rows)}


def _report_bulk(manager: ProxmoxManagerService, connection_id: str) -> dict[str, Any]:
    _, client = _client(manager, connection_id)
    resources = [item for item in _raw_resources(client) if not item.get("template")]
    by_status: dict[str, int] = defaultdict(int)
    by_node: dict[str, int] = defaultdict(int)
    for vm in resources:
        by_status[str(vm.get("status") or "unknown")] += 1
        by_node[str(vm.get("node") or "")] += 1
    return {
        "feature": FEATURE_BY_SLUG["bulk-operations"],
        "resources": resources,
        "summary": {"total": len(resources), "by_status": dict(by_status), "by_node": dict(by_node)},
        "supported_actions": ["start", "shutdown", "reboot", "stop", "snapshot", "migrate"],
        "confirmation": "BULK <ACTION>",
    }


_REPORTS = {
    "cluster-health": _report_cluster_health,
    "storage-balancer": _report_storage_balancer,
    "backup-analyzer": _report_backup,
    "pbs-manager": _report_pbs,
    "replication-manager": _report_replication,
    "ha-manager": _report_ha,
    "migration-planner": _report_migration,
    "network-planner": _report_network,
    "sdn-manager": _report_sdn,
    "cloud-init-profiles": _report_cloud_init,
    "vm-policy-manager": _report_vm_policy,
    "orphan-detector": _report_orphans,
    "guest-agent-audit": _report_guest_agent,
    "template-lifecycle": _report_templates,
    "drift-manager": _report_drift,
    "bulk-operations": _report_bulk,
}


@router.get("/catalog")
def catalog(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    return {"features": FEATURES, "total": len(FEATURES)}


@router.get("/reports/{feature}")
def report(
    feature: str,
    connection_id: str = Query("", max_length=64),
    cpu_cores: int = Query(2, ge=1, le=1024),
    memory_mb: int = Query(2048, ge=128, le=16_777_216),
    disk_gb: int = Query(32, ge=1, le=1_048_576),
    max_age_days: int = Query(30, ge=1, le=3650),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    manager = service()
    if feature not in FEATURE_BY_SLUG:
        raise HTTPException(status_code=404, detail="Unknown Proxmox Advanced feature")
    try:
        if feature == "placement-advisor":
            return _report_placement(manager, connection_id, cpu_cores, memory_mb, disk_gb)
        if feature == "capacity-planner":
            return _report_capacity(manager, connection_id, cpu_cores, memory_mb, disk_gb)
        if feature == "snapshot-retention":
            return _report_snapshot_retention(manager, connection_id, max_age_days)
        if feature == "iso-lifecycle":
            return _report_iso(manager, connection_id, max_age_days)
        handler = _REPORTS.get(feature)
        if not handler:
            raise HTTPException(status_code=501, detail="Feature report is not implemented")
        return handler(manager, connection_id)
    except HTTPException:
        raise
    except KeyError as error:
        raise HTTPException(status_code=404, detail=_public_error(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=_public_error(error)) from error
    except ProxmoxApiError as error:
        raise HTTPException(status_code=502, detail=_public_error(error)) from error


@router.post("/cloud-init-profiles")
def save_cloud_init_profile(
    payload: CloudInitProfileInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    manager = service()
    if payload.connection_id:
        _connection(manager, payload.connection_id)
    result = _save_profile(manager, "cloud-init", payload.connection_id, payload.name, payload.model_dump(exclude={"connection_id", "name"}), user.username)
    _activity(user.username, "proxmox_cloud_init_profile_save", payload.name, {"connection_id": payload.connection_id})
    return result


@router.delete("/cloud-init-profiles/{name}")
def delete_cloud_init_profile(
    name: str,
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    removed = _delete_profile(service(), "cloud-init", connection_id, name)
    _activity(user.username, "proxmox_cloud_init_profile_delete", name, {"connection_id": connection_id, "removed": removed})
    return {"ok": removed}


@router.post("/vm-policies")
def save_vm_policy(
    payload: VmPolicyInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    manager = service()
    if payload.connection_id:
        _connection(manager, payload.connection_id)
    result = _save_profile(manager, "vm-policy", payload.connection_id, payload.name, payload.model_dump(exclude={"connection_id", "name"}), user.username)
    _activity(user.username, "proxmox_vm_policy_save", payload.name, {"connection_id": payload.connection_id})
    return result


@router.delete("/vm-policies/{name}")
def delete_vm_policy(
    name: str,
    connection_id: str = Query("", max_length=64),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    removed = _delete_profile(service(), "vm-policy", connection_id, name)
    _activity(user.username, "proxmox_vm_policy_delete", name, {"connection_id": connection_id, "removed": removed})
    return {"ok": removed}


@router.post("/drift-baselines")
def save_drift_baseline(
    payload: DriftBaselineInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    result = _save_baseline(service(), payload, user.username)
    _activity(user.username, "proxmox_drift_baseline_save", str(payload.vmid), {"connection_id": payload.connection_id})
    return result


@router.delete("/drift-baselines/{vmid}")
def delete_drift_baseline(
    vmid: int,
    connection_id: str,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    manager = service()
    _ensure_advanced_schema(manager)
    with manager.connect() as connection:
        removed = bool(connection.execute("DELETE FROM advanced_drift_baselines WHERE connection_id=? AND vmid=?", (connection_id, vmid)).rowcount)
    _activity(user.username, "proxmox_drift_baseline_delete", str(vmid), {"connection_id": connection_id, "removed": removed})
    return {"ok": removed}


@router.post("/snapshot-retention/apply")
def apply_snapshot_retention(
    payload: SnapshotRetentionApplyInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    if payload.confirmation_text != "DELETE OLD SNAPSHOTS":
        raise HTTPException(status_code=422, detail="confirmation_text must equal DELETE OLD SNAPSHOTS")
    manager = service()
    connection, client = _client(manager, payload.connection_id)
    selected = {int(item) for item in payload.vmids} or None
    candidates = _snapshot_candidates(manager, str(connection["id"]), payload.max_age_days, selected)
    results = []
    for item in candidates:
        path = f"nodes/{_quote(item['node'])}/{item['type']}/{item['vmid']}/snapshot/{_quote(item['snapshot'])}"
        try:
            upid = client.delete(path)
            results.append({**item, "accepted": True, "status": "queued" if upid else "accepted", "task": upid})
        except (ProxmoxApiError, KeyError, ValueError) as error:
            results.append({**item, "accepted": False, "status": "failed", "error": _public_error(error)})
    accepted = sum(item["accepted"] for item in results)
    failed = sum(not item["accepted"] for item in results)
    _activity(
        user.username,
        "proxmox_snapshot_retention_apply",
        str(connection["id"]),
        {"max_age_days": payload.max_age_days, "requested": len(candidates), "accepted": accepted},
        failed=bool(failed),
    )
    return {"results": results, "accepted": accepted, "failed": failed}


@router.post("/bulk")
def bulk_operation(
    payload: BulkOperationInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    expected = f"BULK {payload.action.upper()}"
    if payload.confirmation_text != expected:
        raise HTTPException(status_code=422, detail=f"confirmation_text must equal {expected}")
    action_permission = {
        "start": Permission.HOSTS_MANAGER_POWER_ON,
        "shutdown": Permission.HOSTS_MANAGER_POWER_SHUTDOWN,
        "stop": Permission.HOSTS_MANAGER_POWER_SHUTDOWN,
        "reboot": Permission.HOSTS_MANAGER_POWER_REBOOT,
    }.get(payload.action)
    if action_permission is not None:
        authorize(user, action_permission)
    if payload.action == "migrate" and not payload.target_node:
        raise HTTPException(status_code=422, detail="target_node is required for migrate")
    manager = service()
    connection, client = _client(manager, payload.connection_id)
    resources = {int(item["vmid"]): item for item in _raw_resources(client) if not item.get("template")}
    results: list[dict[str, Any]] = []
    for vmid in list(dict.fromkeys(payload.vmids)):
        vm = resources.get(vmid)
        if not vm:
            results.append({"vmid": vmid, "accepted": False, "status": "failed", "error": "VM not found"})
            continue
        base = f"nodes/{_quote(vm['node'])}/{vm['type']}/{vmid}"
        try:
            if payload.action in {"start", "shutdown", "reboot", "stop"}:
                task = client.post(f"{base}/status/{payload.action}")
            elif payload.action == "snapshot":
                name = payload.snapshot_name or f"webnas-bulk-{int(time.time())}"
                task = client.post(f"{base}/snapshot", {"snapname": name, "description": "Created by WebNAS Proxmox Bulk Operations"})
            else:
                data: dict[str, Any] = {"target": payload.target_node}
                if vm["type"] == "qemu" and vm.get("status") == "running":
                    data["online"] = 1
                task = client.post(f"{base}/migrate", data)
            results.append({"vmid": vmid, "name": vm["name"], "accepted": True, "status": "queued" if task else "accepted", "task": task})
        except (ProxmoxApiError, KeyError, ValueError) as error:
            results.append({"vmid": vmid, "name": vm.get("name"), "accepted": False, "status": "failed", "error": _public_error(error)})
    accepted = sum(item["accepted"] for item in results)
    failed = sum(not item["accepted"] for item in results)
    _activity(
        user.username,
        "proxmox_bulk_operation",
        str(connection["id"]),
        {"action": payload.action, "requested": len(payload.vmids), "accepted": accepted},
        failed=bool(failed),
    )
    return {"action": payload.action, "results": results, "accepted": accepted, "failed": failed}
