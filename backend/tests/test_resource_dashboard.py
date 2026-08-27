from pathlib import Path
from types import SimpleNamespace

from app import resource_dashboard


def _metric(percent: float = 25.0) -> dict:
    return {"total": 100, "used": percent, "free": 100 - percent, "percent": percent}


def _sample() -> dict:
    return {
        "cpu": {"cpu": 12.5, "cpu0": 10.0, "cpu1": 15.0},
        "network": {"eth0": (1000, 2000)},
        "network_rates": {"eth0": (10.0, 20.0)},
        "disks": {"sda": (4096, 8192), "sdb": (100, 200)},
        "disk_rates": {"sda": (30.0, 40.0), "sdb": (1.0, 2.0)},
    }


def test_usage_payload_percent():
    payload = resource_dashboard._usage_payload(100, 25)

    assert payload["free"] == 75
    assert payload["percent"] == 25.0


def test_proc_parsers_and_delta_cpu_percentage():
    previous = resource_dashboard.parse_proc_stat("cpu 100 0 100 800 0\ncpu0 50 0 50 400 0\nintr 4")
    current = resource_dashboard.parse_proc_stat("cpu 150 0 150 900 0\ncpu0 75 0 75 450 0")

    assert resource_dashboard.cpu_percentages(current, previous) == {"cpu": 50.0, "cpu0": 50.0}
    assert resource_dashboard.parse_net_dev("eth0: 100 0 0 0 0 0 0 0 250 0 0 0 0 0 0 0") == {"eth0": (100, 250)}
    assert resource_dashboard.parse_diskstats("8 0 sda 1 0 2 0 1 0 4 0") == {"sda": (1024, 2048)}


def test_counter_rates_handle_first_sample_and_counter_reset():
    assert resource_dashboard.counter_rates({"eth0": (100, 200)}, None, 2) == {"eth0": (None, None)}
    assert resource_dashboard.counter_rates({"eth0": (140, 260)}, {"eth0": (100, 200)}, 2) == {"eth0": (20.0, 30.0)}
    assert resource_dashboard.counter_rates({"eth0": (5, 10)}, {"eth0": (100, 200)}, 2) == {"eth0": (0.0, 0.0)}


def test_realtime_sample_uses_monotonic_deltas_without_sleep(monkeypatch):
    contents = {
        "/proc/stat": "cpu 100 0 100 800 0\ncpu0 50 0 50 400 0",
        "/proc/net/dev": "eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0",
        "/proc/diskstats": "8 0 sda 1 0 2 0 1 0 4 0",
    }
    monkeypatch.setattr(resource_dashboard, "_read", lambda path: contents[path])
    resource_dashboard._last_sample = None

    first = resource_dashboard.realtime_sample(now=10.0)
    contents["/proc/stat"] = "cpu 150 0 150 900 0\ncpu0 75 0 75 450 0"
    contents["/proc/net/dev"] = "eth0: 1200 0 0 0 0 0 0 0 2400 0 0 0 0 0 0 0"
    contents["/proc/diskstats"] = "8 0 sda 1 0 4 0 1 0 8 0"
    second = resource_dashboard.realtime_sample(now=12.0)

    assert first["cpu"]["cpu"] is None
    assert second["cpu"]["cpu"] == 50.0
    assert second["network_rates"]["eth0"] == (100.0, 200.0)
    assert second["disk_rates"]["sda"] == (512.0, 1024.0)


def test_realtime_sample_tolerates_missing_proc_files(monkeypatch):
    monkeypatch.setattr(resource_dashboard, "_read", lambda path: "")
    resource_dashboard._last_sample = None

    assert resource_dashboard.realtime_sample(now=1.0)["cpu"] == {}


def test_network_interfaces_tolerate_missing_sys_state(monkeypatch):
    monkeypatch.setattr(resource_dashboard, "_read", lambda path: "")

    interfaces = resource_dashboard.network_interfaces(_sample())

    assert interfaces[0]["name"] == "eth0"
    assert interfaces[0]["state"] == "unknown"


def test_allowed_root_usage_uses_allowed_roots(monkeypatch, tmp_path: Path):
    root = tmp_path / "home"
    alias = root / "files"
    alias.mkdir(parents=True)
    monkeypatch.setattr(resource_dashboard, "allowed_roots", lambda username: [root, alias])
    monkeypatch.setattr(resource_dashboard, "mount_records", lambda: [])

    result = resource_dashboard.allowed_root_usage("alice")

    assert len(result) == 1
    assert result[0]["path"] == str(root)
    assert result[0]["paths"] == sorted([str(root), str(alias)])


def test_allowed_roots_with_equal_capacity_are_not_grouped_across_devices(monkeypatch):
    class FakeRoot:
        def __init__(self, value: str, device: int):
            self.value = value
            self.device = device

        def resolve(self, strict: bool = False):
            return self

        def stat(self):
            return SimpleNamespace(st_dev=self.device)

        def __str__(self):
            return self.value

    roots = [FakeRoot("/data/a", 101), FakeRoot("/data/b", 202)]
    monkeypatch.setattr(resource_dashboard, "allowed_roots", lambda username: roots)
    monkeypatch.setattr(resource_dashboard, "disk_usage", lambda path: {"path": str(path), **_metric(50)})
    monkeypatch.setattr(resource_dashboard, "mount_records", lambda: [])

    result = resource_dashboard.allowed_root_usage("alice")

    assert len(result) == 2
    assert result[0]["filesystem_id"] != result[1]["filesystem_id"]


