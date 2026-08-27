"""DATA Communication & Segmentation Tool (DCST)."""

from __future__ import annotations

from typing import Any

from ...core.events import bus
from .service import DcstService, service


_instance = service()


def _apply_inventory_change(payload: dict[str, Any]) -> None:
    """Apply already-refreshed dynamic IPSets and dependent Services after Proxmox sync."""
    actor = str(payload.get("actor") or "system")
    result = _instance.sync_all(actor, refresh_inventory=False)
    if result.get("errors"):
        _instance.repository.set_state("last_inventory_apply_error", {"actor": actor, "errors": result["errors"]})


_event_unsubscribe = bus.subscribe("PROXMOX_INVENTORY_CHANGED", _apply_inventory_change)

__all__ = ["DcstService", "service"]
