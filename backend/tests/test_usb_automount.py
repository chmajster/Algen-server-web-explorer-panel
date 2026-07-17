from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "scripts" / "usb_automount.py"
SPEC = importlib.util.spec_from_file_location("webnas_usb_automount", SCRIPT)
assert SPEC and SPEC.loader
usb_automount = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usb_automount)


def test_parses_udev_properties_without_losing_equals_signs():
    properties = usb_automount.parse_udev_properties(
        "ID_BUS=usb\nID_FS_USAGE=filesystem\nID_FS_LABEL=Backup=2026\ninvalid\n"
    )

    assert properties == {
        "ID_BUS": "usb",
        "ID_FS_USAGE": "filesystem",
        "ID_FS_LABEL": "Backup=2026",
    }


@pytest.mark.parametrize("device", ["/dev/sdb1/child", "/dev/../sdb1", "/tmp/sdb1", "/dev/", "sdb1"])
def test_rejects_non_direct_device_paths(device):
    with pytest.raises(usb_automount.AutomountError):
        usb_automount._device_name(device)


def test_creates_stable_bounded_mountpoint_names():
    name = usb_automount.mountpoint_name("Kopie zapasowe / 2026", "A1B2-C3D4-E5F6-7890", "sdb1")

    assert name == "Kopie-zapasowe-2026-A1B2C3D4E5F6"
    assert len(name) <= 64
    assert "/" not in name


def test_permissionless_usb_filesystems_are_visible_but_non_executable():
    assert usb_automount.mount_options("exfat") == [
        "nosuid",
        "nodev",
        "noexec",
        "uid=0",
        "gid=0",
        "fmask=0111",
        "dmask=0000",
    ]
    assert usb_automount.mount_options("ext4") == ["nosuid", "nodev", "noexec"]


def test_mount_lookup_requires_an_exact_mountpoint(monkeypatch):
    commands: list[list[str]] = []

    def run(command, *, check=True):
        commands.append(command)
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(usb_automount, "_run", run)

    assert usb_automount._source_for_mount(Path("/media/webnas-usb/backup-1234")) == ""
    assert "--mountpoint" in commands[0]
    assert "--target" not in commands[0]


@pytest.mark.parametrize("path", ["/media/webnas-usb", "/media/webnas-usb/disk/child", "/mnt/disk", "relative"])
def test_rejects_mountpoints_outside_direct_managed_children(path):
    with pytest.raises(usb_automount.AutomountError):
        usb_automount._safe_target(path)
