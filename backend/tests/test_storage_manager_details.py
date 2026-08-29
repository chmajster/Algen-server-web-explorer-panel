from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from app.modules.storage_manager.details import StorageDetailsService
from app.modules.storage_manager.service import CommandResult


def test_lvm_inventory_normalizes_pvs_vgs_lvs_and_relationships() -> None:
    payloads = {
        "pvs": {"report": [{"pv": [{"pv_name": "/dev/sdb1", "vg_name": "data", "pv_size": "107374182400", "pv_free": "53687091200", "pv_attr": "a--"}]}]},
        "vgs": {"report": [{"vg": [{"vg_name": "data", "vg_size": "107374182400", "vg_free": "53687091200", "pv_count": "1", "lv_count": "2", "vg_attr": "wz--n-"}]}]},
        "lvs": {
            "report": [
                {
                    "lv": [
                        {"lv_name": "archive", "vg_name": "data", "lv_path": "/dev/data/archive", "lv_size": "53687091200", "lv_attr": "-wi-a-----", "pool_lv": "", "origin": "", "data_percent": "12.5", "metadata_percent": ""},
                        {"lv_name": "thin", "vg_name": "data", "lv_path": "/dev/data/thin", "lv_size": "21474836480", "lv_attr": "Vwi-a-tz--", "pool_lv": "pool0", "origin": "", "data_percent": "42.0", "metadata_percent": "3.5"},
                    ]
                }
            ]
        },
    }
    calls: list[list[str]] = []

    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        del timeout
        calls.append(list(argv))
        tool = Path(argv[0]).name
        return CommandResult(0, json.dumps(payloads[tool]), "")

    manager = StorageDetailsService(
        runner=runner,
        tool_resolver=lambda name: f"/usr/sbin/{name}" if name in payloads else None,
    )

    result = manager.lvm()

    assert result["available"] is True
    assert result["physical_volumes"][0]["path"] == "/dev/sdb1"
    assert result["physical_volumes"][0]["free"] == 53687091200
    assert result["volume_groups"][0]["name"] == "data"
    assert result["volume_groups"][0]["lv_count"] == 2
    assert result["logical_volumes"][0]["path"] == "/dev/data/archive"
    assert result["logical_volumes"][0]["data_percent"] == 12.5
    assert result["logical_volumes"][1]["thin_pool"] is True
    assert result["relationships"] == [
        {"volume_group": "data", "physical_volumes": ["/dev/sdb1"], "logical_volumes": ["archive", "thin"]}
    ]
    assert {Path(call[0]).name for call in calls} == {"pvs", "vgs", "lvs"}


def test_lvm_inventory_rejects_malicious_device_path() -> None:
    payloads = {
        "pvs": {"report": [{"pv": [{"pv_name": "/dev/sdb1;id", "vg_name": "data", "pv_size": "1", "pv_free": "0", "pv_attr": "a--"}]}]},
        "vgs": {"report": [{"vg": []}]},
        "lvs": {"report": [{"lv": []}]},
    }

    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        del timeout
        return CommandResult(0, json.dumps(payloads[Path(argv[0]).name]), "")

    manager = StorageDetailsService(runner=runner, tool_resolver=lambda name: f"/usr/sbin/{name}")

    assert manager.lvm()["physical_volumes"] == []


def test_swap_inventory_parses_kernel_output() -> None:
    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        del argv, timeout
        return CommandResult(0, "/dev/dm-1 partition 8589934592 1073741824 -2\n/swapfile file 2147483648 0 -3\n", "")

    manager = StorageDetailsService(runner=runner, tool_resolver=lambda name: "/usr/sbin/swapon" if name == "swapon" else None)

    result = manager.swap()

    assert result == [
        {"name": "/dev/dm-1", "type": "partition", "size": 8589934592, "used": 1073741824, "priority": -2},
        {"name": "/swapfile", "type": "file", "size": 2147483648, "used": 0, "priority": -3},
    ]


def test_fstab_inventory_marks_active_disabled_protected_and_resolves_uuid() -> None:
    content = """
# system mounts
UUID=root / ext4 defaults 0 1
PARTUUID=data-part /srv/data xfs defaults,noatime 0 2
/dev/sdc1 /mnt/archive ext4 noauto 0 2
server:/share /mnt/net nfs4 _netdev 0 0
/dev/sdd1 /mnt/../etc ext4 defaults 0 2
"""
    filesystems = [
        {"mount_point": "/", "source": "/dev/mapper/root", "filesystem": "ext4"},
        {"mount_point": "/srv/data", "source": "/dev/sdb1", "filesystem": "xfs"},
    ]
    devices = [
        {"path": "/dev/mapper/root", "uuid": "root", "label": "", "partuuid": "", "children": []},
        {"path": "/dev/sdb1", "uuid": "", "label": "", "partuuid": "data-part", "children": []},
    ]

    result = StorageDetailsService.parse_fstab(content, filesystems, devices)

    root = next(item for item in result if item["mount_point"] == "/")
    data = next(item for item in result if item["mount_point"] == "/srv/data")
    archive = next(item for item in result if item["mount_point"] == "/mnt/archive")
    network = next(item for item in result if item["mount_point"] == "/mnt/net")

    assert root["active"] is True
    assert root["protected"] is True
    assert root["source_matches"] is True
    assert data["state"] == "active"
    assert data["resolved_source"] == "/dev/sdb1"
    assert data["source_matches"] is True
    assert archive["state"] == "disabled"
    assert archive["noauto"] is True
    assert network["network"] is True
    assert all(item["mount_point"] != "/mnt/../etc" for item in result)


def test_diskstats_parser_filters_physical_devices_and_calculates_bytes() -> None:
    content = """
   8       0 sda 100 2 300 40 500 6 700 80 1 90 120 10 0 30 5 7 3
   8       1 sda1 10 0 20 4 30 0 40 8 0 9 12
 259       0 nvme0n1 200 3 400 50 600 7 800 90 2 100 140 0 0 0 0
"""

    result = StorageDetailsService.parse_diskstats(content, {"sda", "nvme0n1"})

    assert [item["name"] for item in result] == ["sda", "nvme0n1"]
    assert result[0]["bytes_read"] == 300 * 512
    assert result[0]["bytes_written"] == 700 * 512
    assert result[0]["bytes_discarded"] == 30 * 512
    assert result[0]["flushes_completed"] == 7
    assert result[1]["io_in_progress"] == 2


def test_details_service_rejects_unknown_and_unapproved_probe_arguments() -> None:
    resolved: list[str] = []
    executed: list[list[str]] = []

    def resolver(name: str) -> str | None:
        resolved.append(name)
        return f"/usr/bin/{name}"

    def runner(argv: Sequence[str], timeout: float) -> CommandResult:
        del timeout
        executed.append(list(argv))
        return CommandResult(0, "", "")

    manager = StorageDetailsService(runner=runner, tool_resolver=resolver)

    assert manager._run("sh", ["-c", "id"]) is None
    assert manager._run("pvs", ["--reportformat", "json;id"]) is None
    assert manager._run("zpool", ["status", "-P", "tank;id"]) is None
    assert resolved == []
    assert executed == []


def test_storage_manager_exposes_logical_read_only_detail_endpoints() -> None:
    from app.modules.storage_manager.router import router

    routes = {getattr(route, "path", ""): set(getattr(route, "methods", set()) or set()) for route in router.routes}
    for path in {"/api/storage/details", "/api/storage/lvm", "/api/storage/mounts", "/api/storage/io", "/api/storage/pools"}:
        assert routes[path] == {"GET"}
