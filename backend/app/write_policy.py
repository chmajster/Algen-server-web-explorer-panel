from __future__ import annotations

from pathlib import Path

from .local_disks import assert_write_allowed as assert_local_disk_write_allowed
from .network_mounts import assert_write_allowed as assert_network_mount_write_allowed


def assert_write_allowed(path: str | Path) -> None:
    assert_network_mount_write_allowed(path)
    assert_local_disk_write_allowed(path)
