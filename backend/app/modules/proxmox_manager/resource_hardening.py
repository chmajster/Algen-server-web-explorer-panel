from __future__ import annotations

import math
from typing import Any

from .service import ProxmoxApiClient, ProxmoxManagerService


def _safe_int(value: Any, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= minimum else None


def _safe_float(value: Any, *, minimum: float = 0.0) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= minimum else None


def _safe_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def install_resource_hardening() -> None:
    if getattr(ProxmoxManagerService, "_runtime_audit_11_resource_hardening", False):
        return

    def _resources(
        self: ProxmoxManagerService,
        connection: dict[str, Any],
        client: ProxmoxApiClient | None = None,
    ) -> list[dict[str, Any]]:
        selected = client or self._client(connection)
        raw = selected.get("cluster/resources?type=vm")
        if not isinstance(raw, list):
            return []

        resources: list[dict[str, Any]] = []
        for value in raw:
            if not isinstance(value, dict):
                continue
            resource_type = self._resource_type(value)
            if not resource_type:
                continue
            if resource_type == "lxc" and not connection["sync_lxc"]:
                continue

            vmid = _safe_int(value.get("vmid"), minimum=1)
            node = value.get("node")
            if vmid is None or not isinstance(node, str) or not node.strip():
                continue
            node = node.strip()

            template = _safe_flag(value.get("template"))
            if template and not connection["sync_templates"]:
                continue

            uptime = _safe_int(value.get("uptime"), minimum=0) or 0
            maxcpu = _safe_int(value.get("maxcpu"), minimum=0) or 0
            mem = _safe_int(value.get("mem"), minimum=0) or 0
            maxmem = _safe_int(value.get("maxmem"), minimum=0) or 0
            disk = _safe_int(value.get("disk"), minimum=0) or 0
            maxdisk = _safe_int(value.get("maxdisk"), minimum=0) or 0
            cpu = _safe_float(value.get("cpu"), minimum=0.0) or 0.0

            name_value = value.get("name")
            name = name_value.strip() if isinstance(name_value, str) else ""
            resources.append(
                {
                    "vmid": vmid,
                    "name": name or f"{resource_type}-{vmid}",
                    "node": node,
                    "type": resource_type,
                    "status": str(value.get("status") or "unknown"),
                    "template": template,
                    "uptime": uptime,
                    "cpu": cpu,
                    "maxcpu": maxcpu,
                    "mem": mem,
                    "maxmem": maxmem,
                    "disk": disk,
                    "maxdisk": maxdisk,
                    "tags": self._parse_proxmox_tags(value.get("tags")),
                }
            )
        return sorted(resources, key=lambda row: (row["node"], row["vmid"]))

    ProxmoxManagerService._resources = _resources  # type: ignore[method-assign]
    setattr(ProxmoxManagerService, "_runtime_audit_11_resource_hardening", True)
