from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .service import CommandResult, _clean_text, _number, _safe_device_path, _safe_mount_path, _mountpoint_is_protected


logger = logging.getLogger(__name__)
SAFE_TOOL_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
ALLOWED_DETAIL_TOOLS = {"pvs", "vgs", "lvs", "swapon"}

Runner = Callable[[Sequence[str], float], CommandResult]


def _default_runner(argv: Sequence[str], timeout: float) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - executable is resolved from a fixed allowlist
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _bytes_value(value: Any) -> int:
    text = str(value or "").strip().lstrip("<>")
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def _decode_fstab_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\043", "#")
        .replace("\\134", "\\")
    )


class StorageDetailsService:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        tool_resolver: Callable[[str], str | None] | None = None,
        fstab_path: Path = Path("/etc/fstab"),
        diskstats_path: Path = Path("/proc/diskstats"),
    ) -> None:
        self._runner = runner or _default_runner
        self._tool_resolver = tool_resolver or self._resolve_tool
        self.fstab_path = fstab_path
        self.diskstats_path = diskstats_path

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

    def _run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:
        executable = self._tool_resolver(name) if name in ALLOWED_DETAIL_TOOLS else None
        if executable is None:
            return None
        try:
            return self._runner([executable, *args], timeout)
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("storage_detail_probe_failed tool=%s error=%s", name, type(error).__name__)
            return CommandResult(127, "", type(error).__name__)

    @staticmethod
    def _lvm_rows(payload: str, section: str) -> list[dict[str, Any]]:
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        reports = decoded.get("report") if isinstance(decoded, dict) else None
        if not isinstance(reports, list):
            return []
        rows: list[dict[str, Any]] = []
        for report in reports:
            if not isinstance(report, dict):
                continue
            values = report.get(section)
            if isinstance(values, list):
                rows.extend(item for item in values if isinstance(item, dict))
        return rows

    def lvm(self) -> dict[str, Any]:
        commands = {
            "pvs": ["--reportformat", "json", "--units", "b", "--nosuffix", "-o", "pv_name,vg_name,pv_size,pv_free,pv_attr"],
            "vgs": ["--reportformat", "json", "--units", "b", "--nosuffix", "-o", "vg_name,vg_size,vg_free,pv_count,lv_count,vg_attr"],
            "lvs": ["--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,vg_name,lv_path,lv_size,lv_attr,pool_lv,origin,data_percent,metadata_percent"],
        }
        raw: dict[str, list[dict[str, Any]]] = {}
        for tool, args in commands.items():
            result = self._run(tool, args, timeout=12.0)
            raw[tool] = self._lvm_rows(result.stdout, tool[:-1]) if result is not None and result.returncode == 0 else []

        physical_volumes = []
        for item in raw["pvs"]:
            path = _safe_device_path(item.get("pv_name"))
            if path is None:
                continue
            physical_volumes.append(
                {
                    "path": path,
                    "volume_group": _clean_text(item.get("vg_name"), 128),
                    "size": _bytes_value(item.get("pv_size")),
                    "free": _bytes_value(item.get("pv_free")),
                    "attributes": _clean_text(item.get("pv_attr"), 32),
                }
            )

        volume_groups = [
            {
                "name": _clean_text(item.get("vg_name"), 128),
                "size": _bytes_value(item.get("vg_size")),
                "free": _bytes_value(item.get("vg_free")),
                "pv_count": int(_number(item.get("pv_count")) or 0),
                "lv_count": int(_number(item.get("lv_count")) or 0),
                "attributes": _clean_text(item.get("vg_attr"), 32),
            }
            for item in raw["vgs"]
            if _clean_text(item.get("vg_name"), 128)
        ]

        logical_volumes = []
        for item in raw["lvs"]:
            path = _safe_device_path(item.get("lv_path"))
            logical_volumes.append(
                {
                    "name": _clean_text(item.get("lv_name"), 128),
                    "volume_group": _clean_text(item.get("vg_name"), 128),
                    "path": path or "",
                    "size": _bytes_value(item.get("lv_size")),
                    "attributes": _clean_text(item.get("lv_attr"), 32),
                    "pool": _clean_text(item.get("pool_lv"), 128),
                    "origin": _clean_text(item.get("origin"), 128),
                    "data_percent": _number(item.get("data_percent")),
                    "metadata_percent": _number(item.get("metadata_percent")),
                }
            )

        return {
            "available": any(self.tool_available(name) for name in {"pvs", "vgs", "lvs"}),
            "physical_volumes": physical_volumes,
            "volume_groups": volume_groups,
            "logical_volumes": logical_volumes,
        }

    def swap(self) -> list[dict[str, Any]]:
        result = self._run(
            "swapon",
            ["--show", "--bytes", "--noheadings", "--raw", "--output", "NAME,TYPE,SIZE,USED,PRIO"],
        )
        if result is None or result.returncode != 0:
            return []
        entries: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            fields = line.split(None, 4)
            if len(fields) != 5:
                continue
            name, kind, size, used, priority = fields
            entries.append(
                {
                    "name": _clean_text(name, 512),
                    "type": _clean_text(kind, 32),
                    "size": _bytes_value(size),
                    "used": _bytes_value(used),
                    "priority": int(_number(priority) or 0),
                }
            )
        return entries

    @staticmethod
    def parse_fstab(content: str, filesystems: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        live = {
            str(item.get("mount_point")): item
            for item in filesystems or []
            if isinstance(item, dict) and item.get("mount_point")
        }
        entries: list[dict[str, Any]] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                line = line.split("#", 1)[0].rstrip()
            fields = line.split()
            if len(fields) < 4:
                continue
            source = _decode_fstab_field(fields[0])
            target = _safe_mount_path(_decode_fstab_field(fields[1]))
            if target is None:
                continue
            fs_type = _clean_text(fields[2], 64)
            options = [_clean_text(item, 128) for item in fields[3].split(",") if _clean_text(item, 128)]
            current = live.get(target)
            noauto = "noauto" in options
            entries.append(
                {
                    "source": _clean_text(source, 512),
                    "mount_point": target,
                    "filesystem": fs_type,
                    "options": options,
                    "dump": int(_number(fields[4]) or 0) if len(fields) > 4 else 0,
                    "pass": int(_number(fields[5]) or 0) if len(fields) > 5 else 0,
                    "active": current is not None,
                    "current_source": _clean_text(current.get("source"), 512) if current else "",
                    "current_filesystem": _clean_text(current.get("filesystem"), 64) if current else "",
                    "noauto": noauto,
                    "automount": "x-systemd.automount" in options,
                    "protected": _mountpoint_is_protected(target),
                    "state": "active" if current else "disabled" if noauto else "inactive",
                }
            )
        return entries

    def fstab(self, filesystems: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        try:
            content = self.fstab_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.parse_fstab(content, filesystems)

    @staticmethod
    def parse_diskstats(content: str, names: set[str] | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line in content.splitlines():
            fields = line.split()
            if len(fields) < 14:
                continue
            name = fields[2]
            if names is not None and name not in names:
                continue
            if names is None and (name.startswith("loop") or name.startswith("ram")):
                continue
            try:
                reads = int(fields[3])
                sectors_read = int(fields[5])
                read_ms = int(fields[6])
                writes = int(fields[7])
                sectors_written = int(fields[9])
                write_ms = int(fields[10])
                in_flight = int(fields[11])
                io_ms = int(fields[12])
                weighted_io_ms = int(fields[13])
            except ValueError:
                continue
            entries.append(
                {
                    "name": name,
                    "reads_completed": reads,
                    "bytes_read": sectors_read * 512,
                    "read_ms": read_ms,
                    "writes_completed": writes,
                    "bytes_written": sectors_written * 512,
                    "write_ms": write_ms,
                    "io_in_progress": in_flight,
                    "io_ms": io_ms,
                    "weighted_io_ms": weighted_io_ms,
                }
            )
        return entries

    @staticmethod
    def _physical_kernel_names(devices: list[dict[str, Any]] | None) -> set[str] | None:
        if devices is None:
            return None
        names: set[str] = set()
        for item in devices:
            if not isinstance(item, dict) or item.get("type") != "disk":
                continue
            kernel_name = _clean_text(item.get("kernel_name"), 128)
            if kernel_name:
                names.add(kernel_name)
        return names

    def disk_io(self, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        try:
            content = self.diskstats_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.parse_diskstats(content, self._physical_kernel_names(devices))

    def snapshot(
        self,
        *,
        devices: list[dict[str, Any]] | None = None,
        filesystems: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        return {
            "read_only": True,
            "generated_at": time.time(),
            "tools": {name: self.tool_available(name) for name in sorted(ALLOWED_DETAIL_TOOLS)},
            "lvm": self.lvm(),
            "swap": self.swap(),
            "fstab": self.fstab(filesystems),
            "disk_io": self.disk_io(devices),
            "duration_ms": round((time.time() - started) * 1000, 1),
        }


_details_service: StorageDetailsService | None = None


def details_service() -> StorageDetailsService:
    global _details_service
    if _details_service is None:
        _details_service = StorageDetailsService()
    return _details_service
