from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import local_disks, network_mounts, path_policy, proxmox_guard
from app.config import AppConfig


def mount_line(device: str, point: str, fs_type: str = "ext4", options: str = "rw,relatime") -> str:
    return f"{device} {point} {fs_type} {options} 0 0"


def patch_discovery(monkeypatch, content: str, *, inaccessible: set[str] | None = None) -> None:
    inaccessible = inaccessible or set()
    monkeypatch.setattr(local_disks, "_read_mounts", lambda: local_disks.parse_proc_mounts(content))
    monkeypatch.setattr(local_disks, "_secure_mount_path", lambda username, point: Path(point))
    monkeypatch.setattr(local_disks, "user_can_access_mount", lambda username, path: str(path) not in inaccessible)
    monkeypatch.setattr(local_disks.shutil, "disk_usage", lambda path: SimpleNamespace(total=1000, used=400, free=600))


def test_detects_local_block_devices(monkeypatch):
    patch_discovery(
        monkeypatch,
        "\n".join(
            [
                mount_line("/dev/sdb1", "/mnt/storage"),
                mount_line("/dev/nvme0n1p2", "/media/fast", "xfs"),
            ]
        ),
    )

    disks = local_disks.local_disk_mounts("alice")

    assert {(disk["device"], disk["name"], disk["fs_type"]) for disk in disks} == {
        ("/dev/sdb1", "storage", "ext4"),
        ("/dev/nvme0n1p2", "fast", "xfs"),
    }


@pytest.mark.parametrize("fs_type", ["tmpfs", "overlay", "proc"])
def test_skips_pseudo_filesystems(monkeypatch, fs_type):
    patch_discovery(monkeypatch, mount_line("none", "/mnt/technical", fs_type))

    assert local_disks.local_disk_mounts("alice") == []


@pytest.mark.parametrize("fs_type", ["nfs", "cifs", "smb3", "fuse.sshfs"])
def test_skips_network_filesystems(monkeypatch, fs_type):
    patch_discovery(monkeypatch, mount_line("server:/share", "/mnt/remote", fs_type))

    assert local_disks.local_disk_mounts("alice") == []


@pytest.mark.parametrize("point", ["/boot", "/boot/efi", "/var/lib/vz", "/mnt/pve", "/mnt/pve/storage", "/mnt/webnas/mnt/media"])
def test_skips_system_proxmox_and_application_mounts(monkeypatch, point):
    patch_discovery(monkeypatch, mount_line("/dev/sdb1", point))

    assert local_disks.local_disk_mounts("alice") == []


def test_recognizes_read_only_and_read_write_options(monkeypatch):
    patch_discovery(
        monkeypatch,
        "\n".join(
            [
                mount_line("/dev/sdb1", "/mnt/archive", options="ro,nosuid"),
                mount_line("/dev/sdc1", "/mnt/work", options="rw,nosuid"),
            ]
        ),
    )

    disks = {disk["name"]: disk for disk in local_disks.local_disk_mounts("alice")}

    assert disks["archive"]["read_only"] is True
    assert disks["work"]["read_only"] is False


def test_decodes_proc_mount_escapes():
    parsed = local_disks.parse_proc_mounts(r"/dev/disk\040one /mnt/My\040Disk ext4 rw,note=tab\011line\012slash\134 0 0")

    assert parsed[0]["device"] == "/dev/disk one"
    assert parsed[0]["mount_point"] == "/mnt/My Disk"
    assert parsed[0]["options"][1] == "note=tab\tline\nslash\\"


def test_removes_duplicate_mountpoints(monkeypatch):
    patch_discovery(
        monkeypatch,
        "\n".join(
            [
                mount_line("/dev/sdb1", "/mnt/storage"),
                mount_line("/dev/disk/by-label/storage", "/mnt/storage"),
            ]
        ),
    )

    assert len(local_disks.local_disk_mounts("alice")) == 1


def test_skips_mount_without_user_access(monkeypatch):
    patch_discovery(monkeypatch, mount_line("/dev/sdb1", "/mnt/private"), inaccessible={str(Path("/mnt/private"))})

    assert local_disks.local_disk_mounts("alice") == []


def test_checks_mount_permissions_for_the_requested_user(monkeypatch, tmp_path):
    disk = tmp_path / "private"
    disk.mkdir(mode=0o700)
    details = disk.stat()
    monkeypatch.setattr(
        local_disks.pwd,
        "getpwnam",
        lambda username: SimpleNamespace(pw_uid=details.st_uid + 1000, pw_gid=details.st_gid + 1000),
    )
    monkeypatch.setattr(local_disks.os, "getgrouplist", lambda username, gid: [gid], raising=False)

    assert local_disks.user_can_access_mount("alice", disk) is False

    monkeypatch.setattr(
        local_disks.pwd,
        "getpwnam",
        lambda username: SimpleNamespace(pw_uid=details.st_uid, pw_gid=details.st_gid),
    )
    assert local_disks.user_can_access_mount("alice", disk) is True


def test_allowed_roots_include_visible_local_disk(monkeypatch, tmp_path):
    home = tmp_path / "home"
    disk = tmp_path / "storage"
    home.mkdir()
    disk.mkdir()
    monkeypatch.setattr(path_policy, "user_home", lambda username: str(home))
    monkeypatch.setattr(network_mounts, "visible_mount_roots", lambda username: [])
    monkeypatch.setattr(local_disks, "visible_local_disk_roots", lambda username: [disk])

    assert disk in path_policy.allowed_roots("alice")


def test_proxmox_safe_mode_hides_non_home_local_disk(monkeypatch, tmp_path):
    home = tmp_path / "home" / "alice"
    disk = tmp_path / "mnt" / "storage"
    home.mkdir(parents=True)
    disk.mkdir(parents=True)
    cfg = AppConfig.model_validate(
        {
            "proxmox": {"safe_mode": True, "detect": False, "allow_only_home_roots_on_proxmox": True},
            "paths": {"allowed_roots": [str(home)]},
        }
    )
    monkeypatch.setattr(local_disks, "get_config", lambda: cfg)
    monkeypatch.setattr(proxmox_guard, "user_home", lambda username: str(home))

    assert local_disks._secure_mount_path("alice", str(disk)) is None


def test_read_only_local_disk_blocks_write(monkeypatch):
    monkeypatch.setattr(local_disks, "_read_mounts", lambda: local_disks.parse_proc_mounts(mount_line("/dev/sdb1", "/mnt/archive", options="ro")))

    with pytest.raises(HTTPException) as error:
        local_disks.assert_write_allowed("/mnt/archive/file.txt")

    assert error.value.status_code == 403


def test_endpoint_uses_authenticated_username(monkeypatch):
    monkeypatch.setattr(local_disks, "local_disk_mounts", lambda username: [{"username": username}])

    assert local_disks.list_local_disks(SimpleNamespace(username="alice")) == [{"username": "alice"}]
