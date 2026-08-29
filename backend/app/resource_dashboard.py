from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from threading import Lock

from .audit import logger
from .path_policy import allowed_roots

PSEUDO_FILESYSTEMS = {
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs", "devpts",
    "devtmpfs", "efivarfs", "fusectl", "hugetlbfs", "mqueue", "overlay", "proc", "pstore",
    "securityfs", "sysfs", "tmpfs", "tracefs",
}
WEBNAS_SERVICE_UNITS = (
    "webnas-backend-blue.service",
    "webnas-backend-green.service",
    "webnas.service",
)
DEFAULT_PROCESS_LIMIT = 12
_sample_lock = Lock()
_last_sample: dict | None = None


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("resource_metric_unavailable path=%s error=%s", path, type(exc).__name__)
        return ""


def parse_proc_stat(content: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for line in content.splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith("cpu") or (fields[0] != "cpu" and not fields[0][3:].isdigit()):
            continue
        try:
            values = [int(value) for value in fields[1:]]
        except ValueError:
            continue
        if len(values) < 4:
            continue
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        result[fields[0]] = (sum(values), idle)
    return result


def cpu_percentages(current: dict[str, tuple[int, int]], previous: dict[str, tuple[int, int]] | None) -> dict[str, float | None]:
    if previous is None:
        return {name: None for name in current}
    result: dict[str, float | None] = {}
    for name, (total, idle) in current.items():
        old = previous.get(name)
        if not old:
            result[name] = None
            continue
        total_delta = total - old[0]
        idle_delta = idle - old[1]
        if total_delta <= 0 or idle_delta < 0:
            result[name] = 0.0
        else:
            result[name] = round(max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), 1)
    return result


