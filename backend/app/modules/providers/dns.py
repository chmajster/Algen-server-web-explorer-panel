from __future__ import annotations

import base64
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

import yaml

from ...config import get_config
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, PackageAction, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .container_apps import CONTAINER_APPS_BY_ID
from .infrastructure import ApiConnectionProvider


class DnsContainerProvider(ApiConnectionProvider):
    container_app_id = ""

    @property
    def container_app(self):
        return CONTAINER_APPS_BY_ID[self.container_app_id]

    @property
    def container_data_dir(self) -> Path:
        path = Path(get_config().paths.data_dir) / "container-apps" / self.container_app_id
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def _docker(self, args: list[str], *, timeout: int = 180) -> str:
        return self._result(self._run(["docker", *args], timeout=timeout), f"{self.container_app.name} Docker operation failed")

    def _container_inspect(self) -> dict[str, Any] | None:
        if not shutil.which("docker"):
            return None
        result = self._run(["docker", "inspect", self.container_app.container], timeout=15)
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
            return payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else None
        except (json.JSONDecodeError, IndexError):
            return None

    @staticmethod
    def _timezone(payload: dict[str, Any]) -> str:
        timezone = str(payload.get("timezone") or "UTC")
        if timezone not in available_timezones():
            api_error(422, "INVALID_TIMEZONE", "Timezone must be a known IANA timezone")
        return timezone

    def _run_container(self, image: str, timezone: str, options: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    def _manage_container(self, operation: str, payload: dict[str, Any], log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        inspect = self._container_inspect()
        if operation == "install_container":
            if inspect:
                api_error(409, "CONTAINER_EXISTS", f"The controlled {self.container_app.name} container already exists")
            if not shutil.which("docker"):
                api_error(409, "DOCKER_UNAVAILABLE", "Install and start Docker before installing a container application")
            timezone = self._timezone(payload)
            progress(15, f"Pulling {self.container_app.name} image")
            self._docker(["pull", self.container_app.image], timeout=1800)
            if cancelled():
                raise InterruptedError(f"{self.container_app.name} installation cancelled before container creation")
            self._run_container(self.container_app.image, timezone, payload)
        elif operation in {"container_start", "container_stop", "container_restart"}:
            if not inspect:
                api_error(404, "CONTAINER_NOT_FOUND", f"{self.container_app.name} container is not installed")
            self._docker([operation.removeprefix("container_"), self.container_app.container])
        elif operation == "update_container":
            if not inspect:
                api_error(404, "CONTAINER_NOT_FOUND", f"{self.container_app.name} container is not installed")
            timezone = self._timezone(payload)
            old_image = str(inspect.get("Image") or inspect.get("Config", {}).get("Image") or self.container_app.image)
            was_running = bool(inspect.get("State", {}).get("Running"))
            progress(15, f"Pulling updated {self.container_app.name} image")
            self._docker(["pull", self.container_app.image], timeout=1800)
            if was_running:
                self._docker(["stop", self.container_app.container])
            self._docker(["rm", self.container_app.container])
            try:
                self._run_container(self.container_app.image, timezone, payload)
                if not was_running:
                    self._docker(["stop", self.container_app.container])
            except RuntimeError:
                self._run_container(old_image, timezone, payload)
                if not was_running:
                    self._docker(["stop", self.container_app.container])
                log("stderr", f"{self.container_app.name} update failed; the previous image was restored")
                raise
        elif operation == "remove_container":
            if not inspect:
                api_error(404, "CONTAINER_NOT_FOUND", f"{self.container_app.name} container is not installed")
            if bool(inspect.get("State", {}).get("Running")):
                self._docker(["stop", self.container_app.container])
            self._docker(["rm", self.container_app.container])
            log("stdout", f"{self.container_app.name} container removed; configuration data was preserved")
        else:
            api_error(400, "MODULE_ACTION_NOT_SUPPORTED", "Unsupported container application action")
        log("stdout", f"{self.container_app.name} operation {operation} completed")
        progress(95, f"Refreshing {self.container_app.name} state")
        return {"operation": operation, "status": self.get_status().model_dump(mode="json")}

    def get_log_sources(self) -> list[dict[str, str]]:
        if self._container_inspect():
            return [{"id": "docker:container", "label": f"{self.container_app.name} container"}]
        return super().get_log_sources()

    def get_logs(self, source: str, lines: int = 200, search: str = "", level: str = "") -> dict[str, Any]:
        if source == "docker:container" and self._container_inspect():
            result = self._run(["docker", "logs", "--tail", str(min(max(lines, 1), 1000)), "--timestamps", self.container_app.container], timeout=30)
            if result.returncode != 0:
                self._result(result, f"Could not read {self.container_app.name} logs")
            output = (result.stdout + result.stderr).splitlines()
            needle = search.strip().lower()
            selected = [line for line in output if not needle or needle in line.lower()]
            return {"source": source, "lines": selected, "truncated": len(selected) < len(output)}
        return super().get_logs(source, lines, search, level)

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if self._container_inspect() and action in {PackageAction.start, PackageAction.stop, PackageAction.restart}:
            return self._manage_container(f"container_{action.value}", payload, log, progress, cancelled)
        return super().execute_operation(action, payload, actor, log, progress, cancelled)


class PiHoleProvider(DnsContainerProvider):
    allowed_tools = {"pihole-FTL", "docker"}
    container_app_id = "pihole"

    def default_base_url(self) -> str:
        return "http://127.0.0.1:8080"

    def _container_settings(self, options: dict[str, Any] | None) -> dict[str, Any]:
        settings_path = self.container_data_dir / "settings.json"
        try:
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        options = options or {}
        settings: dict[str, Any] = {
            "hostname": str(options.get("hostname") or saved.get("hostname") or "pihole"),
            "panel_port": int(options.get("panel_port") or saved.get("panel_port") or 8080),
            "dns_port": int(options.get("dns_port") or saved.get("dns_port") or 53),
            "network": str(options.get("network") or saved.get("network") or "bridge"),
        }
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", settings["hostname"]):
            api_error(422, "INVALID_HOSTNAME", "Pi-hole hostname is invalid")
        if not 1 <= settings["panel_port"] <= 65535 or not 1 <= settings["dns_port"] <= 65535:
            api_error(422, "INVALID_PORT", "Pi-hole ports must be between 1 and 65535")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", settings["network"]) or settings["network"] in {"host", "none"}:
            api_error(422, "INVALID_NETWORK", "Pi-hole must use a managed bridge network")
        temp = settings_path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, settings_path)
        os.chmod(settings_path, 0o600)
        return settings

    def _run_container(self, image: str, timezone: str, options: dict[str, Any] | None = None) -> None:
        secret = str(self.connection().get("secret") or "")
        if not secret:
            api_error(409, "PIHOLE_PASSWORD_REQUIRED", "Set a Pi-hole web/API password before installing the container")
        config_dir = self.container_data_dir / "etc-pihole"
        config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(config_dir, 0o700)
        password_file = self.container_data_dir / "webpassword"
        with password_file.open("w", encoding="utf-8") as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(password_file, 0o600)
        settings = self._container_settings(options)
        self._docker([
            "run", "-d", "--name", self.container_app.container,
            "--label", "io.webnas.app=pihole", "--restart", "unless-stopped",
            "--hostname", settings["hostname"], "--network", settings["network"],
            "-e", f"TZ={timezone}", "-e", "FTLCONF_dns_listeningMode=all",
            "-e", "WEBPASSWORD_FILE=/run/secrets/pihole_webpassword",
            "-p", f"{settings['dns_port']}:53/tcp", "-p", f"{settings['dns_port']}:53/udp", "-p", f"{settings['panel_port']}:80/tcp",
            "--health-cmd", "dig +short +norecurse +retry=0 @127.0.0.1 pi.hole || exit 1", "--health-interval", "30s", "--health-timeout", "5s", "--health-retries", "5",
            "-v", f"{config_dir}:/etc/pihole", "-v", f"{password_file}:/run/secrets/pihole_webpassword:ro",
            image,
        ])

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
        inspect = self._container_inspect()
        container_running = bool(inspect and inspect.get("State", {}).get("Running"))
        local_install = bool(shutil.which("pihole-FTL") or inspect)
        if not local_install and not self.connection():
            return ModuleStatus(installed=False, service_state="not_installed", services={}, health=ModuleHealth.not_installed, health_message="Pi-hole is not installed", metrics={"blocking": False, "summary": {}})
        try:
            blocking = self._api("/api/dns/blocking")
            summary = self._api("/api/stats/summary")
            api_active = True
            health = ModuleHealth.healthy
            message = "Pi-hole API is available"
        except RuntimeError as error:
            blocking, summary, api_active, health, message = {}, {}, False, ModuleHealth.degraded, str(error)
        installed = local_install or api_active
        if not installed:
            health = ModuleHealth.not_installed
        active = api_active or container_running
        enabled = bool(blocking.get("blocking")) if isinstance(blocking, dict) else False
        image = str(inspect.get("Config", {}).get("Image") or "") if inspect else ""
        service = self.container_app.container if inspect else "pihole-FTL"
        return ModuleStatus(installed=installed, package_version=image or None, service_state="active" if active else "inactive", service_enabled=enabled, services={service: {"state": "active" if active else "inactive", "enabled": True, "required": True}}, health=health, health_message=message, metrics={"blocking": enabled, "summary": summary, "panel_port": self.container_app.panel_port if inspect else None})

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
        if operation in {"install_container", "container_start", "container_stop", "container_restart", "update_container", "remove_container"}:
            if operation == "install_container" and not str(self.connection().get("secret") or ""):
                api_error(409, "PIHOLE_PASSWORD_REQUIRED", "Set a Pi-hole web/API password before installing the container")
            if (
                operation == "install_container"
                and Path("/run/systemd/system").is_dir()
                and shutil.which("systemctl")
                and self._systemctl("systemd-resolved", "is-active").returncode == 0
            ):
                api_error(409, "DNS_PORT_CONFLICT", "systemd-resolved is active and may own port 53. Reconfigure its DNS stub listener explicitly before installing Pi-hole; WebNAS will not change host DNS automatically")
            return self._manage_container(operation, payload, log, progress, cancelled)
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


class AdGuardHomeProvider(DnsContainerProvider):
    allowed_tools = {"AdGuardHome", "docker"}
    container_app_id = "adguard-home"
    CONFIG_PATHS = (Path("/opt/AdGuardHome/AdGuardHome.yaml"), Path("/var/lib/AdGuardHome/AdGuardHome.yaml"), Path("/etc/AdGuardHome.yaml"))

    def default_base_url(self) -> str:
        return "http://127.0.0.1:3000"

    def _run_container(self, image: str, timezone: str, options: dict[str, Any] | None = None) -> None:
        work_dir = self.container_data_dir / "work"
        config_dir = self.container_data_dir / "conf"
        for path in (work_dir, config_dir):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(path, 0o700)
        self._docker([
            "run", "-d", "--name", self.container_app.container,
            "--label", "io.webnas.app=adguard-home", "--restart", "unless-stopped",
            "-e", f"TZ={timezone}",
            "-p", "53:53/tcp", "-p", "53:53/udp", "-p", "3000:3000/tcp",
            "-p", "8081:80/tcp", "-p", "8444:443/tcp", "-p", "8444:443/udp",
            "-v", f"{work_dir}:/opt/adguardhome/work", "-v", f"{config_dir}:/opt/adguardhome/conf",
            image,
        ])

    def _headers(self) -> dict[str, str]:
        config = self.connection()
        token = base64.b64encode(f"{config.get('username', '')}:{config.get('secret', '')}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _api(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        return self._request(f"/control{path}", method=method, payload=payload, headers=self._headers())

    def get_status(self) -> ModuleStatus:
        inspect = self._container_inspect()
        container_running = bool(inspect and inspect.get("State", {}).get("Running"))
        local_install = bool(shutil.which("AdGuardHome") or any(path.exists() for path in self.CONFIG_PATHS) or inspect)
        if not local_install and not self.connection():
            return ModuleStatus(installed=False, service_state="not_installed", services={}, health=ModuleHealth.not_installed, health_message="AdGuard Home is not installed", metrics={"status": {}, "statistics": {}})
        try:
            status = self._api("/status")
            statistics = self._api("/stats")
            health, api_active, message = ModuleHealth.healthy, True, "AdGuard Home API is available"
        except RuntimeError as error:
            status, statistics, health, api_active, message = {}, {}, ModuleHealth.degraded, False, str(error)
        installed = local_install or api_active
        if not installed:
            health = ModuleHealth.not_installed
        state = "active" if api_active or container_running else "inactive"
        image = str(inspect.get("Config", {}).get("Image") or "") if inspect else ""
        service = self.container_app.container if inspect else "AdGuardHome"
        return ModuleStatus(installed=installed, package_version=str(status.get("version") or "") or image or None, service_state=state, services={service: {"state": state, "enabled": True, "required": True}}, health=health, health_message=message, metrics={"status": status, "statistics": statistics, "panel_port": self.container_app.panel_port if inspect else None})

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
        if operation in {"install_container", "container_start", "container_stop", "container_restart", "update_container", "remove_container"}:
            return self._manage_container(operation, payload, log, progress, cancelled)
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

    def _config_paths(self) -> tuple[Path, ...]:
        return (*self.CONFIG_PATHS, self.container_data_dir / "conf" / "AdGuardHome.yaml")

    def _config_file(self) -> Path:
        path = next((item for item in self._config_paths() if item.is_file()), None)
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
        inspect = self._container_inspect()
        container_active = bool(inspect and inspect.get("State", {}).get("Running"))
        was_active = container_active or self._systemctl("AdGuardHome", "is-active").returncode == 0
        if container_active:
            self._docker(["stop", self.container_app.container])
        elif was_active and self._systemctl("AdGuardHome", "stop").returncode != 0:
            raise RuntimeError("AdGuard Home service could not be stopped for restore")
        tmp = target.with_suffix(".webnas.tmp")
        try:
            tmp.write_bytes(content)
            tmp.chmod(previous_mode)
            os.replace(tmp, target)
            if container_active:
                self._docker(["start", self.container_app.container])
            elif was_active and self._systemctl("AdGuardHome", "start").returncode != 0:
                raise RuntimeError("AdGuard Home service failed after restore")
        except Exception:
            rollback = target.with_suffix(".webnas.rollback")
            rollback.write_bytes(previous)
            rollback.chmod(previous_mode)
            os.replace(rollback, target)
            if container_active:
                self._docker(["start", self.container_app.container])
            elif was_active:
                self._systemctl("AdGuardHome", "start")
            raise
        log("stdout", "AdGuard Home configuration restored from a verified private backup")
        return {"restored": backup_id}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="AdGuard Home API", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "critical", recommended_action="Verify the private API URL and credentials" if status.health != ModuleHealth.healthy else "")]
