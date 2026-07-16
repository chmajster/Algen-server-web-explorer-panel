from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .infrastructure import ApiConnectionProvider


class PiHoleProvider(ApiConnectionProvider):
    allowed_tools = {"pihole-FTL"}

    def default_base_url(self) -> str:
        return "http://127.0.0.1"

    def _api(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        config = self.connection()
        auth = self._request("/api/auth", method="POST", payload={"password": str(config.get("secret") or "")})
        session = auth.get("session", {}) if isinstance(auth, dict) else {}
        sid = str(session.get("sid") or "")
        if not session.get("valid") or not sid:
            raise RuntimeError("Pi-hole API authentication failed")
        try:
            return self._request(path, method=method, payload=payload, headers={"X-FTL-SID": sid})
        finally:
            try:
                self._request("/api/auth", method="DELETE", headers={"X-FTL-SID": sid})
            except RuntimeError:
                pass

    def get_status(self) -> ModuleStatus:
        installed = bool(shutil.which("pihole-FTL") or self.connection())
        try:
            blocking = self._api("/api/dns/blocking")
            summary = self._api("/api/stats/summary")
            active = True
            health = ModuleHealth.healthy
            message = "Pi-hole API is available"
        except RuntimeError as error:
            blocking, summary, active, health, message = {}, {}, False, ModuleHealth.degraded if installed else ModuleHealth.not_installed, str(error)
        enabled = bool(blocking.get("blocking")) if isinstance(blocking, dict) else False
        return ModuleStatus(installed=installed, service_state="active" if active else "inactive", service_enabled=enabled, services={"pihole-FTL": {"state": "active" if active else "inactive", "enabled": True, "required": True}}, health=health, health_message=message, metrics={"blocking": enabled, "summary": summary})

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        paths = {
            "statistics": "/api/stats/summary",
            "domains": "/api/domains",
            "clients": "/api/clients",
            "lists": "/api/lists",
            "updates": "/api/info/version",
        }
        if resource not in paths:
            return super().list_resources(resource, limit=limit, search=search)
        data = self._api(paths[resource])
        if resource == "statistics" or resource == "updates":
            items = [data]
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            candidate = data.get(resource) or data.get("items") or data
            items = candidate if isinstance(candidate, list) else [candidate]
        else:
            items = []
        if resource == "domains":
            items = [item for item in items if not isinstance(item, dict) or item.get("type") in {1, 3, "deny", "denied", "regex_deny"}]
        needle = search.lower().strip()
        if needle:
            items = [item for item in items if needle in json.dumps(item, ensure_ascii=False).lower()]
        return {"resource": resource, "items": items[:limit], "total": len(items)}

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation not in {"blocking_enable", "blocking_disable"}:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        progress(20, "Updating Pi-hole blocking state")
        if cancelled():
            raise InterruptedError("Pi-hole operation cancelled")
        result = self._api("/api/dns/blocking", method="POST", payload={"blocking": operation == "blocking_enable", "timer": None})
        log("stdout", "Pi-hole blocking state updated through the authenticated API")
        progress(95, "Verifying Pi-hole state")
        return {"operation": operation, "response": result, "status": self.get_status().model_dump(mode="json")}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        connection = self.public_connection()
        return [
            ModuleDiagnostic(status="ok" if connection["secret_configured"] else "warning", title="API credentials", description="Application password configured" if connection["secret_configured"] else "No application password is configured", severity="ok" if connection["secret_configured"] else "warning", recommended_action="Configure a Pi-hole application password" if not connection["secret_configured"] else ""),
            ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="Pi-hole API", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "critical"),
        ]


