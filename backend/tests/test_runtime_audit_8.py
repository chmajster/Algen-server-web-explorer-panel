from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import transport_settings
from app.alerts import delivery as alert_delivery
from app.app_store import state as app_state
from app.modules.ansible_controller import awx
from app.modules.proxmox_manager import ProxmoxApiClient
from app.modules.proxmox_manager import secure_client as proxmox_secure


def test_awx_authenticated_transport_disables_redirects() -> None:
    handler = awx._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://attacker.example/") is None


def test_proxmox_manager_installs_hardened_client_and_disables_redirects() -> None:
    service_module = importlib.import_module("app.modules.proxmox_manager.service")
    assert service_module.ProxmoxApiClient is ProxmoxApiClient
    assert ProxmoxApiClient is proxmox_secure.HardenedProxmoxApiClient

    handler = proxmox_secure._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://attacker.example/") is None


def test_alert_webhook_transport_disables_redirects() -> None:
    handler = alert_delivery._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://attacker.example/") is None


def test_app_store_type_corruption_is_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path)
    path = app_state.app_state_path("samba")
    path.write_text(
        json.dumps({"installed": "yes", "history": {"bad": True}, "changes": "not-a-list", "custom": 7}),
        encoding="utf-8",
    )

    state = app_state.read_state("samba")

    assert state["installed"] is False
    assert state["history"] == []
    assert state["changes"] == []
    assert state["custom"] == 7


def test_transport_gateway_rejects_type_corrupted_port_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "deployment.json").write_text(json.dumps({"active_port": {"bad": True}}), encoding="utf-8")
    monkeypatch.setattr(
        transport_settings,
        "get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path))),
    )

    with pytest.raises(HTTPException) as error:
        transport_settings._require_standard_gateway()

    assert error.value.status_code == 409
