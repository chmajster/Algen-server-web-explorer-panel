from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .collectors.inventory import ExtendedInventoryCollector
from .collectors.io import DiskIoCollector
from .collectors.lvm import LvmCollector
from .collectors.mounts import MountCollector
from .collectors.pools import PoolCollector
from .collectors.probe import ALLOWED_DETAIL_TOOLS, Runner, StorageReadOnlyProbe
from .service import CommandResult, StorageInventoryService, _integer, _number, service as inventory_service


MANAGEMENT_GUARDRAILS = (
    "dedicated-rbac",
    "csrf",
    "preview",
    "explicit-confirmation",
    "privileged-broker",
    "audit-log",
    "protected-system-devices",
    "rollback-when-supported",
)


def _flatten_devices(devices: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(item: dict[str, Any]) -> None:
        result.append(item)
        for child in item.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for item in devices or []:
        if isinstance(item, dict):
            visit(item)
    return result


class StorageDetailsService:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        tool_resolver: Callable[[str], str | None] | None = None,
        fstab_path: Path = Path("/etc/fstab"),
        diskstats_path: Path = Path("/proc/diskstats"),
        mdstat_path: Path = Path("/proc/mdstat"),
        inventory: StorageInventoryService | None = None,
    ) -> None:
        self.probe = StorageReadOnlyProbe(runner=runner, tool_resolver=tool_resolver)
        self.inventory_collector = ExtendedInventoryCollector(inventory or inventory_service())
        self.lvm_collector = LvmCollector(self.probe)
        self.mount_collector = MountCollector(self.probe, fstab_path=fstab_path)
        self.io_collector = DiskIoCollector(diskstats_path=diskstats_path)
        self.pool_collector = PoolCollector(self.probe, mdstat_path=mdstat_path)

    def tool_available(self, name: str) -> bool:
        return self.probe.tool_available(name)

    def _run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:
        return self.probe.run(name, args, timeout=timeout)

    @staticmethod
    def parse_fstab(
        content: str,
        filesystems: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return MountCollector.parse_fstab(content, filesystems, devices)

    @staticmethod
    def parse_diskstats(content: str, names: set[str] | None = None) -> list[dict[str, Any]]:
        return DiskIoCollector.parse_diskstats(content, names)

    def lvm(self) -> dict[str, Any]:
        return self.lvm_collector.collect()

    def swap(self) -> list[dict[str, Any]]:
        return self.mount_collector.swap()

    def fstab(
        self,
        filesystems: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return self.mount_collector.fstab(filesystems, devices)

    def mounts(
        self,
        *,
        filesystems: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self.mount_collector.snapshot(filesystems=filesystems, devices=devices)

    def disk_io(self, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return self.io_collector.collect(devices)

    def io_sample(self, devices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self.io_collector.sample(devices)

    def pools(self, filesystems: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self.pool_collector.collect(filesystems=filesystems)

    @staticmethod
    def dashboard(
        *,
        devices: list[dict[str, Any]] | None,
        filesystems: list[dict[str, Any]] | None,
        health: list[dict[str, Any]] | None,
        lvm: dict[str, Any],
        pools: dict[str, Any],
    ) -> dict[str, Any]:
        flattened = _flatten_devices(devices)
        physical = [item for item in flattened if item.get("type") == "disk"]
        mapper = [item for item in flattened if bool(item.get("device_mapper"))]
        encrypted = [item for item in flattened if bool(item.get("encrypted"))]
        unhealthy = [item for item in health or [] if str(item.get("state")) in {"failed", "warning", "degraded"}]
        low_space: list[dict[str, Any]] = []
        for item in filesystems or []:
            free_percent = _number(item.get("free_percent"))
            if _integer(item.get("total")) >= 1024**3 and free_percent is not None and free_percent < 10.0:
                low_space.append(item)
        zfs = pools.get("zfs") if isinstance(pools, dict) else {}
        return {
            "physical_disks": len(physical),
            "total_physical_capacity": sum(_integer(item.get("size")) for item in physical),
            "filesystems": len(filesystems or []),
            "lvm_pv": len(lvm.get("physical_volumes") or []),
            "lvm_vg": len(lvm.get("volume_groups") or []),
            "lvm_lv": len(lvm.get("logical_volumes") or []),
            "raid_arrays": len(pools.get("raid") or []),
            "zfs_pools": len(zfs.get("pools") or []) if isinstance(zfs, dict) else 0,
            "btrfs_filesystems": len(pools.get("btrfs") or []),
            "unhealthy_devices": len(unhealthy),
            "low_space_filesystems": len(low_space),
            "device_mapper_entries": len(mapper),
            "encrypted_entries": len(encrypted),
        }

    def snapshot(
        self,
        *,
        devices: list[dict[str, Any]] | None = None,
        filesystems: list[dict[str, Any]] | None = None,
        health: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        extended_devices = self.inventory_collector.devices() or (devices or [])
        extended_health = self.inventory_collector.health(extended_devices) or (health or [])
        lvm = self.lvm()
        mounts = self.mounts(filesystems=filesystems, devices=extended_devices)
        io_sample = self.io_sample(extended_devices)
        pools = self.pools(filesystems)
        return {
            "read_only": True,
            "generated_at": time.time(),
            "duration_ms": round((time.time() - started) * 1000, 1),
            "tools": {name: self.tool_available(name) for name in sorted(ALLOWED_DETAIL_TOOLS)},
            "dashboard": self.dashboard(devices=extended_devices, filesystems=filesystems, health=extended_health, lvm=lvm, pools=pools),
            "devices": extended_devices,
            "device_health": extended_health,
            "lvm": lvm,
            "swap": mounts["swap"],
            "fstab": mounts["persistent"],
            "mounts": mounts,
            "disk_io": io_sample["devices"],
            "io": io_sample,
            "pools": pools,
            "management": {
                "mode": "read-only",
                "write_api_enabled": False,
                "future_guardrails": list(MANAGEMENT_GUARDRAILS),
            },
        }


_details_service: StorageDetailsService | None = None
_details_service_lock = threading.Lock()


def details_service() -> StorageDetailsService:
    global _details_service
    with _details_service_lock:
        if _details_service is None:
            _details_service = StorageDetailsService()
        return _details_service
