from types import SimpleNamespace

from app import host_info, settings


def test_cpu_details_report_physical_cores_threads_and_model(monkeypatch):
    cpuinfo = """
processor : 0
model name : Example CPU 9000
physical id : 0
core id : 0

processor : 1
model name : Example CPU 9000
physical id : 0
core id : 0

processor : 2
model name : Example CPU 9000
physical id : 0
core id : 1

processor : 3
model name : Example CPU 9000
physical id : 0
core id : 1
"""
    monkeypatch.setattr(host_info.os, "cpu_count", lambda: 4)

    result = host_info.cpu_details(cpuinfo)

    assert result == {"model": "Example CPU 9000", "physical_cores": 2, "logical_threads": 4}


def test_ip_addresses_drop_loopback_duplicates_and_invalid_values():
    assert host_info._normalized_addresses(["127.0.0.1", "192.0.2.5", "192.0.2.5", "::1", "2001:db8::4%eth0", "invalid"]) == ["192.0.2.5", "2001:db8::4"]


def test_lspci_gpu_parser_returns_readable_unique_models():
    output = '00:02.0 "VGA compatible controller" "Intel Corporation" "UHD Graphics 770"\n01:00.0 "3D controller" "NVIDIA Corporation" "Example GPU"\n'

    assert host_info._lspci_gpu_models(output) == ["Intel Corporation UHD Graphics 770", "NVIDIA Corporation Example GPU"]


def test_collect_host_info_combines_safe_system_metrics(monkeypatch):
    monkeypatch.setattr(host_info.socket, "gethostname", lambda: "nas-one")
    monkeypatch.setattr(host_info, "os_name", lambda: "Example Linux 1")
    monkeypatch.setattr(host_info.platform, "release", lambda: "6.12-test")
    monkeypatch.setattr(host_info.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(host_info, "ip_addresses", lambda: ["192.0.2.10"])
    monkeypatch.setattr(host_info, "uptime_seconds", lambda: 90061.0)
    monkeypatch.setattr(host_info, "cpu_details", lambda: {"model": "Example CPU", "physical_cores": 4, "logical_threads": 8})
    monkeypatch.setattr(host_info, "memory_stats", lambda: {"ram": {"total": 16, "used": 8, "free": 8, "percent": 50}, "swap": {}})
    monkeypatch.setattr(host_info, "gpu_models", lambda: ["Example GPU"])
    monkeypatch.setattr(host_info, "root_storage", lambda: {"path": "/", "total": 100, "used": 40, "free": 60, "percent": 40})

    result = host_info.collect_host_info()

    assert result["hostname"] == "nas-one"
    assert result["cpu"]["physical_cores"] == 4
    assert result["memory"]["total"] == 16
    assert result["gpus"] == ["Example GPU"]
    assert result["storage"]["free"] == 60
    assert result["application_version"] == "0.1.12"


def test_host_info_endpoint_requires_system_status_permission(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "authorize", lambda user, permission: calls.append((user.username, permission)))
    monkeypatch.setattr(settings, "collect_host_info", lambda: {"hostname": "nas"})

    result = settings.system_host_info(SimpleNamespace(username="alice"))

    assert result == {"hostname": "nas"}
    assert calls == [("alice", "system.status")]
