"""Shared network-oriented projection of the canonical Hosts Manager inventory."""

from __future__ import annotations

import json
from typing import Any

from .public import registry


def _variables(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def network_inventory(*, provider: str = "proxmox") -> list[dict[str, Any]]:
    """Return APMID/ENV groups and their canonical hosts without copying inventory.

    Managed APMID/ENV memberships are authoritative. Provider metadata is used as a
    compatibility fallback for Proxmox hosts created before managed group assignment.
    """
    service = registry()
    with service.connect() as connection:
        group_rows = connection.execute(
            """
            SELECT aeg.apmid_id,a.code AS apmid,e.id AS environment_id,e.name AS environment,
                   e.slug AS environment_slug,aeg.group_id
            FROM apmid_environment_groups aeg
            JOIN apmids a ON a.id=aeg.apmid_id
            JOIN environments e ON e.id=aeg.environment_id
            ORDER BY a.code COLLATE NOCASE,e.name COLLATE NOCASE
            """
        ).fetchall()
        host_rows = connection.execute(
            """
            SELECT h.id,h.name,h.hostname,h.address,h.management_address,h.environment,h.location,
                   h.active,h.variables_json,m.group_id
            FROM hosts h
            LEFT JOIN memberships m ON m.host_id=h.id
            WHERE h.active=1
            ORDER BY h.name COLLATE NOCASE
            """
        ).fetchall()

    groups: dict[str, dict[str, Any]] = {}
    by_group_id: dict[str, str] = {}
    by_fallback: dict[tuple[str, str], str] = {}
    for row in group_rows:
        key = f"{row['apmid_id']}:{row['environment_id']}"
        item = {
            "id": key,
            "apmid_id": str(row["apmid_id"]),
            "apmid": str(row["apmid"]),
            "environment_id": str(row["environment_id"]),
            "environment": str(row["environment"]),
            "environment_slug": str(row["environment_slug"]),
            "group_id": str(row["group_id"]),
            "hosts": [],
        }
        groups[key] = item
        by_group_id[item["group_id"]] = key
        for environment_value in {item["environment"].casefold(), item["environment_slug"].casefold()}:
            by_fallback[(item["apmid"].casefold(), environment_value)] = key

    attached: set[str] = set()
    for row in host_rows:
        variables = _variables(row["variables_json"])
        if provider and str(variables.get("algen_provider") or "") != provider:
            continue
        key = by_group_id.get(str(row["group_id"] or ""))
        if not key:
            project = str(variables.get("algen_project") or "").strip().casefold()
            environment = str(row["environment"] or "").strip().casefold()
            key = by_fallback.get((project, environment))
        if not key:
            continue
        host_id = str(row["id"])
        membership_key = f"{key}:{host_id}"
        if membership_key in attached:
            continue
        attached.add(membership_key)
        vmid = variables.get("proxmox_vmid") or variables.get("algen_provider_resource_id")
        groups[key]["hosts"].append(
            {
                "id": host_id,
                "name": str(row["name"]),
                "hostname": str(row["hostname"] or ""),
                "address": str(row["address"] or ""),
                "management_address": str(row["management_address"] or ""),
                "location": str(row["location"] or ""),
                "provider": str(variables.get("algen_provider") or ""),
                "provider_instance_id": str(variables.get("algen_provider_instance_id") or ""),
                "provider_resource_id": str(variables.get("algen_provider_resource_id") or ""),
                "vmid": int(vmid) if str(vmid or "").isdigit() else None,
                "node": str(variables.get("proxmox_node") or ""),
                "resource_type": str(variables.get("proxmox_resource_type") or ""),
                "present": variables.get("proxmox_present", True) is not False,
            }
        )

    return sorted(groups.values(), key=lambda item: (item["apmid"].casefold(), item["environment"].casefold()))


__all__ = ["network_inventory"]