def parse_net_dev(content: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        name, raw = line.split(":", 1)
        fields = raw.split()
        try:
            if len(fields) >= 16:
                result[name.strip()] = (int(fields[0]), int(fields[8]))
        except ValueError:
            continue
    return result


def parse_diskstats(content: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for line in content.splitlines():
        fields = line.split()
        try:
            if len(fields) >= 10:
                result[fields[2]] = (int(fields[5]) * 512, int(fields[9]) * 512)
        except ValueError:
            continue
    return result


def counter_rates(current: dict[str, tuple[int, int]], previous: dict[str, tuple[int, int]] | None, elapsed: float) -> dict[str, tuple[float | None, float | None]]:
    rates: dict[str, tuple[float | None, float | None]] = {}
    for name, values in current.items():
        old = previous.get(name) if previous else None
        if not old or elapsed <= 0:
            rates[name] = (None, None)
            continue
        first = round((values[0] - old[0]) / elapsed, 1) if values[0] >= old[0] else 0.0
        second = round((values[1] - old[1]) / elapsed, 1) if values[1] >= old[1] else 0.0
        rates[name] = (first, second)
    return rates


def realtime_sample(now: float | None = None) -> dict:
    global _last_sample
    with _sample_lock:
        timestamp = time.monotonic() if now is None else now
        cpu = parse_proc_stat(_read("/proc/stat"))
        network = parse_net_dev(_read("/proc/net/dev"))
        disks = parse_diskstats(_read("/proc/diskstats"))
        previous = _last_sample
        elapsed = timestamp - previous["time"] if previous else 0.0
        result = {
            "cpu": cpu_percentages(cpu, previous["cpu"] if previous else None),
            "network_rates": counter_rates(network, previous["network"] if previous else None, elapsed),
            "disk_rates": counter_rates(disks, previous["disks"] if previous else None, elapsed),
            "network": network,
            "disks": disks,
        }
        _last_sample = {"time": timestamp, "cpu": cpu, "network": network, "disks": disks}
    return result


def cpu_usage_percent() -> float | None:
    return realtime_sample()["cpu"].get("cpu")


def _meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        try:
            result[key] = int(raw.strip().split()[0]) * 1024
        except (ValueError, IndexError):
            continue
    return result


def _usage_payload(total: int, used: int) -> dict:
    return {"total": total, "used": used, "free": max(0, total - used), "percent": round((used / total) * 100, 1) if total else 0.0}


def memory_stats() -> dict:
    info = _meminfo()
    total, available = info.get("MemTotal", 0), info.get("MemAvailable", 0)
    swap_total, swap_free = info.get("SwapTotal", 0), info.get("SwapFree", 0)
    return {"ram": _usage_payload(total, max(0, total - available)), "swap": _usage_payload(swap_total, max(0, swap_total - swap_free))}


def disk_usage(path: Path) -> dict | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"path": str(path), **_usage_payload(usage.total, usage.total - usage.free)}


def _decode_mount(value: str) -> str:
    for escaped, decoded in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(escaped, decoded)
    return value


def mount_records() -> list[dict]:
    records: list[dict] = []
    for line in _read("/proc/self/mounts").splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        device, mountpoint, fs_type = (_decode_mount(value) for value in fields[:3])
        if fs_type in PSEUDO_FILESYSTEMS:
            continue
        records.append({"device": device, "mountpoint": mountpoint, "fs_type": fs_type})
    return records


def _filesystem_id(device_id: int) -> str:
    try:
        return f"fs-{os.major(device_id)}-{os.minor(device_id)}"
    except (AttributeError, OSError, ValueError):
        return f"fs-{device_id}"


def _mount_for(path: Path, device_id: int, records: list[dict]) -> dict | None:
    matches: list[dict] = []
    for record in records:
        mount = Path(record["mountpoint"])
        try:
            if (path == mount or path.is_relative_to(mount)) and mount.stat().st_dev == device_id:
                matches.append(record)
        except OSError:
            continue
    return max(matches, key=lambda item: len(item["mountpoint"]), default=None)


def allowed_root_usage(username: str) -> list[dict]:
    records = mount_records()
    grouped: dict[int, dict] = {}
    for root in allowed_roots(username):
        try:
            real = root.resolve(strict=True)
            device_id = real.stat().st_dev
        except OSError:
            continue
        usage = disk_usage(real)
        if not usage:
            continue
        if device_id not in grouped:
            mount = _mount_for(real, device_id, records) or {}
            grouped[device_id] = {
                **usage, "filesystem_id": _filesystem_id(device_id), "paths": [],
                "device": mount.get("device"), "mountpoint": mount.get("mountpoint"), "fs_type": mount.get("fs_type"),
            }
        grouped[device_id]["paths"].append(str(real))
    for item in grouped.values():
        item["paths"] = sorted(set(item["paths"]))
        item["path"] = item["paths"][0]
    return sorted(grouped.values(), key=lambda item: item["path"])


def mountpoint_usage() -> list[dict]:
    result: list[dict] = []
    for record in mount_records():
        path = Path(record["mountpoint"])
        usage = disk_usage(path)
        try:
            device_id = path.stat().st_dev
        except OSError:
            continue
        if usage:
            result.append({**record, **usage, "filesystem_id": _filesystem_id(device_id)})
    return sorted(result, key=lambda item: item["mountpoint"])


def uptime_seconds() -> float | None:
    try:
        return float(_read("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        return None


def load_average() -> list[float] | None:
    try:
        return [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        return None


def webnas_service_status() -> str:
    if not shutil.which("systemctl"):
        return "unknown"
    statuses: list[str] = []
    try:
        for unit in WEBNAS_SERVICE_UNITS:
            result = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                shell=False,
            )
            status = result.stdout.strip() or "unknown"
            statuses.append(status)
            if status == "active":
                return "active"
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("resource_service_status_unavailable error=%s", type(exc).__name__)
        return "unknown"
    for status in statuses:
        if status not in {"inactive", "unknown"}:
            return status
    return "inactive" if "inactive" in statuses else "unknown"


def cpu_temperature() -> float | None:
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = int(path.read_text(encoding="utf-8").strip())
            if value:
                return round(value / 1000, 1)
        except (OSError, ValueError):
            continue
    return None


def cpu_frequency_mhz() -> float | None:
    values = []
    for line in _read("/proc/cpuinfo").splitlines():
        if line.lower().startswith("cpu mhz") and ":" in line:
            try:
                values.append(float(line.split(":", 1)[1]))
            except ValueError:
                continue
    if not values:
        for path in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"):
            try:
                values.append(float(path.read_text(encoding="utf-8").strip()) / 1000)
            except (OSError, ValueError):
                continue
    return round(sum(values) / len(values), 1) if values else None


def os_name() -> str:
    values = {}
    for line in _read("/etc/os-release").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values.get("PRETTY_NAME") or values.get("NAME") or platform.system()


def is_system_network_interface(name: str, sys_class_net: Path = Path("/sys/class/net")) -> bool:
    if name == "lo":
        return True
    interface = sys_class_net / name
    if (interface / "bridge").exists():
        return True
    try:
        resolved = interface.resolve(strict=True)
    except OSError:
        return False
    parts = resolved.parts
    return any(parts[index:index + 2] == ("virtual", "net") for index in range(len(parts) - 1))


def network_interfaces(sample: dict) -> list[dict]:
    result = []
    for name, (received, sent) in sample["network"].items():
        state = _read(f"/sys/class/net/{name}/operstate").strip()
        result.append({
            "name": name, "state": state if state in {"up", "down"} else "unknown",
            "rx_bytes": received, "tx_bytes": sent,
            "rx_bytes_per_sec": sample["network_rates"].get(name, (None, None))[0],
            "tx_bytes_per_sec": sample["network_rates"].get(name, (None, None))[1],
            "system": is_system_network_interface(name),
        })
    return sorted(result, key=lambda item: (item["system"], item["name"]))


def disk_io(sample: dict) -> list[dict]:
    return [
        {"device": name, "read_bytes": values[0], "write_bytes": values[1],
         "read_bytes_per_sec": sample["disk_rates"].get(name, (None, None))[0],
         "write_bytes_per_sec": sample["disk_rates"].get(name, (None, None))[1]}
        for name, values in sorted(sample["disks"].items()) if not name.startswith(("loop", "ram"))
    ]


def _block_device_name(device: str | None) -> str:
    if not device:
        return ""
    path = Path(device)
    try:
        device_id = path.stat().st_rdev
        sys_device = Path(f"/sys/dev/block/{os.major(device_id)}:{os.minor(device_id)}")
        return sys_device.resolve(strict=True).name
    except (OSError, AttributeError, ValueError):
        return path.name


def top_processes(limit: int | None = DEFAULT_PROCESS_LIMIT) -> list[dict]:
    if limit is not None and limit <= 0:
        return []
    if not shutil.which("ps"):
        return []
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,user=,comm=,%cpu=,%mem=,rss=,stat=", "--sort=-%cpu"],
            capture_output=True, text=True, timeout=2, check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("resource_processes_unavailable error=%s", type(exc).__name__)
        return []
    processes = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 6)
        try:
            if len(fields) == 7:
                processes.append({"pid": int(fields[0]), "user": fields[1], "name": fields[2], "cpu_percent": float(fields[3]), "memory_percent": float(fields[4]), "rss": int(fields[5]) * 1024, "state": fields[6]})
        except ValueError:
            continue
        if limit is not None and len(processes) >= limit:
            break
    return processes


def build_alerts(volumes: list[dict], ram: dict, temperature: float | None, service: str | None) -> list[dict]:
    alerts = []
    for volume in volumes:
        severity = "critical" if volume["percent"] >= 95 else "warning" if volume["percent"] >= 85 else None
        if severity:
            alerts.append({"code": "disk_usage", "severity": severity, "target": volume["filesystem_id"], "value": volume["percent"]})
    if ram["percent"] >= 90:
        alerts.append({"code": "ram_usage", "severity": "warning", "target": "ram", "value": ram["percent"]})
    if temperature is not None and temperature >= 80:
        alerts.append({"code": "cpu_temperature", "severity": "critical" if temperature >= 90 else "warning", "target": "cpu", "value": temperature})
    if service not in {None, "active", "unknown"}:
        alerts.append({"code": "service_inactive", "severity": "warning", "target": "webnas.service", "value": service})
    return alerts


def collect_dashboard(username: str, *, is_admin: bool, process_limit: int | None = 0) -> dict:
    memory = memory_stats()
    sample = realtime_sample()
    allowed = allowed_root_usage(username)
    temperature = cpu_temperature()
    service = webnas_service_status() if is_admin else None
    all_io_items = disk_io(sample)
    visible_devices = {_block_device_name(volume.get("device")) for volume in allowed}
    io_items = all_io_items if is_admin else [item for item in all_io_items if item["device"] in visible_devices]
    io_by_name = {item["device"]: item for item in all_io_items}
    for volume in allowed:
        name = _block_device_name(volume.get("device"))
        volume.update({key: value for key, value in io_by_name.get(name, {}).items() if key != "device"})
    alerts = build_alerts(allowed, memory["ram"], temperature, service)
    uptime = uptime_seconds()
    return {
        "scope": "admin" if is_admin else "user", "timestamp": time.time(),
        "cpu_percent": sample["cpu"].get("cpu"),
        "cpu_cores": [sample["cpu"][name] for name in sorted(sample["cpu"]) if name != "cpu"],
        "cpu_logical_cores": os.cpu_count() or 0, "cpu_frequency_mhz": cpu_frequency_mhz(),
        "ram": memory["ram"], "swap": memory["swap"], "allowed_roots": allowed,
        "mountpoints": mountpoint_usage() if is_admin else [], "uptime_seconds": uptime,
        "boot_time": time.time() - uptime if uptime is not None else None, "load_average": load_average(),
        "temperature_c": temperature, "webnas_service": service,
        "hostname": socket.gethostname(), "os_name": os_name(), "kernel_version": platform.release(),
        "network_interfaces": network_interfaces(sample), "disk_io": io_items,
        "alerts": alerts,
        "warnings": [
            f"Low free space on {next((volume['path'] for volume in allowed if volume['filesystem_id'] == alert['target']), alert['target'])}"
            if alert["code"] == "disk_usage" else f"{alert['code']}:{alert['target']}"
            for alert in alerts
        ],
        "processes": top_processes(process_limit) if is_admin and (process_limit is None or process_limit > 0) else [],
    }
