from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from app.modules.storage_manager.service import CommandResult, StorageInventoryService, _safe_device_path


LSBLK_FIXTURE = {
    "blockdevices": [
        {
            "name": "sda",
            "kname": "sda",
            "path": "/dev/sda",
            "type": "disk",
            "size": 100000000000,
            "fstype": None,
            "mountpoints": [None],
            "ro": 0,
            "rm": 0,
            "model": "System Disk",
            "serial": "SYS123",
            "tran": "sata",
            "children": [
                {
                    "name": "sda1",
                    "kname": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "size": 99900000000,
                    "fstype": "ext4",
                    "mountpoints": ["/"],
                    "ro": 0,
                    "rm": 0,
                    "pkname": "sda",
                }
            ],
        },
        {
            "name": "nvme1n1",
            "kname": "nvme1n1",
            "path": "/dev/nvme1n1",
            "type": "disk",
            "size": 200000000000,
            "fstype": "xfs",
            "mountpoints": ["/srv/data"],
            "ro": 0,
            "rm": 0,
            "model": "Data NVMe",
            "serial": "DATA456",
            "tran": "nvme",
        },
    ]
}


def test_lsblk_inventory_preserves_topology_and_propagates_protected_root() -> None:
    devices = StorageInventoryService.parse_lsblk(json.dumps(LSBLK_FIXTURE))

    assert len(devices) == 2
    assert devices[0]["path"] == "/dev/sda"
    assert devices[0]["protected"] is True
    assert devices[0]["children"][0]["mountpoints"] == ["/"]
    assert devices[1]["path"] == "/dev/nvme1n1"
    assert devices[1]["protected"] is False
    assert devices[1]["mountpoints"] == ["/srv/data"]


def test_device_path_validator_rejects_shell_and_traversal_input() -> None:
    assert _safe_device_path("/dev/sda") == "/dev/sda"
    assert _safe_device_path("/dev/disk/by-id/wwn-123") == "/dev/disk/by-id/wwn-123"
    assert _safe_device_path("/dev/sda;shutdown -h now") is None
    assert _safe_device_path("/dev/../etc/passwd") is None
    assert _safe_device_path("sda") is None


def test_nvme_probe_uses_fixed_binary_and_kernel_discovered_device_only() -> None:
    calls: list[tuple[list[str], float]] = []

    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        calls.append((list(argv), timeout))
        if argv[0] == "/usr/bin/lsblk":
            return CommandResult(0, json.dumps(LSBLK_FIXTURE), "")
        if argv[0] == "/usr/bin/nvme":
            return CommandResult(
                0,
                json.dumps(
                    {
                        "critical_warning": 0,
                        "temperature": 38,
                        "percentage_used": 7,
                        "avail_spare": 100,
                        "media_errors": 0,
                    }
                ),
                "",
            )
        if argv[0] == "/usr/bin/smartctl":
            return CommandResult(0, json.dumps({"smart_status": {"passed": True}}), "")
        raise AssertionError(f"unexpected command: {argv}")

    resolver = lambda name: f"/usr/bin/{name}" if name in {"lsblk", "nvme", "smartctl"} else None
    manager = StorageInventoryService(runner=runner, tool_resolver=resolver)

    health = manager.device_health(manager.block_devices())

    assert len(health) == 2
    nvme = next(item for item in health if item["device"] == "/dev/nvme1n1")
    assert nvme["provider"] == "nvme"
    assert nvme["state"] == "ok"
    assert nvme["temperature_c"] == 38.0
    assert ["/usr/bin/nvme", "smart-log", "-o", "json", "/dev/nvme1n1"] in [argv for argv, _timeout in calls]
    assert all(";" not in argument for argv, _timeout in calls for argument in argv)


def test_mdstat_parser_marks_missing_member_as_degraded() -> None:
    payload = """Personalities : [raid1]\nmd0 : active raid1 sdb1[0] sdc1[1]\n      976630336 blocks super 1.2 [2/1] [U_]\nunused devices: <none>\n"""

    arrays = StorageInventoryService.parse_mdstat(payload)

    assert arrays == [
        {
            "name": "md0",
            "activity": "active",
            "level": "raid1",
            "members": ["sdb1[0]", "sdc1[1]"],
            "member_state": "U_",
            "state": "degraded",
        }
    ]


def test_snapshot_surfaces_failed_device_array_pool_btrfs_and_low_space() -> None:
    class FixtureStorage(StorageInventoryService):
        def block_devices(self) -> list[dict[str, Any]]:
            return [{"path": "/dev/sdz", "type": "disk", "children": []}]

        def device_health(self, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
            return [{"device": "/dev/sdz", "state": "failed"}]

        def filesystems(self) -> list[dict[str, Any]]:
            return [
                {
                    "source": "/dev/sdz1",
                    "mount_point": "/srv/data",
                    "filesystem": "ext4",
                    "total": 20 * 1024**3,
                    "used": 19 * 1024**3,
                    "free": 1024**3,
                    "free_percent": 5.0,
                    "protected": False,
                    "read_only": False,
                    "options": ["rw"],
                }
            ]

        def md_arrays(self) -> list[dict[str, Any]]:
            return [{"name": "md0", "state": "degraded"}]

        def zfs_pools(self) -> list[dict[str, Any]]:
            return [{"name": "tank", "health": "DEGRADED", "state": "degraded"}]

        def btrfs_filesystems(self, filesystems: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
            return [{"mount_point": "/srv/btrfs", "state": "degraded", "available": True}]

        def tool_available(self, name: str) -> bool:
            return name in {"lsblk", "smartctl"}

    snapshot = FixtureStorage(tool_resolver=lambda _name: None).snapshot()
    codes = {item["code"] for item in snapshot["issues"]}

    assert snapshot["state"] == "critical"
    assert snapshot["read_only"] is True
    assert codes == {
        "device-health-failed",
        "md-array-degraded",
        "zfs-pool-degraded",
        "btrfs-device-errors",
        "filesystem-low-space",
    }


def test_filesystem_inventory_filters_network_and_pseudo_mounts(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    mounts = tmp_path / "mounts"
    mounts.write_text(
        f"/dev/sdz1 {data} ext4 rw,relatime 0 0\nserver:/share /mnt/nfs nfs4 rw 0 0\nproc /proc proc rw 0 0\n",
        encoding="utf-8",
    )
    manager = StorageInventoryService(tool_resolver=lambda _name: None, mounts_path=mounts)

    result = manager.filesystems()

    assert len(result) == 1
    assert result[0]["source"] == "/dev/sdz1"
    assert result[0]["mount_point"] == str(data)
    assert result[0]["filesystem"] == "ext4"
    assert result[0]["total"] > 0
