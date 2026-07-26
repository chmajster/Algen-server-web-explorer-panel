from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app import network_management as management


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(management, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path))))
    monkeypatch.setattr(management, "record_activity", lambda *args, **kwargs: None)
    while management._transaction_lock.locked():
        management._transaction_lock.release()


def interface(**changes):
    value = {
        "name": "eth0",
        "kind": "physical",
        "ipv4": {"method": "manual", "addresses": [{"address": "192.0.2.10", "prefix": 24}], "gateway": "192.0.2.1"},
        "ipv6": {"method": "manual", "addresses": [{"address": "2001:db8::10", "prefix": 64}], "gateway": "2001:db8::1"},
    }
    value.update(changes)
    return management.InterfaceConfiguration.model_validate(value)


@pytest.mark.parametrize("name", ["eth 0", "../eth0", "eth0;reboot", "x" * 16, "\neth0"])
def test_interface_names_follow_linux_ifnamesiz(name):
    with pytest.raises(ValidationError):
        interface(name=name)


def test_ip_models_validate_families_and_reject_extra_fields():
    with pytest.raises(ValidationError):
        management.IPConfiguration(method="manual", addresses=[{"address": "192.0.2.10", "prefix": 33}])
    with pytest.raises(ValidationError):
        management.IPConfiguration(method="manual", addresses=[{"address": "192.0.2.10", "prefix": 24}], gateway="2001:db8::1")
    with pytest.raises(ValidationError):
        management.IPConfiguration(method="dhcp", raw_command="ip route flush")


def test_bond_vlan_and_bridge_validation():
    bond = interface(name="bond0", kind="bond", members=["eth0", "eth1"], bond_mode="802.3ad")
    vlan = interface(name="vlan20", kind="vlan", parent="bond0", vlan_id=20)
    bridge = interface(name="br0", kind="bridge", members=["eth2"])
    assert bond.members == ["eth0", "eth1"]
    assert vlan.vlan_id == 20
    assert bridge.stp is True
    with pytest.raises(ValidationError):
        interface(name="bond0", kind="bond", members=["lo"])
    with pytest.raises(ValidationError):
        interface(name="vlan20", kind="vlan", parent="eth0", vlan_id=4095)


def test_routes_validate_ipv4_ipv6_and_non_unicast_types():
    ipv4 = management.ManagedRoute(name="LAN", family="ipv4", destination="192.0.2.4/24", gateway="192.0.2.1")
    ipv6 = management.ManagedRoute(name="v6", family="ipv6", destination="2001:db8::/64", interface="eth0")
    blackhole = management.ManagedRoute(name="blocked", family="ipv4", destination="198.51.100.0/24", route_type="blackhole")
    assert ipv4.destination == "192.0.2.0/24"
    assert ipv6.destination == "2001:db8::/64"
    assert blackhole.gateway is None
    with pytest.raises(ValidationError):
        management.ManagedRoute(name="bad", family="ipv4", destination="192.0.2.0/24", gateway="2001:db8::1")


def test_traffic_control_is_typed_and_bounded():
    rule = management.TrafficRule(name="API", interface="eth0", maximum_kbit=10_000, guaranteed_kbit=1_000, protocol="tcp", destination_port=443)
    commands = management._commands_for_generic(management.NetworkChange(operation="save_traffic", traffic=rule))
    assert all(isinstance(command, list) for command in commands)
    assert all("shell=True" not in item for command in commands for item in command)
    with pytest.raises(ValidationError):
        management.TrafficRule(name="bad", interface="eth0", maximum_kbit=100, guaranteed_kbit=200)
    with pytest.raises(ValidationError):
        management.TrafficRule(name="bad", interface="eth0", maximum_kbit=100, protocol="any", destination_port=80)


def test_networkmanager_generates_fixed_argument_arrays(monkeypatch):
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    change = management.NetworkChange(operation="save_interface", interface=interface(name="bond0", kind="bond", members=["eth0", "eth1"]))
    commands = management.NetworkManagerProvider().commands(change)
    assert commands[0][:3] == ["/usr/bin/nmcli", "connection", "delete"]
    assert any(command[:4] == ["/usr/bin/nmcli", "connection", "add", "type"] for command in commands)
    assert not any(isinstance(command, str) for command in commands)


