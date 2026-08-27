from __future__ import annotations

import ipaddress
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from ..proxmox_manager.public import ProxmoxApiClient, active_connections, api_client

_MANAGED_COMMENT = "DCST:"


def provider_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return (f"dcst_{normalized}" if not normalized.startswith("dcst_") else normalized)[:64]


@dataclass
class ProviderContext:
    connection: dict[str, Any]
    client: ProxmoxApiClient


class ProxmoxFirewallProvider:
    """Single adapter for all DCST access to the Proxmox VE Firewall API."""

    def contexts(self) -> list[ProviderContext]:
        return [ProviderContext(item, api_client(str(item["id"]))) for item in active_connections()]

    def status(self) -> dict[str, Any]:
        results = []
        for ctx in self.contexts():
            try:
                options = ctx.client.get("cluster/firewall/options") or {}
                rules = ctx.client.get("cluster/firewall/rules") or []
                ipsets = ctx.client.get("cluster/firewall/ipset") or []
                results.append({"connection_id": ctx.connection["id"], "name": ctx.connection["name"], "ok": True, "enabled": bool(options.get("enable", 0)), "rules": len(rules), "ipsets": len(ipsets)})
            except Exception as error:  # noqa: BLE001
                results.append({"connection_id": ctx.connection["id"], "name": ctx.connection["name"], "ok": False, "error": str(error)})
        return {"ok": bool(results) and all(item["ok"] for item in results), "connections": results}

    def test(self) -> dict[str, Any]:
        results = []
        for ctx in self.contexts():
            checks = {"api": False, "authentication": False, "firewall": False, "ipsets": False, "rules": False, "logs": False}
            error = ""
            try:
                ctx.client.get("version")
                checks["api"] = checks["authentication"] = True
                ctx.client.get("cluster/firewall/options")
                checks["firewall"] = True
                ctx.client.get("cluster/firewall/ipset")
                checks["ipsets"] = True
                ctx.client.get("cluster/firewall/rules")
                checks["rules"] = True
                nodes = ctx.client.get("nodes") or []
                if nodes:
                    node = urllib.parse.quote(str(nodes[0].get("node") or ""), safe="")
                    if node:
                        ctx.client.get(f"nodes/{node}/firewall/log?limit=1")
                        checks["logs"] = True
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            results.append({"connection_id": ctx.connection["id"], "name": ctx.connection["name"], "checks": checks, "ok": all(checks.values()), "error": error})
        return {"ok": bool(results) and all(item["ok"] for item in results), "connections": results}

    @staticmethod
    def _ipset_entries(client: ProxmoxApiClient, name: str) -> list[str]:
        rows = client.get(f"cluster/firewall/ipset/{urllib.parse.quote(name, safe='')}") or []
        return sorted(str(row.get("cidr") or "") for row in rows if isinstance(row, dict) and row.get("cidr"))

    def plan_ipset(self, ctx: ProviderContext, item: dict[str, Any]) -> dict[str, Any]:
        name = str(item["provider_name"])
        desired = sorted(str(entry["address"]) for entry in item.get("entries", []))
        current_sets = ctx.client.get("cluster/firewall/ipset") or []
        exists = any(str(row.get("name") or "") == name for row in current_sets if isinstance(row, dict))
        actual = self._ipset_entries(ctx.client, name) if exists else []
        operations = []
        if not exists:
            operations.append({"operation": "CREATE", "object": "ipset", "name": name})
        for value in sorted(set(actual) - set(desired)):
            operations.append({"operation": "DELETE", "object": "ipset-entry", "name": name, "value": value})
        for value in sorted(set(desired) - set(actual)):
            operations.append({"operation": "CREATE", "object": "ipset-entry", "name": name, "value": value})
        return {"object": "ipset", "id": item["id"], "provider_name": name, "state": "NO_CHANGE" if not operations else "UPDATE" if exists else "CREATE", "operations": operations, "actual": actual, "desired": desired}

    def apply_ipset(self, ctx: ProviderContext, item: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        plan = self.plan_ipset(ctx, item)
        if dry_run or not plan["operations"]:
            return plan
        name = plan["provider_name"]
        current_sets = ctx.client.get("cluster/firewall/ipset") or []
        if not any(str(row.get("name") or "") == name for row in current_sets if isinstance(row, dict)):
            ctx.client.post("cluster/firewall/ipset", {"name": name, "comment": f"Managed by DCST: {item['name']}"})
        for value in sorted(set(plan["actual"]) - set(plan["desired"])):
            ctx.client.request("DELETE", f"cluster/firewall/ipset/{urllib.parse.quote(name, safe='')}/{urllib.parse.quote(value, safe='')}")
        for value in sorted(set(plan["desired"]) - set(plan["actual"])):
            ctx.client.post(f"cluster/firewall/ipset/{urllib.parse.quote(name, safe='')}", {"cidr": value, "comment": "Managed by DCST"})
        return self.plan_ipset(ctx, item) | {"applied": True}

    @staticmethod
    def _managed_rules(rows: list[Any], service_id: str = "") -> list[dict[str, Any]]:
        result = []
        prefix = f"{_MANAGED_COMMENT}{service_id}:" if service_id else _MANAGED_COMMENT
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            comment = str(row.get("comment") or "")
            if comment.startswith(prefix):
                result.append(dict(row) | {"_position": int(row.get("pos", index))})
        return result

    @staticmethod
    def _endpoint(endpoint_type: str, value: str, ipsets: dict[str, dict[str, Any]]) -> str:
        if endpoint_type == "any":
            return ""
        if endpoint_type in {"ipset", "tag"}:
            item = ipsets.get(value)
            if not item:
                raise KeyError(f"IPSet not found: {value}")
            return f"+{item['provider_name']}"
        if endpoint_type == "ip":
            return str(ipaddress.ip_address(value))
        if endpoint_type == "cidr":
            return str(ipaddress.ip_network(value, strict=False))
        raise ValueError(f"unsupported direct endpoint type: {endpoint_type}")

    def desired_rules(self, service: dict[str, Any], ports: dict[str, dict[str, Any]], ipsets: dict[str, dict[str, Any]], apmid_tags: dict[str, list[str]]) -> list[dict[str, Any]]:
        endpoint_pairs: list[tuple[str, str]] = []
        if service["source_type"] == "apmid" or service["destination_type"] == "apmid":
            sources = apmid_tags.get(service["source_value"], []) if service["source_type"] == "apmid" else [service["source_value"]]
            destinations = apmid_tags.get(service["destination_value"], []) if service["destination_type"] == "apmid" else [service["destination_value"]]
            endpoint_pairs = [(source, destination) for source in sources for destination in destinations]
        else:
            endpoint_pairs = [(service["source_value"], service["destination_value"])]
        rules = []
        port_objects = [ports[pid] for pid in service.get("port_ids", []) if pid in ports] or [None]
        for source_value, destination_value in endpoint_pairs:
            source_type = "tag" if service["source_type"] == "apmid" else service["source_type"]
            destination_type = "tag" if service["destination_type"] == "apmid" else service["destination_type"]
            source = self._endpoint(source_type, source_value, ipsets)
            destination = self._endpoint(destination_type, destination_value, ipsets)
            for port in port_objects:
                protocols = [""]
                if port:
                    protocols = ["tcp", "udp"] if port["protocol"] == "tcp+udp" else [port["protocol"]]
                for protocol in protocols:
                    item = {"type": service["direction"].lower(), "action": "DROP" if service.get("blocked") else service["action"], "enable": 1 if service.get("enabled") else 0, "log": "info" if service.get("logging") else "nolog", "comment": ""}
                    if source:
                        item["source"] = source
                    if destination:
                        item["dest"] = destination
                    if protocol:
                        item["proto"] = protocol
                        if protocol in {"tcp", "udp"} and port:
                            item["dport"] = str(port["port_from"]) if port["port_from"] == port["port_to"] else f"{port['port_from']}:{port['port_to']}"
                    rules.append(item)
        for index, item in enumerate(rules):
            item["comment"] = f"DCST:{service['id']}:{index}|{service['name']}"
        return rules

    @staticmethod
    def _rule_signature(rule: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(str(rule.get(key) or "") for key in ("type", "action", "source", "dest", "proto", "dport", "enable", "log", "comment"))

    def plan_service(self, ctx: ProviderContext, service: dict[str, Any], ports: dict[str, dict[str, Any]], ipsets: dict[str, dict[str, Any]], apmid_tags: dict[str, list[str]]) -> dict[str, Any]:
        desired = self.desired_rules(service, ports, ipsets, apmid_tags)
        actual = self._managed_rules(ctx.client.get("cluster/firewall/rules") or [], str(service["id"]))
        same = sorted(self._rule_signature(item) for item in actual) == sorted(self._rule_signature(item) for item in desired)
        operations = [] if same else ([{"operation": "DELETE", "position": item["_position"]} for item in sorted(actual, key=lambda value: value["_position"], reverse=True)] + [{"operation": "CREATE", "rule": item} for item in desired])
        return {"object": "service", "id": service["id"], "state": "NO_CHANGE" if same else "UPDATE" if actual else "CREATE", "operations": operations, "desired_rules": desired, "actual_rules": actual}

    def apply_service(self, ctx: ProviderContext, service: dict[str, Any], ports: dict[str, dict[str, Any]], ipsets: dict[str, dict[str, Any]], apmid_tags: dict[str, list[str]], *, dry_run: bool = False) -> dict[str, Any]:
        plan = self.plan_service(ctx, service, ports, ipsets, apmid_tags)
        if dry_run or not plan["operations"]:
            return plan
        for operation in plan["operations"]:
            if operation["operation"] == "DELETE":
                ctx.client.request("DELETE", f"cluster/firewall/rules/{operation['position']}")
            elif operation["operation"] == "CREATE":
                ctx.client.post("cluster/firewall/rules", operation["rule"])
        verified = self.plan_service(ctx, service, ports, ipsets, apmid_tags)
        return verified | {"applied": True, "verified": verified["state"] == "NO_CHANGE"}

    def delete_service_rules(self, ctx: ProviderContext, service_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        rows = self._managed_rules(ctx.client.get("cluster/firewall/rules") or [], service_id)
        operations = [{"operation": "DELETE", "position": item["_position"]} for item in sorted(rows, key=lambda value: value["_position"], reverse=True)]
        if not dry_run:
            for operation in operations:
                ctx.client.request("DELETE", f"cluster/firewall/rules/{operation['position']}")
        return {"object": "service", "id": service_id, "operations": operations, "applied": not dry_run}

    def firewall_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        result = []
        for ctx in self.contexts():
            try:
                nodes = ctx.client.get("nodes") or []
            except Exception:  # noqa: BLE001
                continue
            for node_item in nodes:
                node = str(node_item.get("node") or "")
                if not node:
                    continue
                try:
                    rows = ctx.client.get(f"nodes/{urllib.parse.quote(node, safe='')}/firewall/log?limit={max(1, min(limit, 1000))}") or []
                except Exception:  # noqa: BLE001
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        result.append({"connection_id": ctx.connection["id"], "connection_name": ctx.connection["name"], "node": node, **row})
        return result[:max(1, min(limit, 1000))]
