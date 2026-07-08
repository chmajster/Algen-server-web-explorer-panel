from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from threading import Lock

from .path_policy import allowed_roots

_cpu_lock = Lock()
_last_cpu: tuple[int, int] | None = None

PSEUDO_FILESYSTEMS = {
    "autofs",
    "binfmt_misc",
    "bpf",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devpts",
    "devtmpfs",
    "efivarfs",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "overlay",
    "proc",
    "pstore",
    "securityfs",
    "sysfs",
    "tmpfs",
    "tracefs",
}


def _read_cpu_totals() -> tuple[int, int]:
    with Path("/proc/stat").open("r", encoding="utf-8") as handle:
        first = handle.readline().split()
    values = [int(value) for value in first[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_usage_percent() -> float | None:
    if not Path("/proc/stat").exists():
        return None
    global _last_cpu
    with _cpu_lock:
        current = _read_cpu_totals()
        if _last_cpu is None:
            _last_cpu = current
            time.sleep(0.05)
            current = _read_cpu_totals()
        total_delta = current[0] - _last_cpu[0]
        idle_delta = current[1] - _last_cpu[1]
        _last_cpu = current
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), 1)


def _meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    path = Path("/proc/meminfo")
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        result[key] = int(raw.strip().split()[0]) * 1024
    return result


def memory_stats() -> dict:
    info = _meminfo()
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = max(0, total - available)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    return {
        "ram": _usage_payload(total, used),
        "swap": _usage_payload(swap_total, swap_used),
    }


def _usage_payload(total: int, used: int) -> dict:
    percent = round((used / total) * 100, 1) if total else 0.0
    return {"total": total, "used": used, "free": max(0, total - used), "percent": percent}


def disk_usage(path: Path) -> dict | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    used = usage.total - usage.free
    return {"path": str(path), **_usage_payload(usage.total, used)}


def allowed_root_usage(username: str) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for root in allowed_roots(username):
        usage = disk_usage(root)
        if not usage or usage["path"] in seen:
            continue
        seen.add(usage["path"])
        result.append(usage)
    return result


def mountpoint_usage() -> list[dict]:
    mounts = Path("/proc/mounts")
    if not mounts.exists():
        return []
    result: list[dict] = []
    seen: set[str] = set()
    for line in mounts.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fs_type = parts[:3]
        if fs_type in PSEUDO_FILESYSTEMS or mount in seen:
            continue
        usage = disk_usage(Path(mount))
        if not usage:
            continue
        seen.add(mount)
        result.append({"device": device, "mountpoint": mount, "fs_type": fs_type, **usage})
    return sorted(result, key=lambda item: item["mountpoint"])


def uptime_seconds() -> float | None:
    path = Path("/proc/uptime")
    if not path.exists():
        return None
    return float(path.read_text(encoding="utf-8").split()[0])


def load_average() -> list[float] | None:
    if not hasattr(os, "getloadavg"):
        return None
    return [round(value, 2) for value in os.getloadavg()]


def webnas_service_status() -> str:
    if not shutil.which("systemctl"):
        return "unknown"
    result = subprocess.run(["systemctl", "is-active", "webnas.service"], capture_output=True, text=True, timeout=2, check=False)
    return result.stdout.strip() or "unknown"


def cpu_temperature() -> float | None:
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if value:
            return round(value / 1000, 1)
    return None


def collect_dashboard(username: str, *, is_admin: bool) -> dict:
    memory = memory_stats()
    allowed = allowed_root_usage(username)
    warnings = []
    for item in allowed:
        if item["percent"] >= 90:
            warnings.append(f"Low free space on {item['path']}")
    payload = {
        "scope": "admin" if is_admin else "user",
        "timestamp": time.time(),
        "cpu_percent": cpu_usage_percent(),
        "ram": memory["ram"],
        "swap": memory["swap"],
        "allowed_roots": allowed,
        "uptime_seconds": uptime_seconds(),
        "load_average": load_average(),
        "temperature_c": cpu_temperature(),
        "warnings": warnings,
    }
    if is_admin:
        payload["mountpoints"] = mountpoint_usage()
        payload["webnas_service"] = webnas_service_status()
    else:
        payload["mountpoints"] = []
        payload["webnas_service"] = None
    return payload
