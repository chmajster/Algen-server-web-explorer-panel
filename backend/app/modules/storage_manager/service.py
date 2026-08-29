from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ...local_disks import NETWORK_FILESYSTEMS, PSEUDO_FILESYSTEMS, parse_proc_mounts


logger = logging.getLogger(__name__)
SAFE_TOOL_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
ALLOWED_TOOLS = {"lsblk", "smartctl", "nvme", "zpool", "btrfs"}
LOW_FREE_PERCENT = 10.0
PROTECTED_MOUNTPOINTS = {"/", "/boot", "/boot/efi", "/etc/pve", "/var/lib/vz"}
_DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9._/+:-]+$")


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]


def _default_runner(argv: Sequence[str], timeout: float) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - executable is resolved from a fixed allowlist and arguments are not browser supplied
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return "".join(character for character in text if character.isprintable())[:limit]


def _safe_device_path(value: Any) -> str | None:
    path = _clean_text(value, 256)
    if not _DEVICE_RE.fullmatch(path):
        return None
    candidate = PurePosixPath(path)
    if not candidate.is_absolute() or len(candidate.parts) < 3 or candidate.parts[1] != "dev" or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _safe_mount_path(value: Any) -> str | None:
    text = str(value or "")
    if not text.startswith("/") or any(ord(character) < 32 for character in text):
        return None
    candidate = PurePosixPath(text)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _mountpoint_is_protected(value: str) -> bool:
    if value in PROTECTED_MOUNTPOINTS:
        return True
    return value.startswith("/boot/") or value.startswith("/etc/pve/") or value.startswith("/var/lib/vz/")