def test_networkd_and_netplan_render_managed_configuration():
    value = interface(name="vlan20", kind="vlan", parent="eth0", vlan_id=20)
    networkd = management.render_networkd(value)
    netplan = management.render_netplan(value)
    assert "80-webnas-vlan20.network" in networkd
    assert "Id=20" in networkd["80-webnas-vlan20.netdev"]
    assert "vlans:" in netplan
    assert "link: eth0" in netplan


@pytest.mark.parametrize(
    ("tools", "provider"),
    [
        ({"nmcli"}, "networkmanager"),
        ({"netplan"}, "netplan"),
        ({"networkctl"}, "systemd-networkd"),
        (set(), "ifupdown"),
    ],
)
def test_provider_detection(monkeypatch, tools, provider):
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}" if name in tools else None)
    monkeypatch.setattr(management, "_run_command", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "running", ""))
    monkeypatch.setattr(management.Path, "glob", lambda self, pattern: iter([self / "01.yaml"]) if "netplan" in tools else iter([]))
    monkeypatch.setattr(management.Path, "exists", lambda self: False)
    assert management.detect_provider()[0].id == provider


def test_ambiguous_providers_are_read_only(monkeypatch):
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"nmcli", "networkctl"} else None)
    monkeypatch.setattr(management, "_run_command", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "running", ""))
    monkeypatch.setattr(management.Path, "exists", lambda self: False)
    provider, warnings = management.detect_provider()
    assert provider.writable is False
    assert "Ambiguous" in warnings[0]


def test_bond_member_and_vlan_conflicts_are_rejected(monkeypatch):
    state = {
        "interfaces": {
            "bond1": interface(name="bond1", kind="bond", members=["eth1"]).model_dump(mode="json"),
            "vlan20": interface(name="vlan20", kind="vlan", parent="eth0", vlan_id=20).model_dump(mode="json"),
        },
        "dns": None, "routes": {}, "traffic": {},
    }
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": [{"name": "eth1", "system": False, "addresses": []}]})
    with pytest.raises(HTTPException, match="already belongs"):
        management._conflicts(management.NetworkChange(operation="save_interface", interface=interface(name="bond0", kind="bond", members=["eth1"])), state)
    with pytest.raises(HTTPException, match="VLAN ID"):
        management._conflicts(management.NetworkChange(operation="save_interface", interface=interface(name="other20", kind="vlan", parent="eth0", vlan_id=20)), state)


def test_high_risk_plan_is_bound_to_actor_and_requires_phrase(monkeypatch):
    monkeypatch.setattr(management, "detect_provider", lambda: (management.NetworkManagerProvider(), []))
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": []})
    monkeypatch.setattr(management, "routing_snapshot", lambda: {"gateways": [{"device": "eth0"}]})
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface()), "alice", "eth0")
    assert plan["high_risk"] is True
    assert plan["required_phrase"] == "APPLY eth0"
    assert plan["rollback_seconds"] == 15
    with pytest.raises(HTTPException):
        management.apply_plan(plan["id"], "bob", "APPLY eth0")


def test_apply_snapshot_confirm_and_manual_rollback(monkeypatch):
    monkeypatch.setattr(management, "detect_provider", lambda: (management.NetworkManagerProvider(), []))
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": []})
    monkeypatch.setattr(management, "routing_snapshot", lambda: {"gateways": []})
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(management, "_run_command", lambda command, timeout=0: subprocess.CompletedProcess(command, 0, "", ""))
    monkeypatch.setattr(management, "_schedule_rollback", lambda transaction_id, seconds: f"webnas-network-rollback-{transaction_id}.service")
    plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface()), "alice", None)
    transaction = management.apply_plan(plan["id"], "alice", "")
    snapshot = management._state_root() / "transactions" / transaction["id"] / "snapshot.json"
    assert snapshot.exists()
    confirmed = management.confirm_transaction(transaction["id"], "alice")
    assert confirmed["state"] == "confirmed"

    second = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface(mtu=1400)), "alice", None)
    pending = management.apply_plan(second["id"], "alice", "")
    rolled_back = management.rollback_transaction(pending["id"], "alice")
    assert rolled_back["state"] == "rolled_back"


