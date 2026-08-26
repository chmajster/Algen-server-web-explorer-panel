from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...config import get_config
from ..hosts_manager.public import (
    HostCapabilityProvider,
    HostInput,
    host_names as shared_host_names,
    provider_hosts as shared_provider_hosts,
    registry as host_registry,
)
from .models import ProxmoxConnectionInput


PROVIDER = "proxmox"
MODULE_ID = "proxmox-manager"


class ProxmoxApiError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class ProxmoxApiClient:
    def __init__(
        self,
        endpoint: str,
        token_id: str,
        token_secret: str,
        *,
        verify_tls: bool = True,
        ca_certificate: str = "",
        timeout: int = 20,
    ) -> None:
        if not token_id or "!" not in token_id or not token_secret:
            raise ValueError("Proxmox API credential requires username user@realm!tokenid and token secret")
        self.endpoint = endpoint.rstrip("/")
        self.authorization = f"PVEAPIToken={token_id}={token_secret}"
        self.timeout = timeout
        if verify_tls:
            self.ssl_context = ssl.create_default_context()
            if ca_certificate:
                self.ssl_context.load_verify_locations(cadata=ca_certificate)
        else:
            self.ssl_context = ssl._create_unverified_context()  # nosec B323 - explicit per-connection opt-out

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        encoded = urllib.parse.urlencode(data or {}, doseq=True).encode() if method != "GET" else None
        url = f"{self.endpoint}/api2/json/{path.lstrip('/')}"
        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:  # nosec B310
                payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                body = json.loads(error.read(128 * 1024).decode("utf-8"))
                detail = str(body.get("errors") or body.get("message") or "")
            except (ValueError, UnicodeDecodeError):
                detail = ""
            raise ProxmoxApiError(
                f"Proxmox API returned HTTP {error.code}" + (f": {detail}" if detail else ""),
                status=error.code,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as error:
            raise ProxmoxApiError(f"Proxmox API connection failed: {type(error).__name__}") from error
        if not isinstance(payload, dict) or "data" not in payload:
            raise ProxmoxApiError("Proxmox API returned an invalid response")
        return payload["data"]

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, data)