class StorageInventoryService:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        tool_resolver: Callable[[str], str | None] | None = None,
        mounts_path: Path = Path("/proc/self/mounts"),
        mdstat_path: Path = Path("/proc/mdstat"),
    ) -> None:
        self._runner = runner or _default_runner
        self._tool_resolver = tool_resolver or self._resolve_tool
        self.mounts_path = mounts_path
        self.mdstat_path = mdstat_path

    @staticmethod
    def _resolve_tool(name: str) -> str | None:
        if name not in ALLOWED_TOOLS:
            return None
        resolved = shutil.which(name, path=SAFE_TOOL_PATH)
        if not resolved:
            return None
        path = Path(resolved).resolve(strict=False)
        if path.name != name or str(path.parent) not in {"/usr/sbin", "/usr/bin", "/sbin", "/bin"}:
            return None
        return str(path)

    def tool_available(self, name: str) -> bool:
        return name in ALLOWED_TOOLS and self._tool_resolver(name) is not None

    def _run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:
        executable = self._tool_resolver(name) if name in ALLOWED_TOOLS else None
        if executable is None:
            return None
        try:
            return self._runner([executable, *args], timeout)
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("storage_probe_failed tool=%s error=%s", name, type(error).__name__)
            return CommandResult(127, "", type(error).__name__)

    @staticmethod
    def parse_lsblk(payload: str) -> list[dict[str, Any]]:
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        roots = decoded.get("blockdevices") if isinstance(decoded, dict) else None
        if not isinstance(roots, list):
            return []

        def normalize(raw: Any) -> dict[str, Any] | None:
            if not isinstance(raw, dict):
                return None
            path = _safe_device_path(raw.get("path"))
            if path is None:
                return None
            raw_mounts = raw.get("mountpoints")
            if not isinstance(raw_mounts, list):
                single = raw.get("mountpoint")
                raw_mounts = [single] if single else []
            mounts = [mount for item in raw_mounts if (mount := _safe_mount_path(item)) is not None]
            children = [child for item in raw.get("children") or [] if (child := normalize(item)) is not None]
            protected = any(_mountpoint_is_protected(point) for point in mounts) or any(bool(child["protected"]) for child in children)
            return {
                "name": _clean_text(raw.get("name"), 128),
                "kernel_name": _clean_text(raw.get("kname"), 128),
                "path": path,
                "type": _clean_text(raw.get("type"), 32),
                "size": _integer(raw.get("size")),
                "filesystem": _clean_text(raw.get("fstype"), 64),
                "filesystem_version": _clean_text(raw.get("fsver"), 64),
                "label": _clean_text(raw.get("label"), 128),
                "uuid": _clean_text(raw.get("uuid"), 128),
                "mountpoints": mounts,
                "read_only": bool(_integer(raw.get("ro"))),
                "removable": bool(_integer(raw.get("rm"))),
                "model": _clean_text(raw.get("model"), 160),
                "serial": _clean_text(raw.get("serial"), 160),
                "transport": _clean_text(raw.get("tran"), 32),
                "parent_kernel_name": _clean_text(raw.get("pkname"), 128),
                "partition_type": _clean_text(raw.get("parttype"), 128),
                "partition_label": _clean_text(raw.get("partlabel"), 128),
                "protected": protected,
                "children": children,
            }

        return [item for root in roots if (item := normalize(root)) is not None]

    def block_devices(self) -> list[dict[str, Any]]:
        result = self._run(
            "lsblk",
            [
                "--json",
                "--bytes",
                "--output",
                "NAME,KNAME,PATH,TYPE,SIZE,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS,RO,RM,MODEL,SERIAL,TRAN,PKNAME,PARTTYPE,PARTLABEL",
            ],
        )
        if result is None or result.returncode != 0:
            return []
        return self.parse_lsblk(result.stdout)

    @staticmethod
    def _physical_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(item: dict[str, Any]) -> None:
            if item.get("type") == "disk" and _safe_device_path(item.get("path")):
                result.append(item)
            for child in item.get("children") or []:
                if isinstance(child, dict):
                    visit(child)

        for device in devices:
            visit(device)
        return result

    def _smartctl_health(self, device: str) -> dict[str, Any] | None:
        result = self._run("smartctl", ["-a", "-j", device], timeout=12.0)
        if result is None or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"provider": "smartctl", "state": "unknown", "available": True}
        smart_status = payload.get("smart_status") if isinstance(payload, dict) else None
        passed = smart_status.get("passed") if isinstance(smart_status, dict) else None
        temperature_value = payload.get("temperature") if isinstance(payload, dict) else None
        temperature = temperature_value.get("current") if isinstance(temperature_value, dict) else None
        power_value = payload.get("power_on_time") if isinstance(payload, dict) else None
        hours = power_value.get("hours") if isinstance(power_value, dict) else None
        return {
            "provider": "smartctl",
            "available": True,
            "state": "ok" if passed is True else "failed" if passed is False else "unknown",
            "passed": passed if isinstance(passed, bool) else None,
            "temperature_c": _number(temperature),
            "power_on_hours": _integer(hours) if hours is not None else None,
            "tool_exit_code": result.returncode,
        }

    def _nvme_health(self, device: str) -> dict[str, Any] | None:
        result = self._run("nvme", ["smart-log", "-o", "json", device], timeout=12.0)
        if result is None or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"provider": "nvme", "state": "unknown", "available": True}
        if not isinstance(payload, dict):
            return {"provider": "nvme", "state": "unknown", "available": True}
        critical = _integer(payload.get("critical_warning"))
        return {
            "provider": "nvme",
            "available": True,
            "state": "failed" if critical else "ok",
            "critical_warning": critical,
            "temperature_c": _number(payload.get("temperature")),
            "percentage_used": _number(payload.get("percentage_used")),
            "available_spare_percent": _number(payload.get("avail_spare")),
            "media_errors": _integer(payload.get("media_errors")),
            "tool_exit_code": result.returncode,
        }

    def device_health(self, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        roots = devices if devices is not None else self.block_devices()
        results: list[dict[str, Any]] = []
        for item in self._physical_devices(roots):
            device = _safe_device_path(item.get("path"))
            if device is None:
                continue
            is_nvme = device.startswith("/dev/nvme") or str(item.get("transport")) == "nvme"
            health = self._nvme_health(device) if is_nvme else None
            if health is None:
                health = self._smartctl_health(device)
            if health is None:
                health = {"provider": "none", "available": False, "state": "unavailable"}
            results.append(
                {
                    "device": device,
                    "model": item.get("model", ""),
                    "serial": item.get("serial", ""),
                    "protected": bool(item.get("protected")),
                    **health,
                }
            )
        return results

    def filesystems(self) -> list[dict[str, Any]]:
        try:
            content = self.mounts_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for mount in parse_proc_mounts(content):
            fs_type = mount["fs_type"]
            point = _safe_mount_path(mount["mount_point"])
            if point is None or point in seen or fs_type in PSEUDO_FILESYSTEMS or fs_type in NETWORK_FILESYSTEMS:
                continue
            seen.add(point)
            try:
                stats = os.statvfs(point)
            except OSError:
                continue
            block_size = stats.f_frsize or stats.f_bsize
            total = block_size * stats.f_blocks
            free = block_size * stats.f_bavail
            used = max(total - free, 0)
            free_percent = (free / total * 100.0) if total else 0.0
            results.append(
                {
                    "source": _clean_text(mount["device"], 256),
                    "mount_point": point,
                    "filesystem": fs_type,
                    "options": mount["options"][:64],
                    "read_only": "ro" in mount["options"],
                    "total": total,
                    "used": used,
                    "free": free,
                    "free_percent": round(free_percent, 2),
                    "protected": _mountpoint_is_protected(point),
                }
            )
        return sorted(results, key=lambda item: str(item["mount_point"]))

    @staticmethod
    def parse_mdstat(content: str) -> list[dict[str, Any]]:
        arrays: list[dict[str, Any]] = []
        lines = content.splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(md\S+)\s*:\s*(\S+)\s+(raid\S+)\s+(.+)$", line.strip())
            if not match:
                continue
            name, activity, level, members = match.groups()
            detail = lines[index + 1].strip() if index + 1 < len(lines) else ""
            bitmap = re.search(r"\[([U_]+)\]", detail)
            member_state = bitmap.group(1) if bitmap else ""
            degraded = bool(member_state and "_" in member_state)
            arrays.append(
                {
                    "name": name,
                    "activity": activity,
                    "level": level,
                    "members": members.split(),
                    "member_state": member_state,
                    "state": "degraded" if degraded else "ok",
                }
            )
        return arrays

    def md_arrays(self) -> list[dict[str, Any]]:
        try:
            return self.parse_mdstat(self.mdstat_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return []

    def zfs_pools(self) -> list[dict[str, Any]]:
        result = self._run("zpool", ["list", "-H", "-p", "-o", "name,health,size,alloc,free"])
        if result is None or result.returncode != 0:
            return []
        pools: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) != 5:
                fields = line.split()
            if len(fields) != 5:
                continue
            name, health, size, allocated, free = fields
            pools.append(
                {
                    "name": _clean_text(name, 128),
                    "health": _clean_text(health, 32).upper(),
                    "size": _integer(size),
                    "allocated": _integer(allocated),
                    "free": _integer(free),
                    "state": "ok" if health.upper() == "ONLINE" else "degraded",
                }
            )
        return pools

    def btrfs_filesystems(self, filesystems: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        mounts = filesystems if filesystems is not None else self.filesystems()
        results: list[dict[str, Any]] = []
        for item in mounts:
            if item.get("filesystem") != "btrfs":
                continue
            point = _safe_mount_path(item.get("mount_point"))
            if point is None:
                continue
            probe = self._run("btrfs", ["device", "stats", "-c", point], timeout=10.0)
            if probe is None:
                results.append({"mount_point": point, "state": "unavailable", "available": False})
            else:
                results.append(
                    {
                        "mount_point": point,
                        "state": "ok" if probe.returncode == 0 else "degraded",
                        "available": True,
                        "tool_exit_code": probe.returncode,
                    }
                )
        return results

    def snapshot(self) -> dict[str, Any]:
        started = time.time()
        devices = self.block_devices()
        filesystems = self.filesystems()
        smart = self.device_health(devices)
        md = self.md_arrays()
        zfs = self.zfs_pools()
        btrfs = self.btrfs_filesystems(filesystems)
        issues: list[dict[str, Any]] = []

        for item in smart:
            if item.get("state") == "failed":
                issues.append({"severity": "critical", "code": "device-health-failed", "target": item["device"], "message": "Device health check failed"})
        for item in md:
            if item.get("state") != "ok":
                issues.append({"severity": "critical", "code": "md-array-degraded", "target": item["name"], "message": "Software RAID array is degraded"})
        for item in zfs:
            if item.get("state") != "ok":
                issues.append({"severity": "critical", "code": "zfs-pool-degraded", "target": item["name"], "message": f"ZFS pool health is {item['health']}"})
        for item in btrfs:
            if item.get("state") == "degraded":
                issues.append({"severity": "error", "code": "btrfs-device-errors", "target": item["mount_point"], "message": "Btrfs device statistics report errors"})
        for item in filesystems:
            total = _integer(item.get("total"))
            free_percent = _number(item.get("free_percent"))
            if total >= 1024**3 and free_percent is not None and free_percent < LOW_FREE_PERCENT:
                issues.append({"severity": "warning", "code": "filesystem-low-space", "target": item["mount_point"], "message": f"Filesystem free space is {free_percent:.1f}%"})

        severity_rank = {"warning": 1, "error": 2, "critical": 3}
        worst = max((severity_rank.get(str(item.get("severity")), 0) for item in issues), default=0)
        state = "critical" if worst >= 3 else "degraded" if worst >= 1 else "ok"
        return {
            "state": state,
            "read_only": True,
            "generated_at": time.time(),
            "duration_ms": round((time.time() - started) * 1000, 1),
            "tools": {name: self.tool_available(name) for name in sorted(ALLOWED_TOOLS)},
            "devices": devices,
            "device_health": smart,
            "filesystems": filesystems,
            "md_arrays": md,
            "zfs_pools": zfs,
            "btrfs_filesystems": btrfs,
            "issues": issues,
        }


_service: StorageInventoryService | None = None
_service_lock = threading.Lock()


def service() -> StorageInventoryService:
    global _service
    with _service_lock:
        if _service is None:
            _service = StorageInventoryService()
        return _service
