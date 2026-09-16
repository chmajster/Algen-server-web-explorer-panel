from __future__ import annotations

import json
import time
from pathlib import Path

from app.modules.hosts_manager.batch_enrichment import HostRegistryService
from app.modules.hosts_manager.models import HostInput


def _hosts_service(tmp_path: Path) -> HostRegistryService:
    return HostRegistryService(
        tmp_path / "hosts" / "hosts.sqlite3",
        tmp_path / "secrets" / "hosts.key",
        tmp_path / "missing-controller.sqlite3",
    )


def test_corrupted_agent_report_metrics_do_not_break_host_enrichment(tmp_path: Path) -> None:
    store = _hosts_service(tmp_path)
    host = store.save_host(
        HostInput(name="corrupt-report-node", address="10.70.0.10", approved=True, environment="default"),
        "admin",
    )
    paired = store.register_agent(host["id"], "audit-installation", "1.0.0", 8443, 300, "admin")
    assert store.save_agent_report(
        paired["agent_id"],
        paired["token"],
        {"basic": {"distribution": "Debian", "system_version": "13"}, "packages": {"available_updates_count": 1, "security_updates_count": 1}},
    )

    with store.connect() as connection:
        connection.execute(
            "UPDATE host_reports SET report_json=? WHERE host_id=?",
            (
                json.dumps(
                    {
                        "basic": ["wrong-shape"],
                        "packages": {
                            "available_updates_count": "unknown",
                            "security_updates_count": {"bad": True},
                        },
                    }
                ),
                host["id"],
            ),
        )
        connection.execute(
            "UPDATE host_agents SET last_heartbeat_at=?,updated_at=? WHERE host_id=?",
            ("nan", time.time(), host["id"]),
        )

    enriched = store.host(host["id"])

    assert enriched is not None
    assert enriched["available_updates"] == 0
    assert enriched["security_updates"] == 0
    assert enriched["distribution"] == ""
    assert enriched["system_version"] == ""
    assert enriched["agent_status"] in {"online", "warning", "error", "offline"}


def test_negative_and_non_finite_report_metrics_degrade_to_zero(tmp_path: Path) -> None:
    store = _hosts_service(tmp_path)
    host = store.save_host(
        HostInput(name="negative-report-node", address="10.70.0.11", approved=True, environment="default"),
        "admin",
    )
    paired = store.register_agent(host["id"], "audit-installation-2", "1.0.0", 8443, 300, "admin")
    assert store.save_agent_report(
        paired["agent_id"],
        paired["token"],
        {"packages": {"available_updates_count": 0, "security_updates_count": 0}},
    )
    with store.connect() as connection:
        connection.execute(
            "UPDATE host_reports SET report_json=? WHERE host_id=?",
            (json.dumps({"packages": {"available_updates_count": -9, "security_updates_count": "nan"}}), host["id"]),
        )

    enriched = store.host(host["id"])
    assert enriched is not None
    assert enriched["available_updates"] == 0
    assert enriched["security_updates"] == 0
