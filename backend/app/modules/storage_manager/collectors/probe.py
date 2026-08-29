from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from ..service import CommandResult, _safe_mount_path


logger = logging.getLogger(__name__)
SAFE_TOOL_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
ALLOWED_DETAIL_TOOLS = {"pvs", "vgs", "lvs", "swapon", "zpool", "zfs", "btrfs"}

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
_POOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


Runner = Callable[[Sequence[str], float], CommandResult]


def _default_runner(argv: Sequence[str], timeout: float) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - executable and argv shapes are strictly allowlisted below.
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _safe_probe_args(name: str, args: Sequence[str]) -> bool:
    values = tuple(args)
    if name == "pvs":
        return values == PVS_ARGS
    if name == "vgs":
        return values == VGS_ARGS
    if name == "lvs":
        return values == LVS_ARGS
    if name == "swapon":
        return values == SWAPON_ARGS
    if name == "zpool":
        if values == ZPOOL_LIST_ARGS:
            return True
        return len(values) == 3 and values[:2] == ("status", "-P") and bool(_POOL_RE.fullmatch(values[2]))
    if name == "zfs":
        return values == ZFS_LIST_ARGS
    if name == "btrfs":
        if len(values) == 4 and values[:3] == ("device", "stats", "-c"):
            return _safe_mount_path(values[3]) is not None
        if len(values) == 4 and values[:3] == ("filesystem", "show", "--raw"):
            return _safe_mount_path(values[3]) is not None
        if len(values) == 4 and values[:3] == ("filesystem", "usage", "-b"):
            return _safe_mount_path(values[3]) is not None
        if len(values) == 4 and values[:3] == ("scrub", "status", "-R"):
            return _safe_mount_path(values[3]) is not None
    return False


class StorageReadOnlyProbe:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        tool_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self._tool_resolver = tool_resolver or self._resolve_tool

    @staticmethod
    def _resolve_tool(name: str) -> str | None:
        if name not in ALLOWED_DETAIL_TOOLS:
            return None
        resolved = shutil.which(name, path=SAFE_TOOL_PATH)
        if not resolved:
            return None
        path = Path(resolved).resolve(strict=False)
        if path.name != name or str(path.parent) not in {"/usr/sbin", "/usr/bin", "/sbin", "/bin"}:
            return None
        return str(path)

    def tool_available(self, name: str) -> bool:
        return name in ALLOWED_DETAIL_TOOLS and self._tool_resolver(name) is not None

    def run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:
        if name not in ALLOWED_DETAIL_TOOLS or not _safe_probe_args(name, args):
            return None
        executable = self._tool_resolver(name)
        if executable is None:
            return None
        try:
            return self._runner([executable, *args], timeout)
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("storage_detail_probe_failed tool=%s error=%s", name, type(error).__name__)
            return CommandResult(127, "", type(error).__name__)