class ProxmoxManagerService:
    """Proxmox connection registry and synchronization bridge to Hosts Manager."""

    def __init__(self, path: Path | None = None) -> None:
        root = (path.parent if path else Path(get_config().paths.data_dir) / MODULE_ID).resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        self.path = path or root / "proxmox.sqlite3"
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS connections(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    endpoint TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    ca_certificate TEXT NOT NULL DEFAULT '',
                    default_ssh_user TEXT NOT NULL DEFAULT 'algen-ansible',
                    environment TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '["proxmox"]',
                    sync_lxc INTEGER NOT NULL DEFAULT 1,
                    sync_templates INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    auto_sync INTEGER NOT NULL DEFAULT 0,
                    last_sync_at REAL,
                    last_sync_status TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proxmox_connections_active ON connections(active,name);
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        for key in ("verify_tls", "sync_lxc", "sync_templates", "active", "auto_sync"):
            value[key] = bool(value[key])
        try:
            value["tags"] = json.loads(value.pop("tags_json") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            value["tags"] = []
        return value

    @staticmethod
    def _credential_summary(credential: dict[str, Any] | None) -> dict[str, Any] | None:
        if not credential:
            return None
        return {
            "id": credential["id"],
            "name": credential["name"],
            "type": credential["type"],
            "username": credential["username"],
            "secret_configured": credential["secret_configured"],
        }

    def connections(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM connections"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY name COLLATE NOCASE"
        with self.connect() as connection:
            items = [self._decode(row) or {} for row in connection.execute(query).fetchall()]
        credentials = {item["id"]: item for item in host_registry().credentials()}
        for item in items:
            item["credential"] = self._credential_summary(credentials.get(item["credential_id"]))
        return items

    def connection(self, connection_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            item = self._decode(connection.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone())
        if not item:
            return None
        credential = next((value for value in host_registry().credentials() if value["id"] == item["credential_id"]), None)
        item["credential"] = self._credential_summary(credential)
        return item

    def save_connection(
        self,
        payload: ProxmoxConnectionInput,
        actor: str,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        credential = next(
            (item for item in host_registry().credentials() if item["id"] == payload.credential_id and item.get("active", True)),
            None,
        )
        if not credential or credential.get("type") != "proxmox_api":
            raise KeyError("Proxmox API credential not found")
        now = time.time()
        item_id = connection_id or secrets.token_hex(16)
        value = payload.model_dump(mode="json")
        with self.connect() as connection:
            old = connection.execute(
                "SELECT created_at,created_by FROM connections WHERE id=?",
                (item_id,),
            ).fetchone()
            created_at = float(old["created_at"]) if old else now
            created_by = str(old["created_by"]) if old else actor
            connection.execute(
                """
                INSERT INTO connections(
                    id,name,endpoint,credential_id,verify_tls,ca_certificate,default_ssh_user,
                    environment,location,tags_json,sync_lxc,sync_templates,active,auto_sync,
                    created_at,updated_at,created_by,updated_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,endpoint=excluded.endpoint,credential_id=excluded.credential_id,
                    verify_tls=excluded.verify_tls,ca_certificate=excluded.ca_certificate,
                    default_ssh_user=excluded.default_ssh_user,environment=excluded.environment,
                    location=excluded.location,tags_json=excluded.tags_json,sync_lxc=excluded.sync_lxc,
                    sync_templates=excluded.sync_templates,active=excluded.active,auto_sync=excluded.auto_sync,
                    updated_at=excluded.updated_at,updated_by=excluded.updated_by
                """,
                (
                    item_id,
                    value["name"],
                    value["endpoint"],
                    value["credential_id"],
                    int(value["verify_tls"]),
                    value["ca_certificate"],
                    value["default_ssh_user"],
                    value["environment"],
                    value["location"],
                    json.dumps(value["tags"]),
                    int(value["sync_lxc"]),
                    int(value["sync_templates"]),
                    int(value["active"]),
                    int(value["auto_sync"]),
                    created_at,
                    now,
                    created_by,
                    actor,
                ),
            )
        return self.connection(item_id) or {}

    def delete_connection(self, connection_id: str) -> bool:
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "UPDATE connections SET active=0,updated_at=? WHERE id=? AND active=1",
                    (time.time(), connection_id),
                ).rowcount
            )

    def _client(self, item: dict[str, Any]) -> ProxmoxApiClient:
        credential = host_registry().verified_credential(
            str(item["credential_id"]),
            module_id=MODULE_ID,
            purpose="proxmox-api",
        )
        if credential["type"] != "proxmox_api":
            raise ValueError("configured credential is not a Proxmox API credential")
        return ProxmoxApiClient(
            str(item["endpoint"]),
            credential["username"],
            credential["secret"],
            verify_tls=bool(item["verify_tls"]),
            ca_certificate=str(item.get("ca_certificate") or ""),
        )

    def test_connection(self, connection_id: str) -> dict[str, Any]:
        item = self.connection(connection_id)
        if not item or not item["active"]:
            raise KeyError("Proxmox connection not found")
        client = self._client(item)
        version = client.get("version")
        nodes = client.get("nodes")
        return {
            "ok": True,
            "connection_id": connection_id,
            "version": version,
            "nodes": [
                {
                    "node": row.get("node"),
                    "status": row.get("status"),
                    "cpu": row.get("cpu"),
                    "mem": row.get("mem"),
                    "maxmem": row.get("maxmem"),
                }
                for row in (nodes or [])
                if isinstance(row, dict)
            ],
        }

    @staticmethod
    def _resource_type(item: dict[str, Any]) -> str:
        value = str(item.get("type") or "")
        return value if value in {"qemu", "lxc"} else ""

    def _resources(self, connection: dict[str, Any], client: ProxmoxApiClient | None = None) -> list[dict[str, Any]]:
        client = client or self._client(connection)
        raw = client.get("cluster/resources?type=vm")
        resources: list[dict[str, Any]] = []
        for value in raw or []:
            if not isinstance(value, dict):
                continue
            resource_type = self._resource_type(value)
            if not resource_type:
                continue
            if resource_type == "lxc" and not connection["sync_lxc"]:
                continue
            if bool(value.get("template")) and not connection["sync_templates"]:
                continue
            resources.append(
                {
                    "vmid": int(value["vmid"]),
                    "name": str(value.get("name") or f"{resource_type}-{value['vmid']}"),
                    "node": str(value.get("node") or ""),
                    "type": resource_type,
                    "status": str(value.get("status") or "unknown"),
                    "template": bool(value.get("template")),
                    "uptime": int(value.get("uptime") or 0),
                    "cpu": float(value.get("cpu") or 0),
                    "maxcpu": int(value.get("maxcpu") or 0),
                    "mem": int(value.get("mem") or 0),
                    "maxmem": int(value.get("maxmem") or 0),
                    "disk": int(value.get("disk") or 0),
                    "maxdisk": int(value.get("maxdisk") or 0),
                }
            )
        return sorted(resources, key=lambda row: (row["node"], row["vmid"]))

    @staticmethod
    def _provider_variables(connection_id: str, resource: dict[str, Any], *, present: bool = True) -> dict[str, Any]:
        return {
            "algen_provider": PROVIDER,
            "algen_provider_instance_id": connection_id,
            "algen_provider_resource_id": str(resource["vmid"]),
            "proxmox_vmid": int(resource["vmid"]),
            "proxmox_node": str(resource["node"]),
            "proxmox_resource_type": str(resource["type"]),
            "proxmox_name": str(resource["name"]),
            "proxmox_status": str(resource["status"]),
            "proxmox_present": present,
        }

    @staticmethod
    def _host_identity(host: dict[str, Any]) -> tuple[str, str] | None:
        variables = dict(host.get("variables") or {})
        if variables.get("algen_provider") != PROVIDER:
            return None
        connection_id = str(variables.get("algen_provider_instance_id") or "")
        resource_id = str(variables.get("algen_provider_resource_id") or variables.get("proxmox_vmid") or "")
        return (connection_id, resource_id) if connection_id and resource_id else None

    @staticmethod
    def _clean_host_name(value: str, vmid: int) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_. -]", "-", value).strip(" .-_")
        if not cleaned or not re.match(r"^[A-Za-z0-9]", cleaned):
            cleaned = f"proxmox-{vmid}"
        return cleaned[:128]

    @staticmethod
    def _dns_address(value: str) -> str:
        candidate = value.strip().rstrip(".")
        if candidate.casefold() == "localhost":
            return ""
        if re.fullmatch(
            r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
            candidate,
        ):
            return candidate
        return ""

    @staticmethod
    def _best_ip(values: list[str]) -> str:
        candidates: list[tuple[int, str]] = []
        for raw in values:
            try:
                address = ipaddress.ip_address(raw.split("/", 1)[0])
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
                continue
            rank = 0 if address.version == 4 and address.is_private else 1 if address.version == 4 else 2
            candidates.append((rank, str(address)))
        candidates.sort()
        return candidates[0][1] if candidates else ""

    @staticmethod
    def _interface_rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            value = value.get("result") or value.get("data") or []
        return [item for item in (value or []) if isinstance(item, dict)] if isinstance(value, list) else []

    def _resolve_address(self, client: ProxmoxApiClient, resource: dict[str, Any]) -> str:
        node = urllib.parse.quote(str(resource["node"]), safe="")
        vmid = int(resource["vmid"])
        values: list[str] = []
        try:
            if resource["type"] == "qemu":
                interfaces = self._interface_rows(client.get(f"nodes/{node}/qemu/{vmid}/agent/network-get-interfaces"))
                for interface in interfaces:
                    for address in interface.get("ip-addresses") or []:
                        if isinstance(address, dict) and address.get("ip-address"):
                            values.append(str(address["ip-address"]))
            else:
                interfaces = self._interface_rows(client.get(f"nodes/{node}/lxc/{vmid}/interfaces"))
                for interface in interfaces:
                    for key in ("inet", "inet6"):
                        if interface.get(key):
                            values.append(str(interface[key]))
        except ProxmoxApiError:
            pass
        return self._best_ip(values)

    @staticmethod
    def _host_payload(
        existing: dict[str, Any] | None,
        connection: dict[str, Any],
        resource: dict[str, Any],
        address: str,
        *,
        name: str,
        present: bool,
    ) -> HostInput:
        variables = dict(existing.get("variables") or {}) if existing else {}
        was_present = variables.get("proxmox_present", True) is not False
        variables.update(ProxmoxManagerService._provider_variables(connection["id"], resource, present=present))

        if existing:
            active = False if not present else (True if not was_present else bool(existing.get("active", True)))
            existing_tags = existing.get("tags")
            tags = list(existing_tags) if isinstance(existing_tags, list) else []
            description = str(existing.get("description") or "")
            environment = str(existing.get("environment") if existing.get("environment") is not None else "")
            location = str(existing.get("location") if existing.get("location") is not None else "")
        else:
            active = present
            tags = list(connection["tags"])
            description = f"Proxmox {resource['type']} VM {resource['vmid']} on {resource['node']}"
            environment = str(connection["environment"])
            location = str(connection["location"])

        return HostInput(
            name=str(existing["name"]) if existing else name,
            hostname=str(existing.get("hostname") or "") if existing else ProxmoxManagerService._dns_address(resource["name"]),
            fqdn=str(existing.get("fqdn") or "") if existing else "",
            address=address,
            management_address=str(existing.get("management_address") or "") if existing else "",
            port=int(existing.get("port") or 22) if existing else 22,
            connection_type=str(existing.get("connection_type") or "ssh") if existing else "ssh",
            ssh_user=str(existing.get("ssh_user") or connection["default_ssh_user"]) if existing else str(connection["default_ssh_user"]),
            credential_id=existing.get("credential_id") if existing else None,
            python_interpreter=str(existing.get("python_interpreter") or "auto_silent") if existing else "auto_silent",
            environment=environment,
            location=location,
            description=description,
            tags=tags,
            variables=variables,
            group_ids=list(existing.get("group_ids") or []) if existing else [],
            active=active,
            approved=bool(existing.get("approved", False)) if existing else False,
            power_profile_id=existing.get("power_profile_id") if existing else None,
        )

    def list_vms(self, connection_id: str = "") -> dict[str, Any]:
        connections = [self.connection(connection_id)] if connection_id else self.connections(active_only=True)
        host_map = {
            identity: host
            for host in shared_provider_hosts(PROVIDER)
            if (identity := self._host_identity(host)) is not None
        }
        values: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for connection in connections:
            if not connection or not connection["active"]:
                continue
            try:
                resources = self._resources(connection)
            except (ProxmoxApiError, KeyError, ValueError) as error:
                errors.append({"connection_id": str(connection["id"]), "connection_name": str(connection["name"]), "error": str(error)})
                continue
            for resource in resources:
                host = host_map.get((str(connection["id"]), str(resource["vmid"])))
                values.append(
                    resource
                    | {
                        "connection_id": connection["id"],
                        "connection_name": connection["name"],
                        "host_id": host.get("id") if host else None,
                        "host_address": host.get("address") if host else "",
                        "host_active": bool(host.get("active")) if host else False,
                        "sync_state": "synced" if host else "not_synced",
                    }
                )
        return {"vms": values, "errors": errors, "total": len(values)}

    def _set_sync_status(self, connection_id: str, status: str, error: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE connections SET last_sync_at=?,last_sync_status=?,last_error=?,updated_at=? WHERE id=?",
                (time.time(), status, error[:2000], time.time(), connection_id),
            )

    def sync(self, connection_id: str, actor: str, *, resolve_addresses: bool = True, disable_missing: bool = True) -> dict[str, Any]:
        connection = self.connection(connection_id)
        if not connection or not connection["active"]:
            raise KeyError("Proxmox connection not found")
        client = self._client(connection)
        try:
            resources = self._resources(connection, client)
        except Exception as error:
            self._set_sync_status(connection_id, "failed", str(error))
            raise

        provider_hosts = {
            identity: host
            for host in shared_provider_hosts(PROVIDER, connection_id)
            if (identity := self._host_identity(host)) is not None
        }
        occupied_names = shared_host_names()
        seen: set[tuple[str, str]] = set()
        created = updated = disabled = 0
        skipped: list[dict[str, Any]] = []
        synchronized: list[dict[str, Any]] = []

        for resource in resources:
            identity = (connection_id, str(resource["vmid"]))
            seen.add(identity)
            existing = provider_hosts.get(identity)
            address = self._resolve_address(client, resource) if resolve_addresses else ""
            if not address and existing:
                address = str(existing.get("address") or "")
            if not address:
                address = self._dns_address(resource["name"])
            if not address:
                skipped.append(
                    {
                        "vmid": resource["vmid"],
                        "name": resource["name"],
                        "reason": "No usable guest address. Install QEMU Guest Agent or provide resolvable VM DNS name.",
                    }
                )
                continue

            name = self._clean_host_name(resource["name"], resource["vmid"])
            if not existing and name.casefold() in occupied_names:
                suffix = f"-{connection_id[:6]}-{resource['vmid']}"
                name = f"{name[: max(1, 128 - len(suffix))]}{suffix}"
            payload = self._host_payload(existing, connection, resource, address, name=name, present=True)
            host = host_registry().save_host(payload, actor, str(existing["id"]) if existing else None, source=PROVIDER)
            occupied_names.add(str(host["name"]).casefold())
            if existing:
                updated += 1
            else:
                created += 1
            synchronized.append(
                {
                    "vmid": resource["vmid"],
                    "name": resource["name"],
                    "host_id": host["id"],
                    "address": host["address"],
                    "status": resource["status"],
                }
            )

        if disable_missing:
            for identity, existing in provider_hosts.items():
                if identity in seen or not existing.get("active", True):
                    continue
                variables = dict(existing.get("variables") or {})
                resource = {
                    "vmid": int(variables.get("proxmox_vmid") or identity[1]),
                    "name": str(variables.get("proxmox_name") or existing["name"]),
                    "node": str(variables.get("proxmox_node") or ""),
                    "type": str(variables.get("proxmox_resource_type") or "qemu"),
                    "status": "missing",
                }
                payload = self._host_payload(
                    existing,
                    connection,
                    resource,
                    str(existing["address"]),
                    name=str(existing["name"]),
                    present=False,
                )
                host_registry().save_host(payload, actor, str(existing["id"]), source=PROVIDER)
                disabled += 1

        self._set_sync_status(connection_id, "completed")
        host_registry().operation(
            None,
            "proxmox.sync",
            actor,
            module_id=MODULE_ID,
            status="completed",
            stage="completed",
            progress=100,
            details={
                "connection_id": connection_id,
                "created": created,
                "updated": updated,
                "disabled": disabled,
                "skipped": len(skipped),
            },
        )
        return {
            "connection_id": connection_id,
            "created": created,
            "updated": updated,
            "disabled": disabled,
            "skipped": skipped,
            "hosts": synchronized,
        }

    def _resource_from_host(self, host: dict[str, Any]) -> tuple[dict[str, Any], int]:
        variables = dict(host.get("variables") or {})
        if variables.get("algen_provider") != PROVIDER or not variables.get("proxmox_present", True):
            raise KeyError("Host is not backed by an active Proxmox resource")
        connection_id = str(variables.get("algen_provider_instance_id") or "")
        connection = self.connection(connection_id)
        if not connection or not connection["active"]:
            raise KeyError("Proxmox connection not found")
        vmid = int(variables.get("proxmox_vmid") or variables.get("algen_provider_resource_id"))
        return connection, vmid

    def _live_resource(self, connection: dict[str, Any], vmid: int) -> dict[str, Any]:
        resource = next((item for item in self._resources(connection) if int(item["vmid"]) == vmid), None)
        if not resource:
            raise KeyError("Proxmox VM not found")
        if not resource.get("node") or resource.get("type") not in {"qemu", "lxc"}:
            raise ValueError("Proxmox resource metadata is incomplete")
        return resource

    def _dispatch_resource_action(
        self,
        connection: dict[str, Any],
        resource: dict[str, Any],
        action: str,
        actor: str,
        host: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = urllib.parse.quote(str(resource["node"]), safe="")
        task = self._client(connection).post(
            f"nodes/{node}/{resource['type']}/{int(resource['vmid'])}/status/{action}"
        )
        host_id = str(host["id"]) if host else None
        operation = host_registry().operation(
            host_id,
            f"proxmox.{action}",
            actor,
            module_id=MODULE_ID,
            status="queued",
            stage="proxmox-task",
            progress=10,
            details={
                "connection_id": connection["id"],
                "vmid": int(resource["vmid"]),
                "node": resource["node"],
                "resource_type": resource["type"],
                "task": task,
            },
        )
        return {"host_id": host_id, "action": action, "task": task, "operation": operation}

    def execute_host_action(self, host: dict[str, Any], action: str, actor: str) -> dict[str, Any]:
        if action not in {"start", "stop", "shutdown", "reboot"}:
            raise ValueError("Unsupported Proxmox power action")
        connection, vmid = self._resource_from_host(host)
        resource = self._live_resource(connection, vmid)
        return self._dispatch_resource_action(connection, resource, action, actor, host)

    def execute_vm_action(self, connection_id: str, vmid: int, action: str, actor: str) -> dict[str, Any]:
        if action not in {"start", "stop", "shutdown", "reboot"}:
            raise ValueError("Unsupported Proxmox power action")
        connection = self.connection(connection_id)
        if not connection or not connection["active"]:
            raise KeyError("Proxmox connection not found")
        resource = self._live_resource(connection, vmid)
        host = next(
            (
                item
                for item in shared_provider_hosts(PROVIDER, connection_id)
                if self._host_identity(item) == (connection_id, str(vmid))
            ),
            None,
        )
        return self._dispatch_resource_action(connection, resource, action, actor, host)


@lru_cache
def service() -> ProxmoxManagerService:
    return ProxmoxManagerService()


def register_host_capabilities() -> None:
    registry = host_registry()
    permissions = {
        "start": "hosts-manager.power.on",
        "stop": "hosts-manager.power.shutdown",
        "shutdown": "hosts-manager.power.shutdown",
        "reboot": "hosts-manager.power.reboot",
    }

    def supports(host: dict[str, Any]) -> bool:
        variables = dict(host.get("variables") or {})
        return (
            bool(host.get("active"))
            and variables.get("algen_provider") == PROVIDER
            and bool(variables.get("algen_provider_instance_id"))
            and bool(variables.get("proxmox_node"))
            and variables.get("proxmox_present", True) is not False
        )

    def make_plan(action: str):
        def plan(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
            dangerous = action in {"stop", "shutdown", "reboot"}
            return {
                "host_id": host["id"],
                "host_name": host["name"],
                "provider": PROVIDER,
                "action": action,
                "dangerous": dangerous,
                "confirmations_required": ["confirm", "host_name"] if dangerous else ["confirm"],
            }

        return plan

    def make_execute(action: str):
        def execute(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
            if not parameters.get("confirm"):
                raise PermissionError("Proxmox action requires confirmation")
            if action in {"stop", "shutdown", "reboot"} and parameters.get("confirmation_text") != host["name"]:
                raise PermissionError("Proxmox action requires the exact host name")
            return service().execute_host_action(host, action, actor)

        return execute

    for action in ("start", "stop", "shutdown", "reboot"):
        registry.register_capability(
            HostCapabilityProvider(
                id=f"{MODULE_ID}.{action}",
                name=f"Proxmox {action}",
                icon="power",
                permission=permissions[action],
                module_id=MODULE_ID,
                supports=supports,
                plan=make_plan(action),
                execute=make_execute(action),
                deep_link="/modules/proxmox-manager",
            )
        )
