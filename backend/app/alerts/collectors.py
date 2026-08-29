from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..core.modules import ModuleRegistry
from ..core.redaction import redact_text
from ..modules.hosts_manager import registry as hosts_registry
from .models import AlertEvent, AlertSeverity
from .service import service


logger = logging.getLogger(__name__)
COLLECT_INTERVAL_SECONDS = 60
_BAD_MODULE_STATES = {"broken", "unavailable", "degraded", "failed"}
_BAD_HOST_STATES = {"offline", "error", "unreachable", "stale"}


def _state(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").casefold()


async def collect_module_health(registry: ModuleRegistry) -> int:
    manager = service()
    changed = 0
    diagnostics = await registry.health()
    for item in diagnostics:
        module_id = str(item.get("module_id") or "")
        if not module_id:
            continue
        state = _state(item.get("state"))
        if state in _BAD_MODULE_STATES:
            severity = AlertSeverity.critical if state in {"broken", "failed"} else AlertSeverity.error
            manager.fire(
                AlertEvent(
                    source="module.health",
                    key=module_id,
                    title=f"Module health is {state}: {module_id}",
                    object_ref=module_id,
                    severity=severity,
                    details={
                        "module_id": module_id,
                        "state": state,
                        "message": redact_text(item.get("message", ""), limit=2000),
                    },
                )
            )
            changed += 1
        elif state in {"active", "disabled"}:
            changed += len(manager.resolve("module.health", module_id, "system"))
    return changed


def collect_host_health() -> int:
    manager = service()
    changed = 0
    for host in hosts_registry().list_hosts(active_only=True, limit=5000):
        host_id = str(host.get("id") or "")
        if not host_id:
            continue
        agent_status = _state(host.get("agent_status"))
        connection_status = _state(host.get("connection_status"))
        status = _state(host.get("status"))
        effective = next(
            (value for value in (agent_status, connection_status, status) if value in _BAD_HOST_STATES),
            "",
        )
        if effective:
            agent = host.get("agent") if isinstance(host.get("agent"), dict) else {}
            manager.fire(
                AlertEvent(
                    source="host.offline",
                    key=host_id,
                    title=f"Host is {effective}: {host.get('name') or host_id}",
                    object_ref=host_id,
                    severity=AlertSeverity.error if effective == "error" else AlertSeverity.warning,
                    details={
                        "host_id": host_id,
                        "name": str(host.get("name") or ""),
                        "address": str(host.get("address") or ""),
                        "status": status,
                        "connection_status": connection_status,
                        "agent_status": agent_status,
                        "last_heartbeat_at": agent.get("last_heartbeat_at"),
                    },
                )
            )
            changed += 1
        elif status not in {"disabled", "pending"}:
            changed += len(manager.resolve("host.offline", host_id, "system"))
    return changed


async def collector_tick(registry: ModuleRegistry) -> dict[str, int]:
    module_changes = await collect_module_health(registry)
    host_changes = collect_host_health()
    return {"module_changes": module_changes, "host_changes": host_changes}


async def collector_loop(registry: ModuleRegistry) -> None:
    while True:
        try:
            await collector_tick(registry)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one provider failure cannot stop alert collection
            logger.exception("alert_collector_tick_failed")
        await asyncio.sleep(COLLECT_INTERVAL_SECONDS)
