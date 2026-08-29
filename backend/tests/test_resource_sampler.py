from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app import resource_sampler as sampler_module


def _fast_payload() -> dict:
    sample = {
        "cpu": {"cpu": 10.0, "cpu0": 10.0},
        "network": {},
        "network_rates": {},
        "disks": {},
        "disk_rates": {},
    }
    metric = {"total": 100, "used": 25, "free": 75, "percent": 25.0}
    return {
        "timestamp": 1.0,
        "memory": {"ram": metric, "swap": metric},
        "sample": sample,
        "uptime_seconds": 100.0,
        "boot_time": 0.0,
        "load_average": [0.1, 0.2, 0.3],
        "network_interfaces": [],
        "disk_io": [],
    }


def test_tiers_refresh_at_independent_intervals(monkeypatch):
    sampler = sampler_module.ResourceSampler(fast_interval=1, medium_interval=5, slow_interval=30)
    calls = SimpleNamespace(fast=0, medium=0, slow=0, static=0)

    def fast():
        calls.fast += 1
        return _fast_payload()

    def medium():
        calls.medium += 1
        return {"temperature_c": None, "cpu_frequency_mhz": None, "webnas_service": "active"}

    def slow():
        calls.slow += 1
        return {"mountpoints": []}

    def static():
        calls.static += 1
        return {"hostname": "host", "os_name": "Linux", "kernel_version": "test", "cpu_logical_cores": 2}

    monkeypatch.setattr(sampler, "_collect_fast", fast)
    monkeypatch.setattr(sampler, "_collect_medium", medium)
    monkeypatch.setattr(sampler, "_collect_slow", slow)
    monkeypatch.setattr(sampler, "_collect_static", static)

    assert sampler.refresh_due(now=100.0) is True
    assert sampler.refresh_due(now=101.0) is True
    assert sampler.refresh_due(now=102.0) is True
    assert sampler.refresh_due(now=105.0) is True
    assert sampler.refresh_due(now=130.0) is True

    assert calls.fast == 5
    assert calls.medium == 3  # 100, 105, 130
    assert calls.slow == 2  # 100, 130
    assert calls.static == 1


def test_ten_clients_share_one_fast_sample_and_one_user_slow_probe(monkeypatch):
    sampler = sampler_module.ResourceSampler(fast_interval=60, medium_interval=60, slow_interval=60)
    calls = SimpleNamespace(fast=0, roots=0)
    start = threading.Barrier(10)

    def fast():
        calls.fast += 1
        return _fast_payload()

    monkeypatch.setattr(sampler, "_collect_fast", fast)
    monkeypatch.setattr(
        sampler,
        "_collect_medium",
        lambda: {"temperature_c": None, "cpu_frequency_mhz": None, "webnas_service": "active"},
    )
    monkeypatch.setattr(sampler, "_collect_slow", lambda: {"mountpoints": []})
    monkeypatch.setattr(
        sampler,
        "_collect_static",
        lambda: {"hostname": "host", "os_name": "Linux", "kernel_version": "test", "cpu_logical_cores": 2},
    )

    def roots(_username: str):
        calls.roots += 1
        time.sleep(0.05)
        return []

    def dashboard(_index: int):
        start.wait(timeout=2)
        return sampler.dashboard("alice", is_admin=False)

    monkeypatch.setattr(sampler_module.metrics, "allowed_root_usage", roots)

    with ThreadPoolExecutor(max_workers=10) as pool:
        payloads = list(pool.map(dashboard, range(10)))

    assert calls.fast == 1
    assert sampler.fast_sample_count == 1
    assert calls.roots == 1
    assert all(payload["scope"] == "user" for payload in payloads)


def test_user_slow_cache_is_isolated_and_invalidatable(monkeypatch):
    sampler = sampler_module.ResourceSampler(fast_interval=60, medium_interval=60, slow_interval=60)
    calls: list[str] = []
    monkeypatch.setattr(sampler, "_collect_fast", _fast_payload)
    monkeypatch.setattr(
        sampler,
        "_collect_medium",
        lambda: {"temperature_c": None, "cpu_frequency_mhz": None, "webnas_service": "active"},
    )
    monkeypatch.setattr(sampler, "_collect_slow", lambda: {"mountpoints": []})
    monkeypatch.setattr(
        sampler,
        "_collect_static",
        lambda: {"hostname": "host", "os_name": "Linux", "kernel_version": "test", "cpu_logical_cores": 2},
    )
    monkeypatch.setattr(sampler_module.metrics, "allowed_root_usage", lambda username: calls.append(username) or [])

    sampler.dashboard("alice", is_admin=False)
    sampler.dashboard("bob", is_admin=False)
    sampler.dashboard("alice", is_admin=False)
    sampler.invalidate_user("alice")
    sampler.dashboard("alice", is_admin=False)

    assert calls == ["alice", "bob", "alice"]


def test_non_admin_never_receives_cached_service_or_mountpoints(monkeypatch):
    sampler = sampler_module.ResourceSampler(fast_interval=60, medium_interval=60, slow_interval=60)
    monkeypatch.setattr(sampler, "_collect_fast", _fast_payload)
    monkeypatch.setattr(
        sampler,
        "_collect_medium",
        lambda: {"temperature_c": 50.0, "cpu_frequency_mhz": 3000.0, "webnas_service": "active"},
    )
    monkeypatch.setattr(sampler, "_collect_slow", lambda: {"mountpoints": [{"mountpoint": "/"}]})
    monkeypatch.setattr(
        sampler,
        "_collect_static",
        lambda: {"hostname": "host", "os_name": "Linux", "kernel_version": "test", "cpu_logical_cores": 2},
    )
    monkeypatch.setattr(sampler_module.metrics, "allowed_root_usage", lambda username: [])

    payload = sampler.dashboard("alice", is_admin=False)

    assert payload["webnas_service"] is None
    assert payload["mountpoints"] == []
