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
from app.ldap_authentication.repository import LdapAuthenticationRepository
from app.modules.ansible_controller import awx
from app.modules.hosts_manager import agent as hosts_agent
from app.modules.ldap_manager.repository import LdapManagerRepository
from app.modules.proxmox_manager import ProxmoxApiClient
from app.modules.proxmox_manager import inventory as proxmox_inventory
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


def test_hosts_manager_agent_transport_disables_redirects() -> None:
    handler = hosts_agent._NoRedirectHandler()
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


def test_ldap_manager_corrupted_persisted_connection_is_safely_normalized(tmp_path: Path) -> None:
    repository = LdapManagerRepository(tmp_path / "ldap-manager.sqlite3")
    with repository.connect() as connection:
        connection.execute(
            """
            INSERT INTO ldap_manager_connections(
                id,name,directory_type,servers_json,security_mode,verify_tls,ca_certificate,base_dn,bind_dn,
                bind_secret_id,connect_timeout,operation_timeout,created_at,updated_at,updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "broken",
                "Broken",
                "generic",
                json.dumps(["bad", {"host": "ldap.example", "port": "bad"}, {"host": "ldap.example", "port": 389, "priority": 5}]),
                "starttls",
                "not-a-bool",
                "",
                "dc=example,dc=com",
                "cn=bind,dc=example,dc=com",
                "secret-id",
                "nan",
                "not-a-number",
                "inf",
                -10,
                "admin",
            ),
        )

    value = repository.get("broken")

    assert value["servers"] == [{"host": "ldap.example", "port": 389, "priority": 5}]
    assert value["verify_tls"] is True
    assert value["connect_timeout"] == 5.0
    assert value["operation_timeout"] == 15.0
    assert value["created_at"] == 0.0
    assert value["updated_at"] == 0.0


def test_ldap_authentication_corrupted_persisted_state_does_not_break_settings(tmp_path: Path) -> None:
    repository = LdapAuthenticationRepository(tmp_path / "ldap-auth.sqlite3")
    with repository.connect() as connection:
        connection.execute(
            """
            UPDATE ldap_auth_settings_v2 SET
                enabled='broken',directory_type='bogus',failover_strategy='bogus',security_mode='bogus',
                verify_tls='broken',connect_timeout='nan',operation_timeout='not-a-number',group_cache_ttl_seconds='huge'
            WHERE id=1
            """
        )
        connection.execute(
            "INSERT INTO ldap_auth_servers(id,host,port,priority,enabled,position) VALUES(?,?,?,?,?,?)",
            ("bad", "ldap.example", "bad", 10, 1, 0),
        )
        connection.execute(
            "INSERT INTO ldap_auth_servers(id,host,port,priority,enabled,position) VALUES(?,?,?,?,?,?)",
            ("good", "ldap2.example", 636, 5, 1, 1),
        )
        connection.execute(
            "INSERT INTO ldap_auth_group_mappings(id,group_dn,role,allow_json,deny_json,priority,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?)",
            ("mapping", "cn=ops,dc=example,dc=com", "user", "[]", "[]", "broken", 1, "admin"),
        )

    settings = repository.settings()
    mappings = repository.mappings()

    assert settings["enabled"] is False
    assert settings["directory_type"] == "auto"
    assert settings["failover_strategy"] == "priority"
    assert settings["security_mode"] == "starttls"
    assert settings["verify_tls"] is True
    assert settings["connect_timeout"] == 5.0
    assert settings["operation_timeout"] == 10.0
    assert settings["group_cache_ttl_seconds"] == 300
    assert settings["servers"] == [{"id": "good", "host": "ldap2.example", "port": 636, "priority": 5, "enabled": True}]
    assert mappings[0]["priority"] == 100


def test_proxmox_inventory_malformed_metrics_degrade_without_crashing() -> None:
    class Client:
        def get(self, path: str):
            if path == "nodes":
                return [{"node": "pve1", "status": "online", "uptime": "bad", "cpu": "nan", "maxcpu": {}}]
            if path == "nodes/pve1/status":
                return {
                    "uptime": "bad",
                    "cpu": "nan",
                    "cpuinfo": {"cpus": "not-int"},
                    "memory": {"used": "bad", "total": "inf"},
                    "rootfs": {"used": "bad", "total": "nan"},
                    "loadavg": "not-a-list",
                }
            if path == "nodes/pve1/storage":
                return [
                    {
                        "storage": "local",
                        "total": "bad",
                        "used": "nan",
                        "avail": "nope",
                        "active": "0",
                        "shared": "false",
                        "enabled": "0",
                    }
                ]
            raise AssertionError(path)

    client = Client()

    class Manager:
        def connections(self, *, active_only: bool = False):
            assert active_only is True
            return [{"id": "connection", "name": "PVE"}]

        def _client(self, _connection):
            return client

        def _resources(self, _connection, _client=None):
            return []

    manager = Manager()
    node = proxmox_inventory.list_nodes(manager)["nodes"][0]
    storage = proxmox_inventory.list_storage(manager)["storage"][0]

    assert node["uptime"] == 0
    assert node["cpu"] == 0.0
    assert node["maxcpu"] == 0
    assert node["mem"] == 0
    assert node["maxmem"] == 0
    assert node["storage_used"] == 0
    assert node["storage_total"] == 0
    assert node["load_average"] == []
    assert storage["total"] == 0
    assert storage["used"] == 0
    assert storage["free"] == 0
    assert storage["status"] == "unavailable"
    assert storage["shared"] is False
    assert storage["enabled"] is False