def test_partial_apply_failure_starts_immediate_rollback(monkeypatch):
    monkeypatch.setattr(management, "detect_provider", lambda: (management.NetworkManagerProvider(), []))
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": []})
    monkeypatch.setattr(management, "routing_snapshot", lambda: {"gateways": []})
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = {"count": 0, "rollback": 0}

    def run(command, timeout=0):
        calls["count"] += 1
        failed = command[1:3] == ["connection", "add"]
        return subprocess.CompletedProcess(command, 1 if failed else 0, "", "failed" if failed else "")

    monkeypatch.setattr(management, "_run_command", run)
    monkeypatch.setattr(management, "rollback_transaction", lambda *args, **kwargs: calls.__setitem__("rollback", calls["rollback"] + 1))
    plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface()), "alice", None)
    with pytest.raises(HTTPException):
        management.apply_plan(plan["id"], "alice", "")
    assert calls["rollback"] == 1


def test_parallel_operations_are_locked():
    management._transaction_lock.acquire()
    try:
        with pytest.raises(HTTPException, match="Another network operation"):
            management.apply_plan("a" * 32, "alice", "")
    finally:
        management._transaction_lock.release()


def test_mutating_routes_require_csrf_dependency_and_domain_permissions():
    routes = {(method, route.path): route for route in management.router.routes for method in route.methods}
    assert ("GET", "/api/admin/network/management") in routes
    assert ("POST", "/api/admin/network/plans") in routes
    assert ("POST", "/api/admin/network/apply") in routes
    assert ("POST", "/api/admin/network/confirm") in routes
    assert ("POST", "/api/admin/network/rollback") in routes
    assert ("GET", "/api/admin/network/transactions/active") in routes
    assert ("GET", "/api/admin/network/transactions/{transaction_id}/status") in routes
    assert ("POST", "/api/admin/network/transactions/{transaction_id}/confirm") in routes
    assert ("POST", "/api/admin/network/transactions/{transaction_id}/rollback") in routes
    assert ("GET", "/api/admin/network/policy") in routes
    assert ("PUT", "/api/admin/network/policy") in routes
    assert ("POST", "/api/admin/network/policy/reset") in routes
    assert management._permission_for(management.NetworkChange(operation="save_dns", dns=management.DnsSettings())) == management.Permission.NETWORK_DNS


def test_systemd_rollback_timer_is_exactly_fifteen_seconds(monkeypatch):
    calls = []
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        management,
        "_run_command",
        lambda command, timeout=0: calls.append(command) or subprocess.CompletedProcess(command, 0, "", ""),
    )
    transaction_id = "a" * 32
    assert management._schedule_rollback(transaction_id, management.DEFAULT_CONFIRMATION_TIMEOUT_SECONDS) == f"webnas-network-rollback-{transaction_id}.service"
    assert "--on-active=15s" in calls[0]
    assert calls[0][-3:] == ["app.network_management", "--rollback", transaction_id]


def test_network_policy_defaults_validates_strict_bounds_and_persists():
    assert management.read_network_policy().change_confirmation_timeout_seconds == 15
    management.write_network_policy(management.NetworkPolicy(change_confirmation_timeout_seconds=45))
    assert management.read_network_policy().change_confirmation_timeout_seconds == 45
    for value in (0, -1, 4, 301, 1.5, "15"):
        with pytest.raises(ValidationError):
            management.NetworkPolicyUpdate.model_validate({"change_confirmation_timeout_seconds": value, "confirm": True})
    with pytest.raises(ValidationError):
        management.NetworkPolicyUpdate.model_validate({"confirm": True})
    with pytest.raises(ValidationError):
        management.NetworkPolicyUpdate.model_validate({"change_confirmation_timeout_seconds": 15, "confirm": True, "unknown": True})


