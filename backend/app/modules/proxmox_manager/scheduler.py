from __future__ import annotations

import logging
import threading
import time
import urllib.parse
from typing import Any

from ...package_center.service import repository as package_repository
from ..hosts_manager.public import provider_hosts as shared_provider_hosts
from .service import PROVIDER, ProxmoxApiError, ProxmoxManagerService, service


logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 60
_started = False
_lock = threading.Lock()


def _tag_context(connection: dict[str, Any], host: dict[str, Any] | None) -> dict[str, Any]:
    if host:
        return host
    project = str(connection.get("project") or "")
    return {
        "environment": str(connection.get("environment") or ""),
        "location": str(connection.get("location") or ""),
        "tags": list(connection.get("tags") or []),
        "variables": {"algen_project": project} if project else {},
    }


def _resource_identity(connection_id: str, resource: dict[str, Any]) -> tuple[str, str]:
    return connection_id, str(resource["vmid"])


def sync_connection_tags(
    manager: ProxmoxManagerService,
    connection: dict[str, Any],
) -> dict[str, Any]:
    """Push Algen metadata tags without requiring a guest IP or QEMU Guest Agent."""
    if not connection.get("active") or not connection.get("sync_proxmox_tags", True):
        return {"connection_id": str(connection.get("id") or ""), "checked": 0, "updated": 0, "errors": []}

    connection_id = str(connection["id"])
    client = manager._client(connection)
    resources = manager._resources(connection, client)
    hosts = {
        identity: host
        for host in shared_provider_hosts(PROVIDER, connection_id)
        if (identity := manager._host_identity(host)) is not None
    }

    updated = 0
    errors: list[dict[str, Any]] = []
    for resource in resources:
        try:
            existing = hosts.get(_resource_identity(connection_id, resource))
            host = _tag_context(connection, existing)
            current = manager._parse_proxmox_tags(resource.get("tags"))
            previous_variables = dict(existing.get("variables") or {}) if existing else {}
            previous_managed = set(manager._parse_proxmox_tags(previous_variables.get("proxmox_managed_tags")))
            desired = manager._managed_proxmox_tags(connection, resource, host)
            unmanaged = [tag for tag in current if tag not in previous_managed]
            final = list(dict.fromkeys([*unmanaged, *desired]))
            if set(final) == set(current):
                continue

            node = urllib.parse.quote(str(resource["node"]), safe="")
            path = f"nodes/{node}/{resource['type']}/{int(resource['vmid'])}/config"
            client.put(path, {"tags": ";".join(final)})
            updated += 1
        except (KeyError, TypeError, ValueError, ProxmoxApiError) as error:
            errors.append(
                {
                    "vmid": resource.get("vmid"),
                    "name": resource.get("name"),
                    "error": str(error)[:500],
                }
            )

    return {
        "connection_id": connection_id,
        "checked": len(resources),
        "updated": updated,
        "errors": errors,
    }


def scheduler_tick() -> int:
    if "proxmox-manager" not in package_repository().installed():
        return 0

    manager = service()
    updated = 0
    for connection in manager.connections(active_only=True):
        if not connection.get("sync_proxmox_tags", True):
            continue
        try:
            result = sync_connection_tags(manager, connection)
            updated += int(result["updated"])
            if result["errors"]:
                logger.warning(
                    "proxmox_auto_tag_completed_with_errors connection=%s errors=%s",
                    connection["id"],
                    len(result["errors"]),
                )
        except (KeyError, ValueError, ProxmoxApiError):
            logger.exception("proxmox_auto_tag_failed connection=%s", connection.get("id"))
    return updated


def _loop() -> None:
    while True:
        try:
            scheduler_tick()
        except Exception:  # noqa: BLE001 - scheduler must survive one failed cycle
            logger.exception("proxmox_auto_tag_scheduler_tick_failed")
        time.sleep(POLL_INTERVAL_SECONDS)


def start_scheduler() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_loop, daemon=True, name="proxmox-auto-tag-scheduler").start()
