from __future__ import annotations

import ipaddress
import os
import platform
import shlex
import shutil
import socket
import subprocess
from pathlib import Path

from . import __version__
from .resource_dashboard import memory_stats, os_name, uptime_seconds


def _command_output(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False, shell=False)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def cpu_details(content: str | None = None) -> dict[str, str | int | None]:
    if content is None:
        try:
            content = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
    entries: list[dict[str, str]] = []
    for block in content.split("\n\n"):
        values: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key.strip().casefold()] = value.strip()
        if values:
            entries.append(values)

    model = next(
        (
            values[key]
            for values in entries
            for key in ("model name", "hardware", "cpu model", "processor")
            if values.get(key) and not values[key].isdigit()
        ),
        platform.processor() or platform.uname().processor or "",
    )
    logical_threads = os.cpu_count() or sum(1 for values in entries if "processor" in values)
    physical_pairs = {
        (values["physical id"], values["core id"])
        for values in entries
        if "physical id" in values and "core id" in values
    }
    if physical_pairs:
        physical_cores = len(physical_pairs)
    else:
        package_cores: dict[str, int] = {}
        for values in entries:
            raw_count = values.get("cpu cores")
            if not raw_count:
                continue
            try:
                package_cores.setdefault(values.get("physical id", "0"), int(raw_count))
            except ValueError:
                continue
        physical_cores = sum(package_cores.values()) if package_cores else logical_threads
    return {
        "model": model[:300],
        "physical_cores": physical_cores or None,
        "logical_threads": logical_threads or None,
    }


def _normalized_addresses(values: list[str]) -> list[str]:
    addresses: set[str] = set()
    for value in values:
        candidate = value.strip().split("%", 1)[0]
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            continue
        addresses.add(str(address))
    return sorted(addresses, key=lambda item: (ipaddress.ip_address(item).version, item))


def ip_addresses() -> list[str]:
    hostname_tool = shutil.which("hostname")
    if hostname_tool:
        addresses = _normalized_addresses(_command_output([hostname_tool, "-I"]).split())
        if addresses:
            return addresses
    try:
        resolved = [str(item[4][0]) for item in socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM)]
    except OSError:
        resolved = []
    return _normalized_addresses(resolved)


def _lspci_gpu_models(content: str) -> list[str]:
    models: list[str] = []
    for line in content.splitlines():
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        if len(fields) < 4 or not any(kind in fields[1].casefold() for kind in ("vga", "3d controller", "display controller")):
            continue
        model = " ".join(fields[2:4]).strip()
        if model and model not in models:
            models.append(model[:300])
    return models


def gpu_models() -> list[str]:
    lspci = shutil.which("lspci")
    if lspci:
        models = _lspci_gpu_models(_command_output([lspci, "-mm"]))
        if models:
            return models

    vendors = {"0x1002": "AMD", "0x10de": "NVIDIA", "0x8086": "Intel"}
    models = []
    for card in Path("/sys/class/drm").glob("card[0-9]*"):
        if not card.name.removeprefix("card").isdigit():
            continue
        try:
            vendor_id = (card / "device/vendor").read_text(encoding="ascii").strip().casefold()
            device_id = (card / "device/device").read_text(encoding="ascii").strip().casefold()
        except OSError:
            continue
        model = f"{vendors.get(vendor_id, 'PCI GPU')} ({vendor_id.removeprefix('0x')}:{device_id.removeprefix('0x')})"
        if model not in models:
            models.append(model)
    return models


def root_storage() -> dict[str, int | float | str] | None:
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return None
    percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    return {"path": "/", "total": usage.total, "used": usage.used, "free": usage.free, "percent": percent}


def collect_host_info() -> dict:
    return {
        "hostname": socket.gethostname(),
        "operating_system": os_name(),
        "kernel_version": platform.release(),
        "architecture": platform.machine() or "unknown",
        "ip_addresses": ip_addresses(),
        "application_version": __version__,
        "uptime_seconds": uptime_seconds(),
        "cpu": cpu_details(),
        "memory": memory_stats()["ram"],
        "gpus": gpu_models(),
        "storage": root_storage(),
    }
