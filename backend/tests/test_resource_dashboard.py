from pathlib import Path

from app import resource_dashboard


def test_usage_payload_percent():
    payload = resource_dashboard._usage_payload(100, 25)

    assert payload["free"] == 75
    assert payload["percent"] == 25.0


def test_allowed_root_usage_uses_allowed_roots(monkeypatch, tmp_path: Path):
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setattr(resource_dashboard, "allowed_roots", lambda username: [root])

    result = resource_dashboard.allowed_root_usage("alice")

    assert result
    assert result[0]["path"] == str(root)


def test_collect_dashboard_hides_admin_only_fields(monkeypatch, tmp_path: Path):
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setattr(resource_dashboard, "allowed_roots", lambda username: [root])
    monkeypatch.setattr(resource_dashboard, "cpu_usage_percent", lambda: 12.5)
    monkeypatch.setattr(resource_dashboard, "memory_stats", lambda: {"ram": resource_dashboard._usage_payload(100, 40), "swap": resource_dashboard._usage_payload(0, 0)})
    monkeypatch.setattr(resource_dashboard, "mountpoint_usage", lambda: [{"mountpoint": "/", "percent": 50}])
    monkeypatch.setattr(resource_dashboard, "webnas_service_status", lambda: "active")

    payload = resource_dashboard.collect_dashboard("alice", is_admin=False)

    assert payload["scope"] == "user"
    assert payload["mountpoints"] == []
    assert payload["webnas_service"] is None
