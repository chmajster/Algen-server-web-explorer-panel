from __future__ import annotations

import json
from typing import Sequence

from app.modules.storage_manager.collectors.inventory import ExtendedInventoryCollector
from app.modules.storage_manager.service import CommandResult, StorageInventoryService


def test_lsblk_inventory_exposes_partuuid_media_type_mapper_and_encryption() -> None:
    payload = {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "kname": "nvme0n1",
                "path": "/dev/nvme0n1",
                "type": "disk",
                "size": 1000,
                "fstype": None,
                "mountpoints": [None],
                "ro": 0,
                "rm": 0,
                "hotplug": 0,
                "rota": 0,
                "tran": "nvme",
                "children": [
                    {
                        "name": "nvme0n1p2",
                        "kname": "nvme0n1p2",
                        "path": "/dev/nvme0n1p2",
                        "type": "part",
                        "size": 900,
                        "fstype": "crypto_LUKS",
                        "partuuid": "part-123",
                        "mountpoints": [None],
                        "ro": 0,
                        "rm": 0,
                        "hotplug": 0,
                    },
                    {
                        "name": "cryptdata",
                        "kname": "dm-0",
                        "path": "/dev/mapper/cryptdata",
                        "type": "crypt",
                        "size": 800,
                        "fstype": "ext4",
                        "mountpoints": ["/srv/data"],
                        "ro": 0,
                        "rm": 0,
                        "hotplug": 0,
                    },
                ],
            }
        ]
    }

    devices = ExtendedInventoryCollector.parse_lsblk(json.dumps(payload))

    assert devices[0]["media_type"] == "nvme"
    assert devices[0]["rotational"] is False
    partition = devices[0]["children"][0]
    mapper = devices[0]["children"][1]
    assert partition["partuuid"] == "part-123"
    assert partition["encrypted"] is True
    assert mapper["device_mapper"] is True
    assert mapper["encrypted"] is True


def test_smartctl_health_surfaces_sector_warnings() -> None:
    calls: list[list[str]] = []

    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        del timeout
        calls.append(list(argv))
        return CommandResult(
            0,
            json.dumps(
                {
                    "smart_status": {"passed": True},
                    "temperature": {"current": 41},
                    "power_on_time": {"hours": 12000},
                    "ata_smart_attributes": {
                        "table": [
                            {"id": 5, "raw": {"value": 2}},
                            {"id": 197, "raw": {"value": 1}},
                            {"id": 198, "raw": {"value": 0}},
                        ]
                    },
                }
            ),
            "",
        )

    manager = StorageInventoryService(runner=runner, tool_resolver=lambda name: f"/usr/bin/{name}" if name == "smartctl" else None)
    result = ExtendedInventoryCollector(manager)._smart("/dev/sda")

    assert result is not None
    assert result["state"] == "warning"
    assert result["reallocated_sectors"] == 2
    assert result["pending_sectors"] == 1
    assert result["uncorrectable_sectors"] == 0
    assert set(result["warnings"]) == {"reallocated-sectors", "pending-sectors"}
    assert calls[0][1:] == ["-a", "-j", "/dev/sda"]


def test_nvme_health_surfaces_wear_media_errors_and_unsafe_shutdowns() -> None:
    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        del argv, timeout
        return CommandResult(
            0,
            json.dumps(
                {
                    "critical_warning": 0,
                    "temperature": 39,
                    "percentage_used": 94,
                    "avail_spare": 98,
                    "spare_thresh": 10,
                    "media_errors": 3,
                    "unsafe_shutdowns": 7,
                    "num_err_log_entries": 4,
                }
            ),
            "",
        )

    manager = StorageInventoryService(runner=runner, tool_resolver=lambda name: f"/usr/bin/{name}" if name == "nvme" else None)
    result = ExtendedInventoryCollector(manager)._nvme("/dev/nvme0n1")

    assert result is not None
    assert result["state"] == "warning"
    assert result["percentage_used"] == 94
    assert result["media_errors"] == 3
    assert result["unsafe_shutdowns"] == 7
    assert result["error_log_entries"] == 4
    assert set(result["warnings"]) == {"wear-high", "media-errors"}
