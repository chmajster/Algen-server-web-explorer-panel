from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.dcst.models import IPSetInput, PortInput, ServiceInput
from app.modules.dcst.provider import ProviderContext, ProxmoxFirewallProvider, provider_name
from app.modules.dcst.repository import DcstRepository
from app.modules.dcst.service import DcstConflict, DcstService


class FakeProvider:
    def __init__(self) -> None:
        self.applied_ipsets: list[dict[str, Any]] = []
        self.applied_services: list[dict[str, Any]] = []
        self.deleted_services: list[str] = []
        self.context = SimpleNamespace(connection={"id": "pve-1", "name": "PVE"})

    def contexts(self):
        return [self.context]

    def status(self):
        return {"ok": True, "connections": [{"id": "pve-1", "ok": True, "enabled": True, "rules": len(self.applied_services), "ipsets": len(self.applied_ipsets)}]}

    def test(self):
        return {"ok": True, "connections": [{"checks": {"api": True, "authentication": True, "firewall": True, "ipsets": True, "rules": True, "logs": True}}]}

    def firewall_logs(self, limit=200):
        return [{"node": "pve1", "t": "policy IN=vmbr0 OUT=fwbr100i0 ACTION=ACCEPT"}][:limit]

    def apply_ipset(self, context, item, *, dry_run=False):
        if not dry_run:
            self.applied_ipsets.append(item)
        return {"object": "ipset", "id": item["id"], "state": "NO_CHANGE" if not dry_run else "CREATE", "operations": [] if not dry_run else [{"operation": "CREATE"}], "applied": not dry_run}

    def apply_service(self, context, item, ports, ipsets, apmid_tags, *, dry_run=False):
        if not dry_run:
            self.applied_services.append(item)
        return {"object": "service", "id": item["id"], "state": "NO_CHANGE" if not dry_run else "CREATE", "operations": [], "verified": not dry_run}

    def delete_service_rules(self, context, service_id, *, dry_run=False):
        if not dry_run:
            self.deleted_services.append(service_id)
        return {"id": service_id, "operations": [], "applied": not dry_run}


@pytest.fixture
def repo(tmp_path: Path):
    return DcstRepository(tmp_path / "dcst.sqlite3")


@pytest.fixture
def inventory():
    return [
        {
            "apmid": "IAASTEA", "environment": "PROD", "hosts": [
                {"id": "vm-1", "name": "vm-app-01", "address": "10.10.20.10", "present": True},
                {"id": "vm-2", "name": "vm-app-02", "address": "10.10.20.11", "present": True},
            ],
        },
        {
            "apmid": "IAASTEA", "environment": "TEST", "hosts": [
                {"id": "vm-3", "name": "vm-test-01", "address": "10.10.30.10", "present": True},
            ],
        },
    ]


def make_service(repo: DcstRepository, inventory):
    return DcstService(repo, FakeProvider(), lambda: inventory)


def test_port_validation():
    assert PortInput(name="HTTPS", protocol="tcp", port_from=443).port_to == 443
    assert PortInput(name="DNS", protocol="udp", port_from=53, port_to=53).port_from == 53
    assert PortInput(name="ICMP", protocol="icmp").port_from is None
    with pytest.raises(ValidationError):
        PortInput(name="invalid", protocol="tcp", port_from=65536)
    with pytest.raises(ValidationError):
        PortInput(name="range", protocol="tcp", port_from=9000, port_to=8000)


def test_ipset_normalizes_and_deduplicates():
    value = IPSetInput(name="CORPORATE_DNS", entries=["10.20.0.10", "10.20.0.10/32", "2001:db8::1"])
    assert value.entries == ["10.20.0.10/32", "2001:db8::1/128"]
    with pytest.raises(ValidationError):
        IPSetInput(name="bad", entries=["999.1.1.1"])


def test_inventory_sync_creates_dynamic_tags_ipsets_and_default_service(repo, inventory):
    dcst = make_service(repo, inventory)
    first = dcst.sync_inventory("alice")
    second = dcst.sync_inventory("alice")

    tags = repo.tags()
    assert [item["name"] for item in tags] == ["IAASTEA.PROD", "IAASTEA.TEST"]
    prod = next(item for item in repo.ipsets() if item["name"] == "IAASTEA.PROD")
    assert prod["type"] == "dynamic"
    assert [entry["address"] for entry in prod["entries"]] == ["10.10.20.10/32", "10.10.20.11/32"]
    system = [item for item in repo.services() if item["system_service"]]
    assert len(system) == 1
    assert system[0]["name"] == "SYSTEM_IAASTEA_INTERNAL"
    assert system[0]["source_type"] == "apmid"
    assert system[0]["destination_type"] == "apmid"
    assert first["tags"] == second["tags"] == 2


def test_vm_delete_ip_change_and_environment_move_reconcile_without_duplicates(repo, inventory):
    dcst = make_service(repo, inventory)
    dcst.sync_inventory("alice")
    inventory[0]["hosts"] = [{"id": "vm-1", "name": "vm-app-01", "address": "10.10.20.99", "present": True}]
    inventory[1]["hosts"].append({"id": "vm-2", "name": "vm-app-02", "address": "10.10.20.11", "present": True})
    dcst.sync_inventory("alice")
    dcst.sync_inventory("alice")

    prod = next(item for item in repo.ipsets() if item["name"] == "IAASTEA.PROD")
    test = next(item for item in repo.ipsets() if item["name"] == "IAASTEA.TEST")
    assert [entry["address"] for entry in prod["entries"]] == ["10.10.20.99/32"]
    assert sorted(entry["address"] for entry in test["entries"]) == ["10.10.20.11/32", "10.10.30.10/32"]
    assert len(repo.tags()) == 2
    assert len([item for item in repo.services() if item["system_service"]]) == 1