def test_alert_thresholds():
    volumes = [
        {"filesystem_id": "a", "percent": 84.9},
        {"filesystem_id": "b", "percent": 85},
        {"filesystem_id": "c", "percent": 95},
    ]

    alerts = resource_dashboard.build_alerts(volumes, _metric(90), 80, "failed")

    assert [(alert["code"], alert["severity"]) for alert in alerts] == [
        ("disk_usage", "warning"),
        ("disk_usage", "critical"),
        ("ram_usage", "warning"),
        ("cpu_temperature", "warning"),
        ("service_inactive", "warning"),
    ]


def test_top_processes_returns_complete_list_and_respects_limit(monkeypatch):
    output = "\n".join(f"{pid} user proc{pid} 1.0 2.0 4 S" for pid in range(1, 61))
    monkeypatch.setattr(resource_dashboard.shutil, "which", lambda command: "/usr/bin/ps" if command == "ps" else None)
    monkeypatch.setattr(resource_dashboard.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output))

    assert len(resource_dashboard.top_processes()) == 60
    assert len(resource_dashboard.top_processes(25)) == 25
    assert resource_dashboard.top_processes(25)[-1]["pid"] == 25


def test_collect_dashboard_hides_admin_only_and_unrelated_disk_data(monkeypatch):
    allowed = [{"path": "/home/alice", "paths": ["/home/alice"], "filesystem_id": "fs-8-0", "device": "/dev/sda", **_metric()}]
    monkeypatch.setattr(resource_dashboard, "memory_stats", lambda: {"ram": _metric(40), "swap": _metric(0)})
    monkeypatch.setattr(resource_dashboard, "realtime_sample", _sample)
    monkeypatch.setattr(resource_dashboard, "allowed_root_usage", lambda username: allowed)
    monkeypatch.setattr(resource_dashboard, "cpu_temperature", lambda: None)
    monkeypatch.setattr(resource_dashboard, "uptime_seconds", lambda: 100.0)
    monkeypatch.setattr(resource_dashboard, "load_average", lambda: [0.1, 0.2, 0.3])
    monkeypatch.setattr(resource_dashboard, "cpu_frequency_mhz", lambda: 1000.0)
    monkeypatch.setattr(resource_dashboard, "os_name", lambda: "Linux Test")
    monkeypatch.setattr(resource_dashboard, "network_interfaces", lambda sample: [])
    monkeypatch.setattr(resource_dashboard, "mountpoint_usage", lambda: [{"mountpoint": "/", "percent": 50}])
    monkeypatch.setattr(resource_dashboard, "webnas_service_status", lambda: "active")
    monkeypatch.setattr(resource_dashboard, "top_processes", lambda: [{"pid": 1}])

    payload = resource_dashboard.collect_dashboard("alice", is_admin=False)

    assert payload["scope"] == "user"
    assert payload["mountpoints"] == []
    assert payload["processes"] == []
    assert payload["webnas_service"] is None
    assert [item["device"] for item in payload["disk_io"]] == ["sda"]
    assert payload["allowed_roots"][0]["read_bytes_per_sec"] == 30.0


def test_collect_dashboard_exposes_admin_metrics(monkeypatch):
    monkeypatch.setattr(resource_dashboard, "memory_stats", lambda: {"ram": _metric(40), "swap": _metric(0)})
    monkeypatch.setattr(resource_dashboard, "realtime_sample", _sample)
    monkeypatch.setattr(resource_dashboard, "allowed_root_usage", lambda username: [])
    monkeypatch.setattr(resource_dashboard, "cpu_temperature", lambda: None)
    monkeypatch.setattr(resource_dashboard, "uptime_seconds", lambda: None)
    monkeypatch.setattr(resource_dashboard, "load_average", lambda: None)
    monkeypatch.setattr(resource_dashboard, "cpu_frequency_mhz", lambda: None)
    monkeypatch.setattr(resource_dashboard, "os_name", lambda: "Linux")
    monkeypatch.setattr(resource_dashboard, "network_interfaces", lambda sample: [])
    monkeypatch.setattr(resource_dashboard, "mountpoint_usage", lambda: [{"mountpoint": "/", "percent": 50}])
    monkeypatch.setattr(resource_dashboard, "webnas_service_status", lambda: "active")
    monkeypatch.setattr(resource_dashboard, "top_processes", lambda: [{"pid": 1}])

    payload = resource_dashboard.collect_dashboard("root", is_admin=True)

    assert payload["scope"] == "admin"
    assert payload["mountpoints"]
    assert payload["processes"] == [{"pid": 1}]
    assert {item["device"] for item in payload["disk_io"]} == {"sda", "sdb"}
