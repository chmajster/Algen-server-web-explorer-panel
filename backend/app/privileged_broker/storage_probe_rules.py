from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePosixPath


ALLOWED_STORAGE_PROBE_TOOLS = frozenset(
    {"smartctl", "nvme", "pvs", "vgs", "lvs", "swapon", "zpool", "zfs", "btrfs"}
)

PVS_ARGS = (
    "--reportformat",
    "json",
    "--units",
    "b",
    "--nosuffix",
    "-o",
    "pv_name,vg_name,pv_size,pv_free,pv_attr",
)
VGS_ARGS = (
    "--reportformat",
    "json",
    "--units",
    "b",
    "--nosuffix",
    "-o",
    "vg_name,vg_size,vg_free,pv_count,lv_count,vg_attr",
)
LVS_ARGS = (
    "--reportformat",
    "json",
    "--units",
    "b",
    "--nosuffix",
    "-o",
    "lv_name,vg_name,lv_path,lv_size,lv_attr,pool_lv,origin,data_percent,metadata_percent",
)
SWAPON_ARGS = ("--show", "--bytes", "--noheadings", "--raw", "--output", "NAME,TYPE,SIZE,USED,PRIO")
ZPOOL_LIST_ARGS = ("list", "-H", "-p", "-o", "name,health,size,alloc,free")
ZFS_LIST_ARGS = ("list", "-H", "-p", "-o", "name,type,used,avail,refer,mountpoint")

_DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9._/+:-]+$")
_POOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def safe_device_path(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 256 or not _DEVICE_RE.fullmatch(value):
        return False
    candidate = PurePosixPath(value)
    return candidate.is_absolute() and len(candidate.parts) >= 3 and candidate.parts[1] == "dev" and ".." not in candidate.parts


def safe_mount_path(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096 or "\x00" in value:
        return False
    if any(ord(character) < 32 for character in value):
        return False
    candidate = PurePosixPath(value)
    return candidate.is_absolute() and ".." not in candidate.parts


def storage_probe_args_allowed(tool: str, args: Sequence[str]) -> bool:
    values = tuple(args)
    if tool == "smartctl":
        return len(values) == 3 and values[:2] == ("-a", "-j") and safe_device_path(values[2])
    if tool == "nvme":
        return len(values) == 4 and values[:3] == ("smart-log", "-o", "json") and safe_device_path(values[3])
    if tool == "pvs":
        return values == PVS_ARGS
    if tool == "vgs":
        return values == VGS_ARGS
    if tool == "lvs":
        return values == LVS_ARGS
    if tool == "swapon":
        return values == SWAPON_ARGS
    if tool == "zpool":
        if values == ZPOOL_LIST_ARGS:
            return True
        return len(values) == 3 and values[:2] == ("status", "-P") and bool(_POOL_RE.fullmatch(values[2]))
    if tool == "zfs":
        return values == ZFS_LIST_ARGS
    if tool == "btrfs":
        if len(values) != 4 or not safe_mount_path(values[3]):
            return False
        return values[:3] in {
            ("device", "stats", "-c"),
            ("filesystem", "show", "--raw"),
            ("filesystem", "usage", "-b"),
            ("scrub", "status", "-R"),
        }
    return False