def test_network_policy_update_requires_permission_and_is_audited(monkeypatch):
    checks = []
    events = []
    monkeypatch.setattr(management, "authorize", lambda user, permission: checks.append(permission))
    monkeypatch.setattr(management, "record_activity", lambda *args, **kwargs: events.append((args, kwargs)))
    user = SimpleNamespace(username="admin")
    result = management.update_network_policy_endpoint(
        management.NetworkPolicyUpdate(change_confirmation_timeout_seconds=60, confirm=True),
        user,
    )
    assert result["change_confirmation_timeout_seconds"] == 60
    assert checks == [management.Permission.NETWORK_POLICY_EDIT]
    assert events[0][1]["details"]["old_value"] == 15
    assert events[0][1]["details"]["new_value"] == 60


def test_network_policy_update_is_denied_without_permission(monkeypatch):
    monkeypatch.setattr(management, "authorize", lambda user, permission: (_ for _ in ()).throw(HTTPException(403, "Forbidden")))
    with pytest.raises(HTTPException) as error:
        management.update_network_policy_endpoint(
            management.NetworkPolicyUpdate(change_confirmation_timeout_seconds=60, confirm=True),
            SimpleNamespace(username="user"),
        )
    assert error.value.status_code == 403
    assert management.read_network_policy().change_confirmation_timeout_seconds == 15


def test_network_policy_can_be_reset_to_default(monkeypatch):
    monkeypatch.setattr(management, "authorize", lambda user, permission: None)
    management.write_network_policy(management.NetworkPolicy(change_confirmation_timeout_seconds=120))
    result = management.reset_network_policy_endpoint(management.PolicyResetRequest(confirm=True), SimpleNamespace(username="admin"))
    assert result["change_confirmation_timeout_seconds"] == 15
    assert management.read_network_policy().change_confirmation_timeout_seconds == 15


def test_network_policy_mutation_dependency_enforces_csrf(monkeypatch):
    user = SimpleNamespace(username="admin")
    checked = []
    monkeypatch.setattr(management, "get_session_user", lambda request: user)
    monkeypatch.setattr(management, "require_csrf", lambda request, current: checked.append(current.username))
    request = Request({"type": "http", "method": "PUT", "path": "/api/admin/network/policy", "headers": [], "client": ("127.0.0.1", 1)})
    assert management._mutating_user(request) is user
    assert checked == ["admin"]


def test_new_transactions_use_current_policy_without_changing_active_deadline(monkeypatch):
    clock = {"now": 2_000.0}
    scheduled = []
    monkeypatch.setattr(management.time, "time", lambda: clock["now"])
    monkeypatch.setattr(management, "detect_provider", lambda: (management.NetworkManagerProvider(), []))
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": []})
    monkeypatch.setattr(management, "routing_snapshot", lambda: {"gateways": []})
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(management, "_run_command", lambda command, timeout=0: subprocess.CompletedProcess(command, 0, "", ""))
    monkeypatch.setattr(management, "_schedule_rollback", lambda transaction_id, seconds: scheduled.append(seconds) or f"webnas-network-rollback-{transaction_id}.service")
    management.write_network_policy(management.NetworkPolicy(change_confirmation_timeout_seconds=30))
    plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface()), "alice", None)
    assert plan["confirmation_timeout_seconds"] == 30
    active = management.apply_plan(plan["id"], "alice", "")
    assert active["confirmation_timeout_seconds"] == 30
    assert active["deadline_at"] - active["created_at"] == 30
    assert scheduled == [30]

    management.write_network_policy(management.NetworkPolicy(change_confirmation_timeout_seconds=90))
    persisted = management.transaction_status(active["id"])
    assert persisted["confirmation_timeout_seconds"] == 30
    assert persisted["deadline_at"] == active["deadline_at"]