class AdGuardHomeProvider(ApiConnectionProvider):
    allowed_tools = {"AdGuardHome"}
    CONFIG_PATHS = (Path("/opt/AdGuardHome/AdGuardHome.yaml"), Path("/var/lib/AdGuardHome/AdGuardHome.yaml"), Path("/etc/AdGuardHome.yaml"))

    def default_base_url(self) -> str:
        return "http://127.0.0.1:3000"

    def _headers(self) -> dict[str, str]:
        config = self.connection()
        token = base64.b64encode(f"{config.get('username', '')}:{config.get('secret', '')}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _api(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        return self._request(f"/control{path}", method=method, payload=payload, headers=self._headers())

    def get_status(self) -> ModuleStatus:
        installed = bool(shutil.which("AdGuardHome") or any(path.exists() for path in self.CONFIG_PATHS) or self.connection())
        try:
            status = self._api("/status")
            statistics = self._api("/stats")
            health, state, message = ModuleHealth.healthy, "active", "AdGuard Home API is available"
        except RuntimeError as error:
            status, statistics, health, state, message = {}, {}, ModuleHealth.degraded if installed else ModuleHealth.not_installed, "inactive", str(error)
        return ModuleStatus(installed=installed, package_version=str(status.get("version") or "") or None, service_state=state, services={"AdGuardHome": {"state": state, "enabled": True, "required": True}}, health=health, health_message=message, metrics={"status": status, "statistics": statistics})

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        paths = {"statistics": "/stats", "clients": "/clients", "filters": "/filtering/status", "upstreams": "/dns_info", "querylog": f"/querylog?limit={limit}"}
        if resource not in paths:
            return super().list_resources(resource, limit=limit, search=search)
        path = paths[resource]
        if search and resource == "querylog":
            from urllib.parse import quote

            path += f"&search={quote(search[:200])}"
        data = self._api(path)
        if resource in {"statistics", "upstreams"}:
            items = [data]
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            candidate = data.get("data") if resource == "querylog" else data.get("clients") if resource == "clients" else data.get("filters") if resource == "filters" else data
            items = candidate if isinstance(candidate, list) else [candidate]
        else:
            items = []
        return {"resource": resource, "items": items[:limit], "total": len(items)}

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        progress(20, "Updating AdGuard Home through its authenticated API")
        if operation in {"protection_enable", "protection_disable"}:
            result = self._api("/protection", method="POST", payload={"enabled": operation == "protection_enable", "duration": 0})
        elif operation == "refresh_filters":
            result = self._api("/filtering/refresh", method="POST", payload={"whitelist": False, "force": False})
        elif operation == "set_rules":
            rules = payload.get("rules")
            if not isinstance(rules, list) or len(rules) > 5000 or any(not isinstance(item, str) or len(item) > 1000 or "\x00" in item for item in rules):
                api_error(422, "INVALID_FILTER_RULES", "Filtering rules must be a bounded list of text rules")
            result = self._api("/filtering/set_rules", method="POST", payload={"rules": rules})
        elif operation == "set_upstreams":
            upstreams = payload.get("upstream_dns")
            if not isinstance(upstreams, list) or not 1 <= len(upstreams) <= 20 or any(not isinstance(item, str) or not 1 <= len(item) <= 300 or "\x00" in item for item in upstreams):
                api_error(422, "INVALID_UPSTREAMS", "Upstream DNS servers are invalid")
            current = self._api("/dns_info")
            allowed = {key: value for key, value in current.items() if key in {"bootstrap_dns", "fallback_dns", "protection_enabled", "ratelimit", "blocking_mode", "edns_cs_enabled", "dnssec_enabled", "disable_ipv6", "cache_size", "cache_ttl_min", "cache_ttl_max"}}
            result = self._api("/dns_config", method="POST", payload={**allowed, "upstream_dns": upstreams})
        elif operation == "update_application":
            result = self._api("/update", method="POST", payload={})
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        log("stdout", "AdGuard Home API operation completed; credentials were not logged")
        progress(95, "Refreshing AdGuard Home state")
        return {"operation": operation, "response": result}

    def _config_file(self) -> Path:
        path = next((item for item in self.CONFIG_PATHS if item.is_file()), None)
        if not path:
            api_error(404, "ADGUARD_CONFIG_NOT_FOUND", "AdGuard Home configuration file was not found")
        return path

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        path = self._config_file()
        return self._store_backup(actor, description, path.read_bytes(), ".yaml", automatic=automatic)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        source, _ = self._backup_metadata(backup_id)
        target = self._config_file()
        content = source.read_bytes()
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as error:
            raise RuntimeError("AdGuard Home backup contains invalid YAML") from error
        if not isinstance(parsed, dict):
            raise RuntimeError("AdGuard Home backup has an invalid document root")
        previous = target.read_bytes()
        previous_mode = target.stat().st_mode & 0o777
        was_active = self._systemctl("AdGuardHome", "is-active").returncode == 0
        if was_active and self._systemctl("AdGuardHome", "stop").returncode != 0:
            raise RuntimeError("AdGuard Home service could not be stopped for restore")
        tmp = target.with_suffix(".webnas.tmp")
        try:
            tmp.write_bytes(content)
            tmp.chmod(previous_mode)
            os.replace(tmp, target)
            if was_active and self._systemctl("AdGuardHome", "start").returncode != 0:
                raise RuntimeError("AdGuard Home service failed after restore")
        except Exception:
            rollback = target.with_suffix(".webnas.rollback")
            rollback.write_bytes(previous)
            rollback.chmod(previous_mode)
            os.replace(rollback, target)
            if was_active:
                self._systemctl("AdGuardHome", "start")
            raise
        log("stdout", "AdGuard Home configuration restored from a verified private backup")
        return {"restored": backup_id}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="AdGuard Home API", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "critical", recommended_action="Verify the private API URL and credentials" if status.health != ModuleHealth.healthy else "")]
