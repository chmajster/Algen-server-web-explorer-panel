"""DATA Communication & Segmentation Tool domain service."""

from __future__ import annotations

import ipaddress
import re
import threading
import time
from functools import lru_cache
from typing import Any, Callable

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...core.events import bus
from ..hosts_manager.network_inventory import network_inventory
from .models import IPSetInput, PortInput, ServiceInput
from .provider import ProxmoxFirewallProvider, provider_name
from .repository import DcstRepository


class DcstError(RuntimeError):
    pass


class DcstNotFound(DcstError):
    pass


class DcstConflict(DcstError):
    pass


class DcstHighRisk(DcstError):
    pass


class DcstService:
    """Desired-state boundary for inventory-derived groups and Proxmox Firewall."""

    def __init__(
        self,
        repository: DcstRepository | None = None,
        provider: ProxmoxFirewallProvider | None = None,
        inventory: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.repository = repository or DcstRepository()
        self.provider = provider or ProxmoxFirewallProvider()
        self.inventory_source = inventory or network_inventory
        self._lock = threading.RLock()
        self._unsubscribe = bus.subscribe("PROXMOX_INVENTORY_CHANGED", self._inventory_event)

    @staticmethod
    def _tag_name(apmid: str, environment: str) -> str:
        return f"{apmid.strip().upper()}.{environment.strip().upper()}"

    @staticmethod
    def _system_service_name(apmid: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", apmid.strip().upper()).strip("_")
        return f"SYSTEM_{slug}_INTERNAL"[:128]

    @staticmethod
    def _address(raw: str) -> str:
        value = raw.strip()
        if not value:
            return ""
        try:
            if "/" in value:
                return str(ipaddress.ip_network(value, strict=False))
            address = ipaddress.ip_address(value)
            return f"{address}/{32 if address.version == 4 else 128}"
        except ValueError:
            return ""

    def _activity(self, actor: str, action: str, target: str, details: dict[str, Any] | None = None, *, failed: bool = False) -> None:
        record_activity(
            ActivityCategory.module,
            action,
            actor,
            target=target,
            details=details or {},
            status=ActivityStatus.failure if failed else ActivityStatus.success,
            source="dcst",
        )

    def _inventory_event(self, payload: dict[str, Any]) -> None:
        actor = str(payload.get("actor") or "system")
        try:
            self.sync_inventory(actor, apply=False)
        except Exception as error:  # noqa: BLE001 - event producer must remain isolated
            self.repository.set_state("last_inventory_event_error", {"at": time.time(), "error": str(error)[:2000]})

    def inventory(self) -> list[dict[str, Any]]:
        return self.inventory_source()

    def tags(self) -> list[dict[str, Any]]:
        groups = {self._tag_name(str(item["apmid"]), str(item["environment"])): item for item in self.inventory()}
        result = []
        for item in self.repository.tags():
            group = groups.get(str(item["name"]))
            hosts = list(group.get("hosts") or []) if group else []
            item = dict(item)
            item["hosts"] = hosts
            item["vm_count"] = len(hosts)
            item["addresses"] = sorted({address for host in hosts if (address := self._address(str(host.get("management_address") or host.get("address") or "")))})
            result.append(item)
        return result

    def _ensure_system_services(self, apmids: set[str], actor: str) -> int:
        existing = {str(item["name"]): item for item in self.repository.services()}
        changed = 0
        for apmid in sorted(apmids):
            name = self._system_service_name(apmid)
            value = {
                "name": name,
                "description": f"Automatic internal communication for APMID {apmid}",
                "direction": "OUT",
                "action": "ACCEPT",
                "source_type": "apmid",
                "source_value": apmid,
                "destination_type": "apmid",
                "destination_value": apmid,
                "port_ids": [],
                "enabled": True,
                "logging": False,
                "comment": "Managed by DCST",
            }
            current = existing.get(name)
            before = dict(current) if current else None
            saved = self.repository.save_service(value, actor, str(current["id"]) if current else None, system_service=True)
            if not current or any(before.get(key) != saved.get(key) for key in ("source_value", "destination_value", "enabled")):
                changed += 1
                self.repository.audit(actor, "SERVICE_CREATED" if not current else "SERVICE_UPDATED", "service", str(saved["id"]), before=before, after=saved)
        return changed

    def sync_inventory(self, actor: str, *, apply: bool = False) -> dict[str, Any]:
        """Reconcile canonical Hosts Manager inventory into dynamic TAG/IPSet desired state."""
        with self._lock:
            groups = self.inventory()
            names: set[str] = set()
            apmids: set[str] = set()
            updated = 0
            for group in groups:
                apmid = str(group.get("apmid") or "").strip().upper()
                environment = str(group.get("environment") or "").strip().upper()
                if not apmid or not environment:
                    continue
                name = self._tag_name(apmid, environment)
                names.add(name)
                apmids.add(apmid)
                tag = self.repository.upsert_dynamic_tag(name, apmid, environment, provider_name(name))
                addresses = sorted({
                    address
                    for host in group.get("hosts") or []
                    if host.get("present", True) is not False
                    and (address := self._address(str(host.get("management_address") or host.get("address") or "")))
                })
                current = next((item for item in self.repository.ipsets() if item["name"] == name and item["type"] == "dynamic"), None)
                ipset = self.repository.save_ipset(
                    name,
                    f"Dynamic VM inventory for {name}",
                    addresses,
                    actor,
                    item_id=str(current["id"]) if current else None,
                    item_type="dynamic",
                    provider_name=str(tag["provider_name"]),
                )
                self.repository.audit(actor, "TAG_SYNCHRONIZED", "tag", str(tag["id"]), after={"tag": tag, "ipset_id": ipset["id"], "addresses": addresses})
                updated += 1
            self.repository.delete_missing_dynamic_tags(names)
            system_services = self._ensure_system_services(apmids, actor)
            summary = {"groups": len(groups), "tags": updated, "system_services": system_services, "at": time.time()}
            self.repository.set_state("last_inventory_sync", summary)
        if apply:
            summary["firewall"] = self.sync_all(actor, dry_run=False, refresh_inventory=False)
        self._activity(actor, "dcst_inventory_sync", "inventory", summary)
        return summary

    def _maps(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
        ports = {str(item["id"]): item for item in self.repository.ports()}
        ipsets: dict[str, dict[str, Any]] = {}
        for item in self.repository.ipsets():
            ipsets[str(item["id"])] = item
            ipsets[str(item["name"])] = item
        apmid_tags: dict[str, list[str]] = {}
        for tag in self.repository.tags():
            apmid_tags.setdefault(str(tag["apmid"]), []).append(str(tag["name"]))
        return ports, ipsets, apmid_tags

    def _validate_service_refs(self, value: dict[str, Any]) -> None:
        ports, ipsets, apmid_tags = self._maps()
        missing_ports = [item for item in value.get("port_ids", []) if item not in ports]
        if missing_ports:
            raise DcstConflict(f"Unknown Port object: {missing_ports[0]}")
        tags = {str(item["name"]) for item in self.repository.tags()}
        for label in ("source", "destination"):
            endpoint_type = str(value[f"{label}_type"])
            endpoint_value = str(value.get(f"{label}_value") or "")
            if endpoint_type == "tag" and endpoint_value not in tags:
                raise DcstConflict(f"Unknown TAG: {endpoint_value}")
            if endpoint_type == "ipset" and endpoint_value not in ipsets:
                raise DcstConflict(f"Unknown IPSet: {endpoint_value}")
            if endpoint_type == "apmid" and endpoint_value.upper() not in apmid_tags:
                raise DcstConflict(f"Unknown APMID: {endpoint_value}")

    @staticmethod
    def _high_risk(service: dict[str, Any]) -> bool:
        return (
            (str(service.get("action")) == "DROP" or bool(service.get("blocked")))
            and str(service.get("source_type")) == "any"
            and str(service.get("destination_type")) == "any"
        )

    def ports(self) -> list[dict[str, Any]]:
        return self.repository.ports()

    def save_port(self, payload: PortInput, actor: str, item_id: str | None = None) -> dict[str, Any]:
        before = self.repository.port(item_id) if item_id else None
        if item_id and not before:
            raise DcstNotFound("Port not found")
        item = self.repository.save_port(payload.model_dump(mode="json"), actor, item_id)
        operation = "PORT_UPDATED" if before else "PORT_CREATED"
        self.repository.audit(actor, operation, "port", str(item["id"]), before=before, after=item)
        self._activity(actor, operation.lower(), str(item["id"]), {"name": item["name"]})
        return item | {"dependencies": self.repository.port_dependencies(str(item["id"]))}

    def delete_port(self, item_id: str, actor: str) -> bool:
        before = self.repository.port(item_id)
        if not before:
            raise DcstNotFound("Port not found")
        dependencies = self.repository.port_dependencies(item_id)
        if dependencies:
            raise DcstConflict(f"Port is referenced by {len(dependencies)} Service(s)")
        removed = self.repository.delete_port(item_id)
        self.repository.audit(actor, "PORT_DELETED", "port", item_id, before=before)
        return removed

    def ipsets(self) -> list[dict[str, Any]]:
        services = self.repository.services()
        result = []
        for item in self.repository.ipsets():
            refs = [service for service in services if (service["source_type"] == "ipset" and service["source_value"] in {item["id"], item["name"]}) or (service["destination_type"] == "ipset" and service["destination_value"] in {item["id"], item["name"]})]
            result.append(item | {"dependencies": [{"id": ref["id"], "name": ref["name"]} for ref in refs]})
        return result

    def save_ipset(self, payload: IPSetInput, actor: str, item_id: str | None = None) -> dict[str, Any]:
        before = self.repository.ipset(item_id) if item_id else None
        if item_id and not before:
            raise DcstNotFound("IPSet not found")
        if before and before["type"] != "manual":
            raise DcstConflict("Dynamic/system IPSet cannot be edited manually")
        item = self.repository.save_ipset(payload.name, payload.description, payload.entries, actor, item_id=item_id, item_type="manual", provider_name=provider_name(payload.name))
        operation = "IPSET_UPDATED" if before else "IPSET_CREATED"
        self.repository.audit(actor, operation, "ipset", str(item["id"]), before=before, after=item)
        return item

    def delete_ipset(self, item_id: str, actor: str) -> bool:
        item = self.repository.ipset(item_id)
        if not item:
            raise DcstNotFound("IPSet not found")
        if item["type"] != "manual":
            raise DcstConflict("Only manual IPSets can be deleted")
        dependencies = next((value["dependencies"] for value in self.ipsets() if value["id"] == item_id), [])
        if dependencies:
            raise DcstConflict(f"IPSet is referenced by {len(dependencies)} Service(s)")
        removed = self.repository.delete_ipset(item_id)
        self.repository.audit(actor, "IPSET_DELETED", "ipset", item_id, before=item)
        return removed

    def services(self, *, search: str = "", apmid: str = "", environment: str = "", direction: str = "", action: str = "", state: str = "") -> list[dict[str, Any]]:
        items = self.repository.services()
        needle = search.strip().casefold()
        tags = {item["name"]: item for item in self.repository.tags()}
        result = []
        for item in items:
            text = " ".join(str(item.get(key) or "") for key in ("name", "description", "source_value", "destination_value", "direction", "action", "state")).casefold()
            if needle and needle not in text:
                continue
            if direction and item["direction"] != direction:
                continue
            if action and item["action"] != action:
                continue
            if state and item["state"] != state:
                continue
            endpoints = [tags.get(str(item["source_value"])), tags.get(str(item["destination_value"]))]
            if apmid and not any(tag and str(tag["apmid"]).casefold() == apmid.casefold() for tag in endpoints) and apmid.casefold() not in {str(item["source_value"]).casefold(), str(item["destination_value"]).casefold()}:
                continue
            if environment and not any(tag and str(tag["environment"]).casefold() == environment.casefold() for tag in endpoints):
                continue
            result.append(item)
        return result

    def save_service(self, payload: ServiceInput, actor: str, item_id: str | None = None) -> dict[str, Any]:
        before = self.repository.service(item_id) if item_id else None
        if item_id and not before:
            raise DcstNotFound("Service not found")
        if before and before.get("system_service"):
            raise DcstConflict("System Service is managed automatically")
        value = payload.model_dump(mode="json")
        value["source_value"] = str(value.get("source_value") or "").upper() if value["source_type"] in {"tag", "apmid"} else value.get("source_value", "")
        value["destination_value"] = str(value.get("destination_value") or "").upper() if value["destination_type"] in {"tag", "apmid"} else value.get("destination_value", "")
        self._validate_service_refs(value)
        item = self.repository.save_service(value, actor, item_id)
        operation = "SERVICE_UPDATED" if before else "SERVICE_CREATED"
        self.repository.audit(actor, operation, "service", str(item["id"]), before=before, after=item)
        return item

    def clone_service(self, item_id: str, actor: str) -> dict[str, Any]:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        value = {key: item[key] for key in ("description", "direction", "action", "source_type", "source_value", "destination_type", "destination_value", "port_ids", "enabled", "logging", "comment")}
        base = f"{item['name']}_COPY"
        existing = {service["name"] for service in self.repository.services()}
        name = base
        index = 2
        while name in existing:
            name = f"{base}_{index}"
            index += 1
        value["name"] = name[:128]
        cloned = self.repository.save_service(value, actor)
        self.repository.audit(actor, "SERVICE_CLONED", "service", str(cloned["id"]), before=item, after=cloned)
        return cloned

    def _sync_service_item(self, item: dict[str, Any], actor: str, *, dry_run: bool, confirm_high_risk: bool = False) -> dict[str, Any]:
        if self._high_risk(item) and not confirm_high_risk:
            raise DcstHighRisk("DROP ANY -> ANY requires explicit high-risk confirmation")
        ports, ipsets, apmid_tags = self._maps()
        contexts = self.provider.contexts()
        if not contexts:
            raise DcstConflict("No active Proxmox connection is configured")
        results = []
        for context in contexts:
            result = self.provider.apply_service(context, item, ports, ipsets, apmid_tags, dry_run=dry_run)
            results.append({"connection_id": context.connection["id"], "connection_name": context.connection["name"], **result})
        if not dry_run:
            verified = all(result.get("state") == "NO_CHANGE" or result.get("verified") for result in results)
            self.repository.set_object_sync("dcst_services", str(item["id"]), "SYNCED" if verified else "DRIFT")
            self.repository.audit(actor, "SERVICE_SYNCHRONIZED", "service", str(item["id"]), after=item, provider_response=results, status="success" if verified else "warning")
        return {"service_id": item["id"], "dry_run": dry_run, "results": results}

    def sync_service(self, item_id: str, actor: str, *, dry_run: bool = False, confirm_high_risk: bool = False) -> dict[str, Any]:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        try:
            return self._sync_service_item(item, actor, dry_run=dry_run, confirm_high_risk=confirm_high_risk)
        except Exception as error:
            if not dry_run:
                self.repository.set_object_sync("dcst_services", item_id, "ERROR", str(error))
                self.repository.audit(actor, "FIREWALL_SYNC_FAILED", "service", item_id, after=item, status="failed", error=str(error))
            raise

    def sync_ipset(self, item_id: str, actor: str, *, dry_run: bool = False) -> dict[str, Any]:
        item = self.repository.ipset(item_id)
        if not item:
            raise DcstNotFound("IPSet not found")
        contexts = self.provider.contexts()
        if not contexts:
            raise DcstConflict("No active Proxmox connection is configured")
        try:
            results = [{"connection_id": context.connection["id"], **self.provider.apply_ipset(context, item, dry_run=dry_run)} for context in contexts]
            if not dry_run:
                verified = all(result.get("state") == "NO_CHANGE" for result in results)
                self.repository.set_object_sync("dcst_ipsets", item_id, "SYNCED" if verified else "DRIFT")
            return {"ipset_id": item_id, "dry_run": dry_run, "results": results}
        except Exception as error:
            if not dry_run:
                self.repository.set_object_sync("dcst_ipsets", item_id, "ERROR", str(error))
            raise

    def change_service_state(self, item_id: str, actor: str, operation: str, *, apply: bool = True) -> dict[str, Any]:
        before = self.repository.service(item_id)
        if not before:
            raise DcstNotFound("Service not found")
        if operation == "block":
            after = self.repository.set_service_state(item_id, blocked=True)
            audit = "SERVICE_BLOCKED"
        elif operation == "unblock":
            after = self.repository.set_service_state(item_id, blocked=False)
            audit = "SERVICE_UNBLOCKED"
        elif operation == "enable":
            after = self.repository.set_service_state(item_id, enabled=True)
            audit = "SERVICE_ENABLED"
        elif operation == "disable":
            after = self.repository.set_service_state(item_id, enabled=False)
            audit = "SERVICE_DISABLED"
        else:
            raise ValueError("Unsupported Service state operation")
        self.repository.audit(actor, audit, "service", item_id, before=before, after=after)
        result: dict[str, Any] = {"service": after}
        if apply:
            result["sync"] = self.sync_service(item_id, actor, confirm_high_risk=operation == "block")
        return result

    def bulk(self, ids: list[str], actor: str, operation: str) -> dict[str, Any]:
        results = []
        for item_id in dict.fromkeys(ids):
            try:
                if operation == "sync":
                    value = self.sync_service(item_id, actor)
                else:
                    value = self.change_service_state(item_id, actor, operation)
                results.append({"id": item_id, "ok": True, "result": value})
            except Exception as error:  # noqa: BLE001 - report per-object bulk failures
                results.append({"id": item_id, "ok": False, "error": str(error)})
        return {"operation": operation, "total": len(results), "success": sum(item["ok"] for item in results), "failed": sum(not item["ok"] for item in results), "results": results}

    def delete_service(self, item_id: str, actor: str, *, remove_provider_rules: bool = True) -> bool:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        if item.get("system_service"):
            raise DcstConflict("System Service cannot be deleted")
        provider_response = []
        if remove_provider_rules:
            for context in self.provider.contexts():
                provider_response.append(self.provider.delete_service_rules(context, item_id))
        removed = self.repository.delete_service(item_id)
        self.repository.audit(actor, "SERVICE_DELETED", "service", item_id, before=item, provider_response=provider_response)
        return removed

    def sync_all(self, actor: str, *, dry_run: bool = False, confirm_high_risk: bool = False, refresh_inventory: bool = True) -> dict[str, Any]:
        if refresh_inventory:
            self.sync_inventory(actor, apply=False)
        self.repository.audit(actor, "FIREWALL_SYNC_STARTED", "firewall", "all", after={"dry_run": dry_run})
        ipsets = []
        services = []
        errors = []
        for item in self.repository.ipsets():
            try:
                ipsets.append(self.sync_ipset(str(item["id"]), actor, dry_run=dry_run))
            except Exception as error:  # noqa: BLE001
                errors.append({"type": "ipset", "id": item["id"], "error": str(error)})
        for item in self.repository.services():
            try:
                services.append(self.sync_service(str(item["id"]), actor, dry_run=dry_run, confirm_high_risk=confirm_high_risk))
            except Exception as error:  # noqa: BLE001
                errors.append({"type": "service", "id": item["id"], "error": str(error)})
        result = {"dry_run": dry_run, "ipsets": ipsets, "services": services, "errors": errors, "at": time.time()}
        if not dry_run:
            self.repository.set_state("last_firewall_sync", result)
            self.repository.audit(actor, "FIREWALL_SYNC_COMPLETED" if not errors else "FIREWALL_SYNC_FAILED", "firewall", "all", provider_response=result, status="success" if not errors else "failed")
        return result

    def drift(self, actor: str = "") -> dict[str, Any]:
        result = self.sync_all(actor or "system", dry_run=True, refresh_inventory=True)
        drifted = []
        for group in (result["ipsets"], result["services"]):
            for item in group:
                if any(entry.get("state") != "NO_CHANGE" for entry in item.get("results", [])):
                    drifted.append(item)
        return {"state": "DRIFT" if drifted else "SYNCED", "drifted": drifted, "errors": result["errors"], "checked_at": time.time()}

    def preview_service(self, item_id: str) -> dict[str, Any]:
        service = self.repository.service(item_id)
        if not service:
            raise DcstNotFound("Service not found")
        tags = {item["name"]: item for item in self.tags()}
        ipsets = {item["id"]: item for item in self.repository.ipsets()} | {item["name"]: item for item in self.repository.ipsets()}

        def effective(kind: str, value: str) -> list[str]:
            if kind == "tag":
                return list(tags.get(value, {}).get("addresses", []))
            if kind == "apmid":
                values = []
                for tag in tags.values():
                    if tag["apmid"] == value:
                        values.extend(tag.get("addresses", []))
                return sorted(set(values))
            if kind == "ipset":
                return [str(entry["address"]) for entry in ipsets.get(value, {}).get("entries", [])]
            return [value] if value else []

        plans = self.sync_service(item_id, "preview", dry_run=True, confirm_high_risk=True) if self.provider.contexts() else {"results": []}
        return {
            "service": service,
            "source": {"type": service["source_type"], "value": service["source_value"], "addresses": effective(service["source_type"], service["source_value"])},
            "destination": {"type": service["destination_type"], "value": service["destination_value"], "addresses": effective(service["destination_type"], service["destination_value"])},
            "ports": [item for item in self.repository.ports() if item["id"] in service["port_ids"]],
            "provider_plans": plans.get("results", []),
            "high_risk": self._high_risk(service),
        }

    def overview(self) -> dict[str, Any]:
        services = self.repository.services()
        ipsets = self.repository.ipsets()
        tags = self.tags()
        status = self.provider.status()
        return {
            "services": len(services),
            "active_services": sum(item["state"] == "ACTIVE" for item in services),
            "blocked_services": sum(item["state"] == "BLOCKED" for item in services),
            "ports": len(self.repository.ports()),
            "ipsets": len(ipsets),
            "tags": len(tags),
            "firewall_rules": sum(int(item.get("rules") or 0) for item in status.get("connections", []) if item.get("ok")),
            "firewall": status,
            "last_inventory_sync": self.repository.state("last_inventory_sync", {}),
            "last_firewall_sync": self.repository.state("last_firewall_sync", {}),
            "recent_changes": self.repository.audits(20),
        }

    def diagnostics(self) -> dict[str, Any]:
        inventory_names = {self._tag_name(str(item["apmid"]), str(item["environment"])) for item in self.inventory()}
        stored_tags = {str(item["name"]) for item in self.repository.tags()}
        services = self.repository.services()
        used_ports = {port_id for service in services for port_id in service.get("port_ids", [])}
        referenced_ipsets = {str(service[key]) for service in services for key, type_key in (("source_value", "source_type"), ("destination_value", "destination_type")) if service[type_key] == "ipset"}
        return {
            "database": {"schema_version": self.repository.state("schema_version", 1), "ok": True},
            "proxmox": self.provider.status(),
            "dynamic_tags": {"expected": sorted(inventory_names), "stored": sorted(stored_tags), "consistent": inventory_names == stored_tags},
            "orphaned_ports": [item for item in self.repository.ports() if item["id"] not in used_ports],
            "orphaned_ipsets": [item for item in self.repository.ipsets() if item["type"] == "manual" and item["id"] not in referenced_ipsets and item["name"] not in referenced_ipsets],
            "last_sync": self.repository.state("last_firewall_sync", {}),
        }

    def firewall_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.provider.firewall_logs(limit)

    def test_proxmox(self) -> dict[str, Any]:
        return self.provider.test()

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.audits(limit)


@lru_cache(maxsize=1)
def service() -> DcstService:
    return DcstService()


__all__ = ["DcstConflict", "DcstError", "DcstHighRisk", "DcstNotFound", "DcstService", "service"]
