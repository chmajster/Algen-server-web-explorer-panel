from __future__ import annotations

import time
from pathlib import Path

from app.modules.hosts_manager.models import (
    AgentReportInput,
    CredentialInput,
    CredentialType,
    GroupInput,
    HostInput,
)
from app.modules.hosts_manager.service import HostRegistryService


def service(tmp_path: Path) -> HostRegistryService:
    return HostRegistryService(
        tmp_path / "hosts-manager" / "hosts.sqlite3",
        tmp_path / "secrets" / "hosts-manager.key",
        tmp_path / "missing.sqlite3",
    )


def test_batch_enrichment_preserves_host_contract_and_redacts_secrets(tmp_path: Path) -> None:
    store = service(tmp_path)
    credential = store.save_credential(
        CredentialInput(
            name="Batch SSH",
            type=CredentialType.ssh_password,
            username="ops",
            secret="batch-secret",
        ),
        "admin",
    )
    group = store.save_group(GroupInput(name="Batch group"), "admin")
    host = store.save_host(
        HostInput(
            name="batch-node",
            address="10.40.0.10",
            approved=True,
            environment="default",
            credential_id=credential["id"],
            group_ids=[group["id"]],
        ),
        "admin",
    )

    store.save_facts(
        host["id"],
        {"distribution": "Ubuntu", "distribution_version": "24.04"},
        "agent",
    )
    store.save_facts(
        host["id"],
        {"distribution": "Debian", "distribution_version": "13"},
        "agent",
    )

    paired = store.register_agent(host["id"], "batch-installation", "1.2.0", 8443, 300, "admin")
    assert store.agent_heartbeat(
        paired["agent_id"],
        paired["token"],
        {"agent_version": "1.2.1", "status": "online", "error": ""},
    )
    report = AgentReportInput(
        agent_id=paired["agent_id"],
        basic={"distribution": "Rocky Linux", "system_version": "9.6"},
        packages={"available_updates_count": 7, "security_updates_count": 3},
    )
    assert store.save_agent_report(
        paired["agent_id"],
        paired["token"],
        report.model_dump(exclude={"agent_id"}),
    )

    with store.connect() as connection:
        connection.execute(
            "UPDATE host_agents SET status='online',last_heartbeat_at=?,updated_at=? WHERE host_id=?",
            (time.time() - 300, time.time(), host["id"]),
        )

    listed = next(item for item in store.list_hosts() if item["id"] == host["id"])
    single = store.host(host["id"])

    assert single is not None
    assert listed["groups"] == [{"id": group["id"], "name": "Batch group"}]
    assert listed["group_ids"] == [group["id"]]
    assert listed["facts"]["distribution"] == "Debian"
    assert listed["agent_status"] == "offline"
    assert listed["connection_status"] == "offline"
    assert "token_hash" not in listed["agent"]
    assert listed["identity"] is not None and "salt" not in listed["identity"]
    assert listed["environment_details"]["id"] == "default"
    assert listed["distribution"] == "Rocky Linux"
    assert listed["system_version"] == "9.6"
    assert listed["available_updates"] == 7
    assert listed["security_updates"] == 3
    assert listed["credential"]["id"] == credential["id"]
    assert listed["credential"]["secret_configured"] is True
    assert "encrypted_secret" not in listed["credential"]
    assert "secret" not in listed["credential"]
    assert single["latest_report"] == listed["latest_report"]
    assert single["agent_status"] == listed["agent_status"]


def test_list_hosts_query_count_is_bounded_for_one_hundred_hosts(monkeypatch, tmp_path: Path) -> None:
    store = service(tmp_path)
    for index in range(100):
        store.save_host(
            HostInput(
                name=f"query-node-{index:03d}",
                address=f"10.41.{index // 250}.{index % 250 + 1}",
                approved=True,
                environment="default",
            ),
            "admin",
        )

    statements: list[str] = []
    original_connect = store.connect

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "connect", traced_connect)
    hosts = store.list_hosts(limit=100)

    reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    assert len(hosts) == 100
    assert len(reads) <= 9, "host enrichment query count must stay independent of page size"
