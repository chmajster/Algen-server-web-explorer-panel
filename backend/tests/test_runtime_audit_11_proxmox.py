from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.proxmox_manager import ProxmoxManagerService


class FakeClient:
    def __init__(self, resources: Any) -> None:
        self.resources = resources

    def get(self, path: str):
        assert path == "cluster/resources?type=vm"
        return self.resources


def test_proxmox_resources_skip_invalid_identity_rows_and_normalize_metrics(tmp_path: Path) -> None:
    service = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")
    client = FakeClient(
        [
            {"vmid": "bad", "node": "pve1", "type": "qemu", "name": "bad-id"},
            {"vmid": 101, "node": "", "type": "qemu", "name": "missing-node"},
            {
                "vmid": "102",
                "node": " pve2 ",
                "type": "qemu",
                "name": "valid",
                "template": "0",
                "uptime": "unknown",
                "cpu": "nan",
                "maxcpu": {"bad": True},
                "mem": -1,
                "maxmem": "4096",
                "disk": True,
                "maxdisk": "8192",
                "status": "running",
                "tags": "prod;web",
            },
        ]
    )
    connection = {"sync_lxc": True, "sync_templates": True}

    resources = service._resources(connection, client)

    assert resources == [
        {
            "vmid": 102,
            "name": "valid",
            "node": "pve2",
            "type": "qemu",
            "status": "running",
            "template": False,
            "uptime": 0,
            "cpu": 0.0,
            "maxcpu": 0,
            "mem": 0,
            "maxmem": 4096,
            "disk": 0,
            "maxdisk": 8192,
            "tags": ["prod", "web"],
        }
    ]


def test_proxmox_resources_reject_wrong_top_level_shape(tmp_path: Path) -> None:
    service = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")
    connection = {"sync_lxc": True, "sync_templates": True}
    assert service._resources(connection, FakeClient({"not": "a list"})) == []


def test_proxmox_template_flags_are_not_truthy_string_coercions(tmp_path: Path) -> None:
    service = ProxmoxManagerService(tmp_path / "proxmox.sqlite3")
    client = FakeClient(
        [
            {"vmid": 200, "node": "pve1", "type": "qemu", "template": "0"},
            {"vmid": 201, "node": "pve1", "type": "qemu", "template": "1"},
        ]
    )
    connection = {"sync_lxc": True, "sync_templates": False}

    resources = service._resources(connection, client)

    assert [item["vmid"] for item in resources] == [200]