def test_manual_ipset_crud_and_dependencies(repo, inventory):
    dcst = make_service(repo, inventory)
    dcst.sync_inventory("alice")
    ipset = dcst.save_ipset(IPSetInput(name="CORPORATE_DNS", entries=["10.20.0.10", "10.20.0.11"]), "alice")
    service = ServiceInput(
        name="APP_TO_DNS", direction="OUT", action="ACCEPT", source_type="tag", source_value="IAASTEA.PROD",
        destination_type="ipset", destination_value=ipset["id"], port_ids=[], enabled=True,
    )
    dcst.save_service(service, "alice")
    with pytest.raises(DcstConflict):
        dcst.delete_ipset(ipset["id"], "alice")


def test_service_multiple_ports_block_unblock_and_bulk(repo, inventory):
    dcst = make_service(repo, inventory)
    dcst.sync_inventory("alice")
    https = dcst.save_port(PortInput(name="HTTPS", protocol="tcp", port_from=443), "alice")
    http = dcst.save_port(PortInput(name="HTTP", protocol="tcp", port_from=80), "alice")
    payload = ServiceInput(
        name="IAASTEA_TO_WEB", direction="OUT", action="ACCEPT", source_type="tag", source_value="IAASTEA.PROD",
        destination_type="tag", destination_value="IAASTEA.TEST", port_ids=[https["id"], http["id"]], enabled=True,
    )
    item = dcst.save_service(payload, "alice")
    assert item["port_ids"] == [http["id"], https["id"]] or set(item["port_ids"]) == {http["id"], https["id"]}
    blocked = dcst.change_service_state(item["id"], "alice", "block", apply=False)["service"]
    assert blocked["state"] == "BLOCKED"
    assert dcst.change_service_state(item["id"], "alice", "unblock", apply=False)["service"]["state"] == "ACTIVE"
    result = dcst.bulk([item["id"], item["id"]], "alice", "disable")
    assert result["total"] == 1
    assert repo.service(item["id"])["state"] == "DISABLED"


def test_reconciliation_dry_run_apply_and_drift(repo, inventory):
    dcst = make_service(repo, inventory)
    dcst.sync_inventory("alice")
    https = dcst.save_port(PortInput(name="HTTPS", protocol="tcp", port_from=443), "alice")
    item = dcst.save_service(ServiceInput(name="PROD_TO_TEST", direction="OUT", source_type="tag", source_value="IAASTEA.PROD", destination_type="tag", destination_value="IAASTEA.TEST", port_ids=[https["id"]]), "alice")
    dry = dcst.sync_service(item["id"], "alice", dry_run=True)
    assert dry["dry_run"] is True
    applied = dcst.sync_service(item["id"], "alice")
    assert applied["results"][0]["state"] == "NO_CHANGE"
    assert repo.service(item["id"])["sync_status"] == "SYNCED"
    drift = dcst.drift("alice")
    assert drift["state"] in {"DRIFT", "SYNCED"}


def test_provider_preserves_external_rules_and_generates_direction_ports():
    class Client:
        def __init__(self):
            self.rules = [{"pos": 0, "type": "in", "action": "ACCEPT", "comment": "external-rule"}]

        def get(self, path):
            if path == "cluster/firewall/rules":
                return list(self.rules)
            if path == "cluster/firewall/ipset":
                return []
            return []

        def post(self, path, data=None):
            if path == "cluster/firewall/rules":
                self.rules.append(dict(data or {}) | {"pos": len(self.rules)})

        def request(self, method, path, data=None):
            if method == "DELETE" and "cluster/firewall/rules/" in path:
                position = int(path.rsplit("/", 1)[1])
                self.rules = [row for row in self.rules if int(row.get("pos", -1)) != position]
                for index, row in enumerate(self.rules):
                    row["pos"] = index

        def put(self, path, data=None):
            return None

    provider = ProxmoxFirewallProvider()
    client = Client()
    ctx = ProviderContext({"id": "pve", "name": "PVE"}, client)  # type: ignore[arg-type]
    service = {"id": "svc", "name": "HTTPS", "direction": "OUT", "action": "ACCEPT", "source_type": "tag", "source_value": "APP.PROD", "destination_type": "cidr", "destination_value": "10.20.0.0/24", "port_ids": ["https"], "enabled": True, "blocked": False, "logging": True}
    ipset = {"id": "tag", "provider_name": provider_name("APP.PROD"), "name": "APP.PROD", "entries": []}
    port = {"id": "https", "protocol": "tcp", "port_from": 443, "port_to": 443}
    desired = provider.desired_rules(service, {"https": port}, {"APP.PROD": ipset}, {})
    assert desired[0]["type"] == "out"
    assert desired[0]["dport"] == "443"
    provider.apply_service(ctx, service, {"https": port}, {"APP.PROD": ipset}, {})
    assert any(row.get("comment") == "external-rule" for row in client.rules)
    assert any(str(row.get("comment", "")).startswith("DCST:svc:") for row in client.rules)


def test_drop_any_to_any_requires_high_risk_confirmation(repo, inventory):
    dcst = make_service(repo, inventory)
    dcst.sync_inventory("alice")
    item = dcst.save_service(ServiceInput(name="BLOCK_ALL", direction="OUT", action="DROP", source_type="any", destination_type="any"), "alice")
    with pytest.raises(Exception, match="high-risk confirmation"):
        dcst.sync_service(item["id"], "alice")
    assert dcst.sync_service(item["id"], "alice", dry_run=True, confirm_high_risk=True)["dry_run"] is True
