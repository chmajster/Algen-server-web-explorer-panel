"""Supported cross-module API for the Proxmox Manager provider."""

from __future__ import annotations

from typing import Any

from .service import ProxmoxApiClient, ProxmoxApiError, ProxmoxManagerService, service


def active_connections() -> list[dict[str, Any]]:
    return service().connections(active_only=True)


def api_client(connection_id: str) -> ProxmoxApiClient:
    manager = service()
    connection = manager.connection(connection_id)
    if not connection or not connection.get("active"):
        raise KeyError("Proxmox connection not found")
    return manager._client(connection)


__all__ = ["ProxmoxApiClient", "ProxmoxApiError", "ProxmoxManagerService", "active_connections", "api_client", "service"]
