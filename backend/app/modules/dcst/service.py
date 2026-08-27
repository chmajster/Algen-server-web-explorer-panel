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
from ..hosts_manager.public import network_inventory
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
    """Desired-state boundary for shared inventory and Proxmox Firewall."""

    def __init__(self, repository: DcstRepository | None = None, provider: ProxmoxFirewallProvider | None = None, inventory: Callable[[], list[dict[str, Any]]] | None = None) -> None:
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
        record_activity(ActivityCategory.module, action, actor, target=target, details=details or {}, status=ActivityStatus.failure if failed else ActivityStatus.success, source="dcst")

    def _inventory_event(self, payload: dict[str, Any]) -> None:
        try:
            self.sync_inventory(str(payload.get("actor") or "system"), apply=False)
        except Exception as error:  # noqa: BLE001
            self.repository.set_state("last_inventory_event_error", {"at": time.time(), "error": str(error)[:2000]})

    def inventory(self) -> list[dict[str, Any]]:
        return self.inventory_source()

    def tags(self) -> list[dict[str, Any]]:
        groups = {self._tag_name(str(item["apmid"]), str(item["environment"])): item for item in self.inventory()}
        result: list[dict[str, Any]] = []
        for stored in self.repository.tags():
            item = dict(stored)
            hosts = list((groups.get(str(item["name"])) or {}).get("hosts") or [])
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
            current = existing.get(name)
            value = {"name": name, "description": f"Automatic internal communication for APMID {apmid}", "direction": "OUT", "action": "ACCEPT", "source_type": "apmid", "source_value": apmid, "destination_type": "apmid", "destination_value": apmid, "port_ids": [], "enabled": True, "logging": False, "comment": "Managed by DCST"}
            saved = self.repository.save_service(value, actor, str(current["id"]) if current else None, system_service=True)
            if not current:
                changed += 1
                self.repository.audit(actor, "SERVICE_CREATED", "service", str(saved["id"]), after=saved)
        return changed

    def sync_inventory(self, actor: str, *, apply: bool = False) -> dict[str, Any]:
        with self._lock:
            groups = self.inventory()
            names: set[str] = set()
            apmids: set[str] = set()
            for group in groups:
                apmid = str(group.get("apmid") or "").strip().upper()
                environment = str(group.get("environment") or "").strip().upper()
                if not apmid or not environment:
                    continue
                name = self._tag_name(apmid, environment)
                names.add(name)
                apmids.add(apmid)
                tag = self.repository.upsert_dynamic_tag(name, apmid, environment, provider_name(name))
                addresses = sorted({address for host in group.get("hosts") or [] if host.get("present", True) is not False and (address := self._address(str(host.get("management_address") or host.get("address") or "")))})
                current = next((item for item in self.repository.ipsets() if item["name"] == name and item["type"] == "dynamic"), None)
                ipset = self.repository.save_ipset(name, f"Dynamic VM inventory for {name}", addresses, actor, item_id=str(current["id"]) if current else None, item_type="dynamic", provider_name=str(tag["provider_name"]))
                self.repository.audit(actor, "TAG_SYNCHRONIZED", "tag", str(tag["id"]), after={"tag": tag, "ipset_id": ipset["id"], "addresses": addresses})
            self.repository.delete_missing_dynamic_tags(names)
            system_services = self._ensure_system_services(apmids, actor)
            summary: dict[str, Any] = {"groups": len(groups), "tags": len(names), "system_services": system_services, "at": time.time()}
            self.repository.set_state("last_inventory_sync", summary)
        if apply:
            summary["firewall"] = self.sync_all(actor, refresh_inventory=False)
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
        missing = [item for item in value.get("port_ids", []) if item not in ports]
        if missing:
            raise DcstConflict(f"Unknown Port object: {missing[0]}")
        tags = {str(item["name"]) for item in self.repository.tags()}
        for side in ("source", "destination"):
            kind = str(value[f"{side}_type"])
            endpoint = str(value.get(f"{side}_value") or "")
            if kind == "tag" and endpoint not in tags:
                raise DcstConflict(f"Unknown TAG: {endpoint}")
            if kind == "ipset" and endpoint not in ipsets:
                raise DcstConflict(f"Unknown IPSet: {endpoint}")
            if kind == "apmid" and endpoint.upper() not in apmid_tags:
                raise DcstConflict(f"Unknown APMID: {endpoint}")

    @staticmethod
    def _high_risk(item: dict[str, Any]) -> bool:
        return (str(item.get("action")) == "DROP" or bool(item.get("blocked"))) and item.get("source_type") == "any" and item.get("destination_type") == "any"

    def ports(self) -> list[dict[str, Any]]:
        return self.repository.ports()

    def save_port(self, payload: PortInput, actor: str, item_id: str | None = None) -> dict[str, Any]:
        before = self.repository.port(item_id) if item_id else None
        if item_id and not before:
            raise DcstNotFound("Port not found")
        item = self.repository.save_port(payload.model_dump(mode="json"), actor, item_id)
        self.repository.audit(actor, "PORT_UPDATED" if before else "PORT_CREATED", "port", str(item["id"]), before=before, after=item)
        return item | {"dependencies": self.repository.port_dependencies(str(item["id"]))}

    def delete_port(self, item_id: str, actor: str) -> bool:
        before = self.repository.port(item_id)
        if not before:
            raise DcstNotFound("Port not found")
        dependencies = self.repository.port_dependencies(item_id)
        if dependencies:
            raise DcstConflict(f"Port is referenced by {len(dependencies)} Service(s)")
        result = self.repository.delete_port(item_id)
        self.repository.audit(actor, "PORT_DELETED", "port", item_id, before=before)
        return result

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
        self.repository.audit(actor, "IPSET_UPDATED" if before else "IPSET_CREATED", "ipset", str(item["id"]), before=before, after=item)
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
        result = self.repository.delete_ipset(item_id)
        self.repository.audit(actor, "IPSET_DELETED", "ipset", item_id, before=item)
        return result

    def services(self, *, search: str = "", apmid: str = "", environment: str = "", direction: str = "", action: str = "", state: str = "") -> list[dict[str, Any]]:
        tags = {item["name"]: item for item in self.repository.tags()}
        needle = search.strip().casefold()
        result = []
        for item in self.repository.services():
            text = " ".join(str(item.get(key) or "") for key in ("name", "description", "source_value", "destination_value", "direction", "action", "state")).casefold()
            endpoints = [tags.get(str(item["source_value"])), tags.get(str(item["destination_value"]))]
            if needle and needle not in text:
                continue
            if direction and item["direction"] != direction or action and item["action"] != action or state and item["state"] != state:
                continue
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
        for side in ("source", "destination"):
            if value[f"{side}_type"] in {"tag", "apmid"}:
                value[f"{side}_value"] = str(value.get(f"{side}_value") or "").upper()
        self._validate_service_refs(value)
        item = self.repository.save_service(value, actor, item_id)
        self.repository.audit(actor, "SERVICE_UPDATED" if before else "SERVICE_CREATED", "service", str(item["id"]), before=before, after=item)
        return item

    def clone_service(self, item_id: str, actor: str) -> dict[str, Any]:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        value = {key: item[key] for key in ("description", "direction", "action", "source_type", "source_value", "destination_type", "destination_value", "port_ids", "enabled", "logging", "comment")}
        existing = {service["name"] for service in self.repository.services()}
        base = f"{item['name']}_COPY"
        name = base
        index = 2
        while name in existing:
            name = f"{base}_{index}"
            index += 1
        value["name"] = name[:128]
        cloned = self.repository.save_service(value, actor)
        self.repository.audit(actor, "SERVICE_CLONED", "service", str(cloned["id"]), before=item, after=cloned)
        return cloned

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

    def sync_service(self, item_id: str, actor: str, *, dry_run: bool = False, confirm_high_risk: bool = False) -> dict[str, Any]:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        if self._high_risk(item) and not confirm_high_risk:
            raise DcstHighRisk("DROP ANY -> ANY requires explicit high-risk confirmation")
        ports, ipsets, apmid_tags = self._maps()
        contexts = self.provider.contexts()
        if not contexts:
            raise DcstConflict("No active Proxmox connection is configured")
        try:
            results = [{"connection_id": context.connection["id"], "connection_name": context.connection["name"], **self.provider.apply_service(context, item, ports, ipsets, apmid_tags, dry_run=dry_run)} for context in contexts]
            if not dry_run:
                verified = all(result.get("state") == "NO_CHANGE" or result.get("verified") for result in results)
                self.repository.set_object_sync("dcst_services", item_id, "SYNCED" if verified else "DRIFT")
                self.repository.audit(actor, "SERVICE_SYNCHRONIZED", "service", item_id, after=item, provider_response=results, status="success" if verified else "warning")
            return {"service_id": item_id, "dry_run": dry_run, "results": results}
        except Exception as error:
            if not dry_run:
                self.repository.set_object_sync("dcst_services", item_id, "ERROR", str(error))
                self.repository.audit(actor, "FIREWALL_SYNC_FAILED", "service", item_id, after=item, status="failed", error=str(error))
            raise

    def change_service_state(self, item_id: str, actor: str, operation: str, *, apply: bool = True) -> dict[str, Any]:
        before = self.repository.service(item_id)
        if not before:
            raise DcstNotFound("Service not found")
        if operation in {"block", "unblock"}:
            after = self.repository.set_service_state(item_id, blocked=operation == "block")
        elif operation in {"enable", "disable"}:
            after = self.repository.set_service_state(item_id, enabled=operation == "enable")
        else:
            raise ValueError("Unsupported Service state operation")
        self.repository.audit(actor, f"SERVICE_{operation.upper()}D" if operation != "disable" else "SERVICE_DISABLED", "service", item_id, before=before, after=after)
        result: dict[str, Any] = {"service": after}
        if apply:
            result["sync"] = self.sync_service(item_id, actor, confirm_high_risk=operation == "block")
        return result

    def bulk(self, ids: list[str], actor: str, operation: str) -> dict[str, Any]:
        results = []
        for item_id in dict.fromkeys(ids):
            try:
                value = self.sync_service(item_id, actor) if operation == "sync" else self.change_service_state(item_id, actor, operation)
                results.append({"id": item_id, "ok": True, "result": value})
            except Exception as error:  # noqa: BLE001
                results.append({"id": item_id, "ok": False, "error": str(error)})
        return {"operation": operation, "total": len(results), "success": sum(item["ok"] for item in results), "failed": sum(not item["ok"] for item in results), "results": results}

    def delete_service(self, item_id: str, actor: str, *, remove_provider_rules: bool = True) -> bool:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        if item.get("system_service"):
            raise DcstConflict("System Service cannot be deleted")
        responses = [self.provider.delete_service_rules(context, item_id) for context in self.provider.contexts()] if remove_provider_rules else []
        removed = self.repository.delete_service(item_id)
        self.repository.audit(actor, "SERVICE_DELETED", "service", item_id, before=item, provider_response=responses)
        return removed

    def sync_all(self, actor: str, *, dry_run: bool = False, confirm_high_risk: bool = False, refresh_inventory: bool = True) -> dict[str, Any]:
        if refresh_inventory:
            self.sync_inventory(actor, apply=False)
        self.repository.audit(actor, "FIREWALL_SYNC_STARTED", "firewall", "all", after={"dry_run": dry_run})
        ipsets: list[dict[str, Any]] = []
        services: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
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
        result = self.sync_all(actor or "system", dry_run=True)
        drifted = [item for group in (result["ipsets"], result["services"]) for item in group if any(entry.get("state") != "NO_CHANGE" for entry in item.get("results", []))]
        return {"state": "DRIFT" if drifted else "SYNCED", "drifted": drifted, "errors": result["errors"], "checked_at": time.time()}

    def preview_service(self, item_id: str) -> dict[str, Any]:
        item = self.repository.service(item_id)
        if not item:
            raise DcstNotFound("Service not found")
        tags = {tag["name"]: tag for tag in self.tags()}
        ipsets = {value["id"]: value for value in self.repository.ipsets()} | {value["name"]: value for value in self.repository.ipsets()}

        def addresses(kind: str, value: str) -> list[str]:
            if kind == "tag":
                return list(tags.get(value, {}).get("addresses", []))
            if kind == "apmid":
                return sorted({address for tag in tags.values() if tag["apmid"] == value for address in tag.get("addresses", [])})
            if kind == "ipset":
                return [str(entry["address"]) for entry in ipsets.get(value, {}).get("entries", [])]
            return [value] if value else []

        plans = self.sync_service(item_id, "preview", dry_run=True, confirm_high_risk=True) if self.provider.contexts() else {"results": []}
        return {"service": item, "source": {"type": item["source_type"], "value": item["source_value"], "addresses": addresses(item["source_type"], item["source_value"])}, "destination": {"type": item["destination_type"], "value": item["destination_value"], "addresses": addresses(item["destination_type"], item["destination_value"])}, "ports": [port for port in self.repository.ports() if port["id"] in item["port_ids"]], "provider_plans": plans["results"], "high_risk": self._high_risk(item)}

    def overview(self) -> dict[str, Any]:
        services = self.repository.services()
        status = self.provider.status()
        return {"services": len(services), "active_services": sum(item["state"] == "ACTIVE" for item in services), "blocked_services": sum(item["state"] == "BLOCKED" for item in services), "ports": len(self.repository.ports()), "ipsets": len(self.repository.ipsets()), "tags": len(self.repository.tags()), "firewall_rules": sum(int(item.get("rules") or 0) for item in status.get("connections", []) if item.get("ok")), "firewall": status, "last_inventory_sync": self.repository.state("last_inventory_sync", {}), "last_firewall_sync": self.repository.state("last_firewall_sync", {}), "recent_changes": self.repository.audits(20)}

    def diagnostics(self) -> dict[str, Any]:
        expected = {self._tag_name(str(item["apmid"]), str(item["environment"])) for item in self.inventory()}
        stored = {str(item["name"]) for item in self.repository.tags()}
        services = self.repository.services()
        used_ports = {port_id for item in services for port_id in item.get("port_ids", [])}
        used_ipsets = {str(item[key]) for item in services for key, type_key in (("source_value", "source_type"), ("destination_value", "destination_type")) if item[type_key] == "ipset"}
        return {"database": {"ok": True}, "proxmox": self.provider.status(), "dynamic_tags": {"expected": sorted(expected), "stored": sorted(stored), "consistent": expected == stored}, "orphaned_ports": [item for item in self.repository.ports() if item["id"] not in used_ports], "orphaned_ipsets": [item for item in self.repository.ipsets() if item["type"] == "manual" and item["id"] not in used_ipsets and item["name"] not in used_ipsets], "last_sync": self.repository.state("last_firewall_sync", {})}

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
