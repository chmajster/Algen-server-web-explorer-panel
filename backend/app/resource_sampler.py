from __future__ import annotations

import asyncio
import copy
import os
import platform
import socket
import threading
import time
from collections import OrderedDict
from typing import Any

from . import resource_dashboard as metrics
from .runtime_events import publish_runtime_event


FAST_INTERVAL_SECONDS = 1.0
MEDIUM_INTERVAL_SECONDS = 7.5
SLOW_INTERVAL_SECONDS = 45.0
MAX_USER_SLOW_CACHE = 64


class ResourceSampler:
    """Share expensive host sampling across all Resource Monitor clients.

    FAST data is process-global and refreshed at most once per second. MEDIUM
    data includes systemctl/thermal/frequency probes and is refreshed much less
    frequently. SLOW data contains mount/filesystem probes. User-visible root
    usage remains keyed by username so authorization boundaries are preserved.
    STATIC data is captured once per process lifetime.
    """

    def __init__(
        self,
        *,
        fast_interval: float = FAST_INTERVAL_SECONDS,
        medium_interval: float = MEDIUM_INTERVAL_SECONDS,
        slow_interval: float = SLOW_INTERVAL_SECONDS,
        user_cache_limit: int = MAX_USER_SLOW_CACHE,
    ) -> None:
        self.fast_interval = max(0.1, fast_interval)
        self.medium_interval = max(self.fast_interval, medium_interval)
        self.slow_interval = max(self.medium_interval, slow_interval)
        self.user_cache_limit = max(1, user_cache_limit)
        self._state_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._last_fast = 0.0
        self._last_medium = 0.0
        self._last_slow = 0.0
        self._fast_sample_count = 0
        self._user_slow: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()

    @property
    def fast_sample_count(self) -> int:
        with self._state_lock:
            return self._fast_sample_count

    def _collect_fast(self) -> dict[str, Any]:
        memory = metrics.memory_stats()
        sample = metrics.realtime_sample()
        uptime = metrics.uptime_seconds()
        return {
            "timestamp": time.time(),
            "memory": memory,
            "sample": sample,
            "uptime_seconds": uptime,
            "boot_time": time.time() - uptime if uptime is not None else None,
            "load_average": metrics.load_average(),
            "network_interfaces": metrics.network_interfaces(sample),
            "disk_io": metrics.disk_io(sample),
        }

    @staticmethod
    def _collect_medium() -> dict[str, Any]:
        return {
            "temperature_c": metrics.cpu_temperature(),
            "cpu_frequency_mhz": metrics.cpu_frequency_mhz(),
            "webnas_service": metrics.webnas_service_status(),
        }

    @staticmethod
    def _collect_slow() -> dict[str, Any]:
        return {"mountpoints": metrics.mountpoint_usage()}

    @staticmethod
    def _collect_static() -> dict[str, Any]:
        return {
            "hostname": socket.gethostname(),
            "os_name": metrics.os_name(),
            "kernel_version": platform.release(),
            "cpu_logical_cores": os.cpu_count() or 0,
        }

    def refresh_due(self, *, now: float | None = None, force: bool = False) -> bool:
        """Refresh due tiers and return True when a FAST sample was collected."""

        monotonic_now = time.monotonic() if now is None else now
        with self._refresh_lock:
            with self._state_lock:
                need_static = "static" not in self._state
                need_fast = force or "fast" not in self._state or monotonic_now - self._last_fast >= self.fast_interval
                need_medium = force or "medium" not in self._state or monotonic_now - self._last_medium >= self.medium_interval
                need_slow = force or "slow" not in self._state or monotonic_now - self._last_slow >= self.slow_interval

            static = self._collect_static() if need_static else None
            fast = self._collect_fast() if need_fast else None
            medium = self._collect_medium() if need_medium else None
            slow = self._collect_slow() if need_slow else None

            with self._state_lock:
                if static is not None:
                    self._state["static"] = static
                if fast is not None:
                    self._state["fast"] = fast
                    self._last_fast = monotonic_now
                    self._fast_sample_count += 1
                if medium is not None:
                    self._state["medium"] = medium
                    self._last_medium = monotonic_now
                if slow is not None:
                    self._state["slow"] = slow
                    self._last_slow = monotonic_now
            return fast is not None

    def _allowed_roots(self, username: str, *, now: float) -> list[dict[str, Any]]:
        with self._state_lock:
            cached = self._user_slow.get(username)
            if cached and now - cached[0] < self.slow_interval:
                self._user_slow.move_to_end(username)
                return copy.deepcopy(cached[1])

        value = metrics.allowed_root_usage(username)
        with self._state_lock:
            self._user_slow[username] = (now, copy.deepcopy(value))
            self._user_slow.move_to_end(username)
            while len(self._user_slow) > self.user_cache_limit:
                self._user_slow.popitem(last=False)
        return value

    def invalidate_user(self, username: str | None = None) -> None:
        with self._state_lock:
            if username is None:
                self._user_slow.clear()
            else:
                self._user_slow.pop(username, None)

    def dashboard(self, username: str, *, is_admin: bool, process_limit: int | None = 0) -> dict[str, Any]:
        # The background loop is the normal producer. This fallback also makes
        # startup/tests safe and is serialized, so concurrent callers cannot
        # trigger duplicate full samples.
        self.refresh_due()
        with self._state_lock:
            static = copy.deepcopy(self._state["static"])
            fast = copy.deepcopy(self._state["fast"])
            medium = copy.deepcopy(self._state["medium"])
            slow = copy.deepcopy(self._state["slow"])

        allowed = self._allowed_roots(username, now=time.monotonic())
        all_io_items = fast["disk_io"]
        visible_devices = {metrics._block_device_name(volume.get("device")) for volume in allowed}
        io_items = all_io_items if is_admin else [item for item in all_io_items if item["device"] in visible_devices]
        io_by_name = {item["device"]: item for item in all_io_items}
        for volume in allowed:
            name = metrics._block_device_name(volume.get("device"))
            volume.update({key: value for key, value in io_by_name.get(name, {}).items() if key != "device"})

        memory = fast["memory"]
        temperature = medium["temperature_c"]
        service = medium["webnas_service"] if is_admin else None
        alerts = metrics.build_alerts(allowed, memory["ram"], temperature, service)
        sample = fast["sample"]
        return {
            "scope": "admin" if is_admin else "user",
            "timestamp": fast["timestamp"],
            "cpu_percent": sample["cpu"].get("cpu"),
            "cpu_cores": [sample["cpu"][name] for name in sorted(sample["cpu"]) if name != "cpu"],
            "cpu_logical_cores": static["cpu_logical_cores"],
            "cpu_frequency_mhz": medium["cpu_frequency_mhz"],
            "ram": memory["ram"],
            "swap": memory["swap"],
            "allowed_roots": allowed,
            "mountpoints": slow["mountpoints"] if is_admin else [],
            "uptime_seconds": fast["uptime_seconds"],
            "boot_time": fast["boot_time"],
            "load_average": fast["load_average"],
            "temperature_c": temperature,
            "webnas_service": service,
            "hostname": static["hostname"],
            "os_name": static["os_name"],
            "kernel_version": static["kernel_version"],
            "network_interfaces": fast["network_interfaces"],
            "disk_io": io_items,
            "alerts": alerts,
            "warnings": [
                f"Low free space on {next((volume['path'] for volume in allowed if volume['filesystem_id'] == alert['target']), alert['target'])}"
                if alert["code"] == "disk_usage"
                else f"{alert['code']}:{alert['target']}"
                for alert in alerts
            ],
            "processes": metrics.top_processes(process_limit)
            if is_admin and (process_limit is None or process_limit > 0)
            else [],
        }


resource_sampler = ResourceSampler()


async def resource_sampler_loop() -> None:
    """Lifespan task that samples once and fans out lightweight invalidations."""

    while True:
        refreshed = await asyncio.to_thread(resource_sampler.refresh_due)
        if refreshed:
            publish_runtime_event("resource.sample.updated", {"timestamp": time.time()})
        await asyncio.sleep(0.25)