def test_apply_payload_cannot_override_policy_timeout():
    with pytest.raises(ValidationError):
        management.ApplyRequest.model_validate({
            "plan_id": "a" * 32,
            "confirmation_timeout_seconds": 300,
        })


def test_rollback_is_armed_before_network_commands(monkeypatch):
    events = []
    monkeypatch.setattr(management, "detect_provider", lambda: (management.NetworkManagerProvider(), []))
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": []})
    monkeypatch.setattr(management, "routing_snapshot", lambda: {"gateways": []})
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        management,
        "_schedule_rollback",
        lambda transaction_id, seconds: events.append("timer") or f"webnas-network-rollback-{transaction_id}.service",
    )
    monkeypatch.setattr(
        management,
        "_run_command",
        lambda command, timeout=0: events.append("apply" if "connection" in command and "delete" in command else "snapshot") or subprocess.CompletedProcess(command, 0, "", ""),
    )
    plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface()), "alice", None)
    transaction = management.apply_plan(plan["id"], "alice", "")
    assert events.index("timer") < events.index("apply")
    assert (management._state_root() / "transactions" / transaction["id"] / "snapshot.json").exists()


def test_confirmation_is_idempotent_and_rejected_after_deadline(monkeypatch):
    clock = {"now": 1_000.0}
    monkeypatch.setattr(management.time, "time", lambda: clock["now"])
    monkeypatch.setattr(management, "detect_provider", lambda: (management.NetworkManagerProvider(), []))
    monkeypatch.setattr(management, "network_overview", lambda: {"interfaces": []})
    monkeypatch.setattr(management, "routing_snapshot", lambda: {"gateways": []})
    monkeypatch.setattr(management.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(management, "_run_command", lambda command, timeout=0: subprocess.CompletedProcess(command, 0, "", ""))
    monkeypatch.setattr(management, "_schedule_rollback", lambda transaction_id, seconds: f"webnas-network-rollback-{transaction_id}.service")
    plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface()), "alice", None)
    pending = management.apply_plan(plan["id"], "alice", "")
    confirmed = management.confirm_transaction(pending["id"], "alice")
    assert management.confirm_transaction(pending["id"], "alice") == confirmed

    next_plan = management.build_plan(management.NetworkChange(operation="save_interface", interface=interface(mtu=1400)), "alice", None)
    expired = management.apply_plan(next_plan["id"], "alice", "")
    clock["now"] = expired["deadline"]
    with pytest.raises(HTTPException, match="expired"):
        management.confirm_transaction(expired["id"], "alice")
    assert management._active_transaction()["id"] == expired["id"]


def test_transaction_status_survives_service_restart_and_reports_rollback(monkeypatch):
    transaction_id = "c" * 32
    directory = management._state_root() / "transactions" / transaction_id
    directory.mkdir(parents=True)
    management._atomic_json(directory / "snapshot.json", {"state": {"interfaces": {}, "dns": None, "routes": {}, "traffic": {}}, "files": {}})
    management._atomic_json(directory / "transaction.json", {
        "id": transaction_id, "state": "pending_confirmation", "provider": "networkmanager",
        "started_at": 100.0, "deadline": 115.0, "rollback_unit": "rollback.service", "target": "eth0",
        "reachable_addresses": ["https://192.0.2.10"],
    })
    management._atomic_json(management._state_root() / "active.json", management._read_json(directory / "transaction.json", {}))
    monkeypatch.setattr(management.time, "time", lambda: 116.0)
    status = management.transaction_status(transaction_id)
    assert status["status"] == "rollback_pending"
    assert status["remaining_seconds"] == 0
    assert status["reachable_addresses"] == ["https://192.0.2.10"]

    monkeypatch.setattr(management.shutil, "which", lambda name: None)
    monkeypatch.setattr(management, "_run_command", lambda command, timeout=0: subprocess.CompletedProcess(command, 0, "", ""))
    assert management.rollback_transaction(transaction_id, automatic=True)["state"] == "rolled_back"
    assert management.transaction_status(transaction_id)["rolled_back"] is True
