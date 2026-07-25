from __future__ import annotations

import json
import hashlib
import io
import ipaddress
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, cast

import yaml

from ...config import get_config
from ...package_center.executor import redact
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, ModuleValidationResult, PackageAction, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .container_apps import CONTAINER_APPS, CONTAINER_APPS_BY_ID
from .infrastructure import ApiConnectionProvider, PrivateBackupProvider, SLUG_RE


IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
REGISTRY_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::[1-9][0-9]{0,4})?$", re.ASCII)
PORT_RE = re.compile(r"^(?:[0-9.:[\]]+:)?[1-9][0-9]{0,4}(?:-[1-9][0-9]{0,4})?:[1-9][0-9]{0,4}(?:-[1-9][0-9]{0,4})?(?:/(?:tcp|udp))?$")
COMPOSE_SERVICE_FIELDS = {
    "image", "container_name", "hostname", "restart", "ports", "volumes", "environment", "networks",
    "depends_on", "labels", "read_only", "tmpfs", "init", "mem_limit", "cpus", "pids_limit", "working_dir", "user",
}
SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "credential", "auth", "apikey", "api_key"}
SYSTEM_NETWORKS = {"bridge", "host", "none"}
DAEMON_CONFIG_FIELDS = {
    "log-driver", "log-opts", "live-restore", "default-address-pools", "dns", "insecure-registries",
    "registry-mirrors", "ipv6", "fixed-cidr-v6", "userland-proxy", "experimental", "features",
    "bip", "fixed-cidr", "default-gateway", "default-gateway-v6", "ip-masq",
}


def _bytes(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?i?b)?\s*", value, re.IGNORECASE)
    if not match:
        return 0
    unit = (match.group(2) or "b").lower()
    factors = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}
    return int(float(match.group(1)) * factors.get(unit, 1))


def _percent(value: Any) -> float:
    try:
        return float(str(value).strip().removesuffix("%"))
    except ValueError:
        return 0.0


def _redact_value(value: Any, key: str = "") -> Any:
    if any(marker in key.lower() for marker in SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact_value(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


class DockerProvider(PrivateBackupProvider):
    allowed_tools = {"docker", "docker-compose", "dockerd", "dpkg-query", "apt-cache", "rpm", "dnf", "yum"}

    def __init__(self, module_id_or_actor: str = "docker") -> None:
        # Generic provider discovery passes the module id, while typed routes
        # pass the audit actor. Docker always uses the fixed bundled manifest.
        self.actor = "" if module_id_or_actor == "docker" else module_id_or_actor
        super().__init__("docker")

    @property
    def compose_dir(self) -> Path:
        path = Path(get_config().paths.data_dir) / "compose"
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    @property
    def daemon_path(self) -> Path:
        return Path("/etc/docker/daemon.json")

    @property
    def manager_store(self):
        from ..docker_manager.storage import store

        return store()

    @staticmethod
    def _allowed_bind_path(value: str) -> Path:
        resolved = Path(value).resolve(strict=False)
        configured = [Path(item).resolve(strict=False) for item in get_config().paths.allowed_roots if str(item).startswith("/")]
        roots = [Path("/srv"), Path("/mnt"), Path("/media"), Path(get_config().paths.data_dir).resolve(strict=False), *configured]
        if resolved == Path("/var/run/docker.sock") or not any(resolved == root or root in resolved.parents for root in roots):
            api_error(422, "UNSAFE_BIND_PATH", "Bind mount is outside approved data roots")
        return resolved

    @staticmethod
    def _write_private(path: Path, content: str) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        os.chmod(path, 0o600)

    def _inspect(self, kind: str, target: str) -> dict[str, Any]:
        if kind not in {"container", "image", "volume", "network"}:
            api_error(400, "INVALID_DOCKER_RESOURCE", "Invalid Docker resource type")
        normalized = self._checked_identifier(target, kind) if kind != "image" else target
        if kind == "image" and not IMAGE_RE.fullmatch(normalized):
            api_error(400, "INVALID_IMAGE", "Invalid image reference")
        result = self._run(["docker", kind, "inspect", normalized], timeout=30)
        if result.returncode != 0:
            api_error(404, f"DOCKER_{kind.upper()}_NOT_FOUND", f"Docker {kind} was not found")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Docker returned invalid {kind} inspection data") from error
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise RuntimeError(f"Docker returned invalid {kind} inspection data")
        return payload[0]

    def _docker(self, args: list[str], *, timeout: int = 60) -> str:
        return self._result(self._run(["docker", *args], timeout=timeout), "Docker operation failed")

    def named_resource_exists(self, kind: str, name: str) -> bool:
        commands = {
            "volume": ["volume", "ls", "--format", "{{json .}}"],
            "network": ["network", "ls", "--format", "{{json .}}"],
        }
        if kind not in commands:
            api_error(400, "INVALID_DOCKER_RESOURCE", "Invalid Docker resource type")
        normalized = self._checked_identifier(name, kind)
        return any(
            str(item.get("Name") or "") == normalized
            for item in self._json_lines(self._docker(commands[kind], timeout=30))
        )

    def _compose_tool(self) -> list[str]:
        plugin = self._run(["docker", "compose", "version"], timeout=15)
        if plugin.returncode == 0:
            return ["docker", "compose"]
        if shutil.which("docker-compose"):
            return ["docker-compose"]
        api_error(409, "DOCKER_COMPOSE_UNAVAILABLE", "Docker Compose is not installed")

    def _package_versions(self) -> tuple[str, str]:
        installed = ""
        available = ""
        if shutil.which("dpkg-query") and shutil.which("apt-cache"):
            current = self._run(["dpkg-query", "-W", "-f=${Version}", "docker-ce"], timeout=15)
            installed = current.stdout.strip() if current.returncode == 0 else ""
            policy = self._run(["apt-cache", "policy", "docker-ce"], timeout=30)
            if policy.returncode == 0:
                match = re.search(r"^\s*Candidate:\s*(\S+)", policy.stdout, re.MULTILINE)
                available = match.group(1) if match and match.group(1) != "(none)" else ""
        elif shutil.which("rpm"):
            current = self._run(["rpm", "-q", "--qf", "%{EPOCHNUM}:%{VERSION}-%{RELEASE}", "docker-ce"], timeout=15)
            installed = current.stdout.strip() if current.returncode == 0 else ""
            manager = "dnf" if shutil.which("dnf") else "yum" if shutil.which("yum") else ""
            if manager:
                listing = self._run([manager, "--showduplicates", "list", "docker-ce"], timeout=60)
                candidates = [line.split()[1] for line in listing.stdout.splitlines() if line.strip().startswith("docker-ce.") and len(line.split()) >= 2]
                available = candidates[-1] if candidates else ""
        return installed, available

    def search_registry(self, query: str, limit: int = 25) -> dict[str, Any]:
        query = query.strip()
        if len(query) < 2 or len(query) > 100 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ /-]*", query):
            api_error(400, "INVALID_REGISTRY_SEARCH", "Registry search must contain 2-100 safe characters")
        bounded_limit = min(max(limit, 1), 100)
        result = self._run(["docker", "search", "--limit", str(bounded_limit), "--format", "{{json .}}", query], timeout=30)
        if result.returncode != 0:
            api_error(502, "REGISTRY_SEARCH_FAILED", "Docker Hub search is temporarily unavailable", reason=redact(result.stderr.strip()))
        results = self._json_lines(result.stdout)
        items = []
        for item in results[:bounded_limit]:
            repository = str(item.get("Name") or "")[:255]
            if not IMAGE_RE.fullmatch(repository):
                continue
            items.append({
                "repository": repository,
                "description": str(item.get("Description") or "")[:500],
                "stars": int(item.get("StarCount") or 0),
                "official": str(item.get("IsOfficial") or "").lower() in {"true", "[ok]", "ok"},
                "automated": str(item.get("IsAutomated") or "").lower() in {"true", "[ok]", "ok"},
            })
        return {"items": items, "total": len(items), "source": "docker_hub"}

    def _inspect_container(self, name: str) -> dict[str, Any] | None:
        if not shutil.which("docker"):
            return None
        result = self._run(["docker", "inspect", name], timeout=15)
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
            return payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else None
        except (json.JSONDecodeError, IndexError):
            return None

    def get_status(self) -> ModuleStatus:
        if not shutil.which("docker"):
            return ModuleStatus(installed=False, service_state="not_installed", health=ModuleHealth.not_installed, health_message="Docker CLI is not installed")
        result = self._run(["docker", "version", "--format", "{{json .}}"], timeout=15)
        active = result.returncode == 0
        client_version = ""
        server_version = ""
        client_api_version = ""
        server_api_version = ""
        try:
            version_payload = json.loads(result.stdout)
            client_version = str((version_payload.get("Client") or {}).get("Version") or "")
            server_version = str((version_payload.get("Server") or {}).get("Version") or "")
            client_api_version = str((version_payload.get("Client") or {}).get("ApiVersion") or "")
            server_api_version = str((version_payload.get("Server") or {}).get("ApiVersion") or "")
        except (json.JSONDecodeError, AttributeError):
            pass
        containers = self._json_lines(self._run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=15).stdout) if active else []
        running = sum(1 for item in containers if str(item.get("State", "")).lower() == "running")
        compose = self._run(["docker", "compose", "version", "--short"], timeout=15) if active else None
        installed_package, available_package = self._package_versions()
        enabled = self._systemctl("docker", "is-enabled").returncode == 0
        uptime, active_since = self._service_uptime("docker") if active else (None, None)
        return ModuleStatus(
            installed=True,
            package_version=server_version or client_version or None,
            available_version=available_package or None,
            update_available=bool(installed_package and available_package and installed_package != available_package),
            service_state="active" if active else "inactive",
            service_enabled=enabled,
            services={"docker": {"state": "active" if active else "inactive", "enabled": enabled, "required": True, "uptime_seconds": uptime, "active_since": active_since}},
            health=ModuleHealth.healthy if active else ModuleHealth.degraded,
            health_message="Docker Engine is available" if active else redact(result.stderr.strip() or "Docker Engine is unavailable"),
            metrics={
                "containers": len(containers), "running_containers": running, "stopped_containers": len(containers) - running,
                "client_version": client_version, "server_version": server_version,
                "client_api_version": client_api_version, "server_api_version": server_api_version,
                "compose_version": compose.stdout.strip() if compose and compose.returncode == 0 else "",
                "installed_package_version": installed_package,
                "available_package_version": available_package,
                "requires_reboot": Path("/var/run/reboot-required").is_file(),
            },
        )

    def dashboard(self) -> dict[str, Any]:
        status = self.get_status()
        if not status.installed or status.service_state != "active":
            return {"status": status.model_dump(mode="json"), "counts": {}, "storage": [], "security": [], "updates": [], "usage": {}, "events": [], "prune_preview": {}}
        containers = self._json_lines(self._docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        images = self._json_lines(self._docker(["image", "ls", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        volumes = self._json_lines(self._docker(["volume", "ls", "--format", "{{json .}}"], timeout=30))
        networks = self._json_lines(self._docker(["network", "ls", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        storage_result = self._run(["docker", "system", "df", "--format", "{{json .}}"], timeout=30)
        storage = self._json_lines(storage_result.stdout) if storage_result.returncode == 0 else []
        info_result = self._run(["docker", "info", "--format", "{{json .}}"], timeout=30)
        try:
            info = json.loads(info_result.stdout) if info_result.returncode == 0 else {}
        except json.JSONDecodeError:
            info = {}
        security: list[dict[str, str]] = []
        warnings = info.get("SecurityOptions") if isinstance(info, dict) else []
        for option in warnings if isinstance(warnings, list) else []:
            security.append({"level": "info", "message": str(option)})
        if isinstance(info, dict) and not info.get("LiveRestoreEnabled"):
            security.append({"level": "warning", "message": "Live restore is disabled"})
        stats = self.current_stats()
        recent_events = self.events(since_seconds=900, limit=10)["items"]
        unhealthy = sum(str((item.get("Status") or "")).lower().find("unhealthy") >= 0 for item in containers)
        return {
            "status": status.model_dump(mode="json"),
            "counts": {
                "containers": len(containers), "running": sum(str(item.get("State", "")).lower() == "running" for item in containers),
                "stopped": sum(str(item.get("State", "")).lower() in {"exited", "created"} for item in containers),
                "paused": sum(str(item.get("State", "")).lower() == "paused" for item in containers),
                "unhealthy": unhealthy + sum(str(item.get("State", "")).lower() == "dead" for item in containers), "images": len(images),
                "volumes": len(volumes), "networks": len(networks),
            },
            "usage": {"cpu_percent": sum(float(item["cpu_percent"]) for item in stats), "memory_bytes": sum(int(item["memory_bytes"]) for item in stats)},
            "storage": storage,
            "engine": _redact_value(info),
            "security": security,
            "updates": [{"component": "docker-engine", "installed": status.metrics.get("installed_package_version"), "available": status.available_version, "available_update": status.update_available}],
            "events": recent_events,
            "prune_preview": self.prune_plan(["containers", "images", "networks", "volumes", "build_cache"]),
        }

    @staticmethod
    def _paginate(items: list[dict[str, Any]], *, page: int, page_size: int, search: str, sort: str, direction: str) -> dict[str, Any]:
        needle = search.lower().strip()
        if needle:
            items = [item for item in items if needle in json.dumps(item, ensure_ascii=False).lower()]
        reverse = direction == "desc"
        items.sort(key=lambda item: str(item.get(sort, item.get(sort.title(), ""))).lower(), reverse=reverse)
        total = len(items)
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}

    def containers(self, *, page: int = 1, page_size: int = 50, search: str = "", state: str = "all", sort: str = "Names", direction: str = "asc") -> dict[str, Any]:
        items = self._json_lines(self._docker(["ps", "-a", "--no-trunc", "--size", "--format", "{{json .}}"], timeout=30))
        if state != "all":
            items = [item for item in items if str(item.get("State", "")).lower() == state]
        ids = [str(item.get("ID") or "") for item in items[:500] if item.get("ID")]
        inspections: list[dict[str, Any]] = []
        if ids:
            inspected = self._run(["docker", "container", "inspect", *ids], timeout=60)
            if inspected.returncode == 0:
                try:
                    value = json.loads(inspected.stdout)
                    inspections = value if isinstance(value, list) else []
                except json.JSONDecodeError:
                    inspections = []
        inspection_by_id = {str(item.get("Id") or ""): item for item in inspections}
        statistics = self.current_stats()
        stats_by_id = {str(item.get("container_id") or ""): item for item in statistics}
        image_ids = list(dict.fromkeys(str(item.get("Image") or "") for item in inspections if item.get("Image")))
        image_digests: dict[str, str] = {}
        if image_ids:
            inspected_images = self._run(["docker", "image", "inspect", *image_ids], timeout=60)
            if inspected_images.returncode == 0:
                try:
                    for image in json.loads(inspected_images.stdout):
                        image_digests[str(image.get("Id") or "")] = str(next(iter(image.get("RepoDigests") or []), ""))
                except (json.JSONDecodeError, TypeError):
                    pass
        for item in items:
            container_id = str(item.get("ID") or "")
            inspect = next((value for key, value in inspection_by_id.items() if key == container_id or key.startswith(container_id)), {})
            config = inspect.get("Config") or {}
            host = inspect.get("HostConfig") or {}
            state_value = inspect.get("State") or {}
            labels = config.get("Labels") or {}
            stats = next((value for key, value in stats_by_id.items() if key == container_id or key.startswith(container_id)), {})
            item.update({
                "Digest": image_digests.get(str(inspect.get("Image") or ""), ""),
                "Health": (state_value.get("Health") or {}).get("Status") or "none",
                "CreatedAt": inspect.get("Created"),
                "RestartPolicy": (host.get("RestartPolicy") or {}).get("Name") or "no",
                "Networks": sorted(((inspect.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
                "Mounts": [{"type": mount.get("Type"), "name": mount.get("Name"), "destination": mount.get("Destination"), "read_only": not bool(mount.get("RW", True))} for mount in inspect.get("Mounts") or []],
                "CpuPercent": stats.get("cpu_percent", 0), "MemoryBytes": stats.get("memory_bytes", 0),
                "NetworkInputBytes": stats.get("network_input_bytes", 0), "NetworkOutputBytes": stats.get("network_output_bytes", 0),
                "BlockReadBytes": stats.get("block_read_bytes", 0), "BlockWriteBytes": stats.get("block_write_bytes", 0),
                "Management": "compose" if labels.get("com.docker.compose.project") else "webnas" if labels.get("io.webnas.managed") == "true" or labels.get("io.webnas.app") else "external",
            })
        return self._paginate(items, page=page, page_size=page_size, search=search, sort=sort, direction=direction)

    def container_details(self, target: str) -> dict[str, Any]:
        inspect = self._inspect("container", target)
        config = cast(dict[str, Any], inspect.get("Config")) if isinstance(inspect.get("Config"), dict) else {}
        host = cast(dict[str, Any], inspect.get("HostConfig")) if isinstance(inspect.get("HostConfig"), dict) else {}
        state = cast(dict[str, Any], inspect.get("State")) if isinstance(inspect.get("State"), dict) else {}
        mounts = inspect.get("Mounts") if isinstance(inspect.get("Mounts"), list) else []
        environment_keys = []
        for item in config.get("Env") or []:
            key = str(item).split("=", 1)[0]
            if key:
                environment_keys.append(key)
        safe = {
            "id": inspect.get("Id"), "name": str(inspect.get("Name") or "").removeprefix("/"), "created": inspect.get("Created"),
            "image": config.get("Image"), "image_id": inspect.get("Image"), "platform": inspect.get("Platform"), "state": state,
            "restart_policy": (host.get("RestartPolicy") or {}).get("Name"), "ports": (inspect.get("NetworkSettings") or {}).get("Ports") or {},
            "networks": ((inspect.get("NetworkSettings") or {}).get("Networks") or {}),
            "mounts": mounts, "labels": config.get("Labels") or {}, "environment_keys": sorted(environment_keys),
            "read_only": bool(host.get("ReadonlyRootfs")),
            "limits": {"memory": host.get("Memory"), "memory_swap": host.get("MemorySwap"), "nano_cpus": host.get("NanoCpus"), "pids": host.get("PidsLimit")},
            "health": state.get("Health"),
        }
        return _redact_value(safe)

    def container_settings(self, target: str) -> dict[str, Any]:
        inspect = self._inspect("container", target)
        config = inspect.get("Config") or {}
        host = inspect.get("HostConfig") or {}
        container_id = str(inspect.get("Id") or "")
        ports: list[dict[str, Any]] = []
        for raw_target, bindings in (host.get("PortBindings") or {}).items():
            target_port, protocol = str(raw_target).split("/", 1)
            for binding in bindings or []:
                if binding.get("HostPort"):
                    ports.append({"target": int(target_port), "published": int(binding["HostPort"]), "protocol": protocol, "host_ip": binding.get("HostIp") or None})
        preferences = self.manager_store.container_preferences(container_id)
        memory = int(host.get("Memory") or 0)
        cpu_shares = int(host.get("CpuShares") or 0)
        priority = "low" if cpu_shares and cpu_shares < 768 else "high" if cpu_shares > 1280 else "medium"
        portal_target = int(preferences.get("portal_port") or 0) or None
        portal_binding = next((item for item in ports if item["target"] == portal_target and item["protocol"] == "tcp"), None)
        return {
            "name": str(inspect.get("Name") or "").removeprefix("/"),
            "resource_limits_enabled": bool(memory or cpu_shares),
            "cpu_priority": priority,
            "memory_mb": memory // (1024 * 1024) if memory else None,
            "auto_restart": str((host.get("RestartPolicy") or {}).get("Name") or "no") != "no",
            "restart_policy": str((host.get("RestartPolicy") or {}).get("Name") or "no"),
            "available_ports": ports,
            "portal_enabled": bool(preferences.get("portal_enabled") and portal_binding),
            "portal_port": portal_target,
            "portal_published_port": portal_binding["published"] if portal_binding else None,
            "portal_protocol": str(preferences.get("portal_protocol") or "http"),
            "compose_managed": bool((config.get("Labels") or {}).get("com.docker.compose.project")),
        }

    def update_container_settings(self, target: str, settings: dict[str, Any]) -> dict[str, Any]:
        from ..docker_manager.models import ContainerSettingsRequest

        normalized = self._checked_identifier(target, "container")
        request = ContainerSettingsRequest.model_validate(settings)
        inspect = self._inspect("container", normalized)
        original_name = str(inspect.get("Name") or "").removeprefix("/")
        if request.name != original_name and self._inspect_container(request.name):
            api_error(409, "CONTAINER_NAME_EXISTS", "A container with the requested name already exists")
        host = inspect.get("HostConfig") or {}
        published_targets = {
            int(str(raw_target).split("/", 1)[0])
            for raw_target, bindings in (host.get("PortBindings") or {}).items()
            if str(raw_target).endswith("/tcp") and any(binding.get("HostPort") for binding in (bindings or []))
        }
        if request.portal_enabled and request.portal_port not in published_targets:
            api_error(422, "PORTAL_PORT_NOT_PUBLISHED", "The selected web portal port is not published by this container")
        cpu_shares = {"low": 256, "medium": 1024, "high": 2048}[request.cpu_priority] if request.resource_limits_enabled else 0
        memory = f"{request.memory_mb}m" if request.resource_limits_enabled and request.memory_mb else "0"
        memory_swap = "-1" if request.resource_limits_enabled else "0"
        restart = "unless-stopped" if request.auto_restart else "no"
        result = self._run(["docker", "update", "--cpu-shares", str(cpu_shares), "--memory", memory, "--memory-swap", memory_swap, "--restart", restart, normalized], timeout=120)
        self._result(result, "Could not update container settings")
        current_name = original_name
        if request.name != original_name:
            renamed = self._run(["docker", "rename", normalized, request.name], timeout=30)
            self._result(renamed, "Container settings were updated but the container could not be renamed")
            current_name = request.name
        self.manager_store.save_container_preferences(
            str(inspect.get("Id") or ""),
            portal_enabled=request.portal_enabled,
            portal_protocol=request.portal_protocol,
            portal_port=request.portal_port if request.portal_enabled else None,
        )
        return {"settings": self.container_settings(current_name), "container": self.container_details(current_name)}

    def container_processes(self, target: str) -> dict[str, Any]:
        normalized = self._checked_identifier(target, "container")
        headings = ["PID", "PPID", "USER", "STAT", "ELAPSED", "COMMAND"]
        result = self._run(["docker", "top", normalized, "-eo", "pid,ppid,user,stat,etime,comm"], timeout=30)
        self._result(result, "Could not read container processes")
        lines = result.stdout.splitlines()
        items: list[dict[str, str]] = []
        for line in lines[1:501]:
            values = re.split(r"\s+", line.strip(), maxsplit=5)
            if len(values) == len(headings):
                items.append(dict(zip(headings, values, strict=True)))
        return {"items": items, "total": len(items), "truncated": len(lines) > 501}

    def container_logs(self, target: str, *, tail: int = 500, since: str = "", until: str = "", search: str = "", level: str = "") -> dict[str, Any]:
        normalized = self._checked_identifier(target, "container")
        args = ["docker", "logs", "--timestamps", "--tail", str(min(max(tail, 1), 5000))]
        iso_re = re.compile(r"^(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?|\d+[smhd])$")
        if since:
            if not iso_re.fullmatch(since):
                api_error(422, "INVALID_LOG_TIME", "Invalid log since value")
            args += ["--since", since]
        if until:
            if not iso_re.fullmatch(until):
                api_error(422, "INVALID_LOG_TIME", "Invalid log until value")
            args += ["--until", until]
        result = self._run([*args, normalized], timeout=60)
        if result.returncode != 0:
            self._result(result, "Could not read container logs")
        needle = search.lower().strip()[:200]
        level_needle = level.lower().strip()[:32]
        lines: list[str] = []
        size = 0
        for value in (result.stdout + result.stderr).splitlines()[-5000:]:
            value = redact(value)
            if needle and needle not in value.lower():
                continue
            if level_needle and level_needle not in value.lower():
                continue
            encoded = len(value.encode("utf-8", errors="replace")) + 1
            if size + encoded > 1024 * 1024:
                break
            lines.append(value)
            size += encoded
        return {"lines": lines, "total": len(lines), "truncated": size >= 1024 * 1024}

    def current_stats(self, target: str | None = None) -> list[dict[str, Any]]:
        args = ["stats", "--no-stream", "--format", "{{json .}}"]
        if target:
            args.append(self._checked_identifier(target, "container"))
        raw = self._json_lines(self._docker(args, timeout=30))
        captured = time.time()
        result: list[dict[str, Any]] = []
        for item in raw:
            memory = str(item.get("MemUsage") or "").split("/", 1)[0].strip()
            network = str(item.get("NetIO") or "").split("/", 1)
            block = str(item.get("BlockIO") or "").split("/", 1)
            result.append({
                "captured_at": captured, "container_id": str(item.get("ID") or ""), "name": str(item.get("Name") or ""),
                "cpu_percent": _percent(item.get("CPUPerc")), "memory_percent": _percent(item.get("MemPerc")), "memory_bytes": _bytes(memory),
                "network_input_bytes": _bytes(network[0]) if network else 0, "network_output_bytes": _bytes(network[1]) if len(network) > 1 else 0,
                "block_read_bytes": _bytes(block[0]) if block else 0, "block_write_bytes": _bytes(block[1]) if len(block) > 1 else 0,
                "pids": int(item.get("PIDs") or 0),
            })
        if result:
            self.manager_store.add_stats(result)
        return result

    def events(self, *, since_seconds: int = 3600, limit: int = 200) -> dict[str, Any]:
        seconds = min(max(since_seconds, 1), 86400)
        result = self._run(["docker", "events", "--since", f"{seconds}s", "--until", "0s", "--format", "{{json .}}"], timeout=30)
        if result.returncode not in {0, 124}:
            self._result(result, "Could not read Docker events")
        items = [_redact_value(item) for item in self._json_lines(result.stdout)][-min(max(limit, 1), 1000):]
        return {"items": items, "total": len(items)}

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        commands = {
            "containers": ["ps", "-a", "--no-trunc", "--format", "{{json .}}"],
            "images": ["image", "ls", "--no-trunc", "--format", "{{json .}}"],
            "networks": ["network", "ls", "--no-trunc", "--format", "{{json .}}"],
            "volumes": ["volume", "ls", "--format", "{{json .}}"],
            "stats": ["stats", "--no-stream", "--format", "{{json .}}"],
        }
        if resource in commands:
            resource_items = self.current_stats() if resource == "stats" else self._json_lines(self._docker(commands[resource], timeout=30))
            needle = search.lower().strip()
            if needle:
                resource_items = [item for item in resource_items if needle in json.dumps(item, ensure_ascii=False).lower()]
            return {"resource": resource, "items": resource_items[:limit], "total": len(resource_items)}
        if resource == "logs":
            target = self._checked_identifier(search, "container")
            result = self._run(["docker", "logs", "--tail", str(limit), "--timestamps", target], timeout=30)
            if result.returncode != 0:
                self._result(result, "Could not read container logs")
            lines = (result.stdout + result.stderr).splitlines()
            return {"resource": resource, "items": [{"line": line} for line in lines], "total": len(lines)}
        if resource == "compose":
            compose_items: list[dict[str, Any]] = []
            for path in sorted(self.compose_dir.glob("*/compose.yaml")):
                stat = path.stat()
                compose_items.append({"name": path.parent.name, "updated_at": stat.st_mtime, "size": stat.st_size})
            return {"resource": resource, "items": compose_items[:limit], "total": len(compose_items)}
        if resource == "apps":
            app_items: list[dict[str, Any]] = []
            for app in CONTAINER_APPS:
                inspect = self._inspect_container(app.container)
                state = inspect.get("State", {}) if inspect else {}
                labels = inspect.get("Config", {}).get("Labels") or {} if inspect else {}
                configured_image = str(inspect.get("Config", {}).get("Image") or "") if inspect else ""
                managed = bool(inspect and (labels.get("io.webnas.app") == app.id or (app.id == "home-assistant" and configured_image == app.image)))
                running = bool(state.get("Running"))
                panel_target = 80 if app.id == "pihole" else 3000 if app.id == "adguard-home" else next((target for published, target, protocol in app.published_ports if published == app.panel_port and protocol == "tcp"), app.panel_port)
                panel_bindings = ((inspect.get("NetworkSettings") or {}).get("Ports") or {}).get(f"{panel_target}/tcp") or [] if inspect else []
                published_panel_port = int(panel_bindings[0]["HostPort"]) if panel_bindings and str(panel_bindings[0].get("HostPort") or "").isdigit() else app.panel_port
                app_items.append({
                    "id": app.id,
                    "name": app.name,
                    "description": app.description,
                    "category": app.category,
                    "image": app.image,
                    "container": app.container,
                    "ports": list(app.ports),
                    "version": app.version,
                    "required_secrets": list(app.required_secrets),
                    "icon": app.icon,
                    "architectures": list(app.architectures),
                    "healthcheck": app.healthcheck,
                    "dependencies": list(app.dependencies),
                    "minimum_memory_mb": app.minimum_memory_mb,
                    "documentation_url": app.documentation_url,
                    "update_strategy": app.update_strategy,
                    "backup_strategy": app.backup_strategy,
                    "uninstall_strategy": app.uninstall_strategy,
                    "panel_port": published_panel_port,
                    "installed": inspect is not None,
                    "running": running,
                    "managed": managed,
                    "status": "running" if running else "stopped" if inspect else "not_installed",
                })
            needle = search.lower().strip()
            if needle:
                app_items = [item for item in app_items if needle in f"{item['name']} {item['description']} {item['category']}".lower()]
            return {"resource": resource, "items": app_items[:limit], "total": len(app_items)}
        if resource == "events":
            return {"resource": resource, **self.events(limit=limit)}
        if resource == "registries":
            items = self.manager_store.list_registries()
            return {"resource": resource, "items": items[:limit], "total": len(items)}
        if resource == "backups":
            items = self.manager_store.list_artifacts()
            return {"resource": resource, "items": items[:limit], "total": len(items)}
        return super().list_resources(resource, limit=limit, search=search)

    def validate_compose(self, content: str) -> dict[str, Any]:
        if len(content.encode("utf-8")) > 512 * 1024:
            api_error(422, "COMPOSE_TOO_LARGE", "Compose configuration exceeds 512 KiB")
        try:
            document = yaml.safe_load(content)
        except yaml.YAMLError as error:
            api_error(422, "INVALID_COMPOSE", f"Invalid Compose YAML: {error}")
        if not isinstance(document, dict) or not isinstance(document.get("services"), dict) or not document["services"]:
            api_error(422, "INVALID_COMPOSE", "Compose configuration requires a services mapping")
        if set(document) - {"name", "version", "services", "networks", "volumes"}:
            api_error(422, "UNSAFE_COMPOSE", "Compose configuration contains unsupported root fields")
        for service_name, service in document["services"].items():
            if not SLUG_RE.fullmatch(str(service_name)) or not isinstance(service, dict) or set(service) - COMPOSE_SERVICE_FIELDS:
                api_error(422, "UNSAFE_COMPOSE", f"Service {service_name} contains unsupported fields")
            image = str(service.get("image") or "")
            if not IMAGE_RE.fullmatch(image):
                api_error(422, "INVALID_IMAGE", f"Service {service_name} requires a valid image reference")
            if str(service.get("network_mode") or "") in {"host", "none"}:
                api_error(422, "UNSAFE_COMPOSE", f"Service {service_name} uses a forbidden network mode")
            if service.get("working_dir") and (not str(service["working_dir"]).startswith("/") or ".." in str(service["working_dir"]).split("/")):
                api_error(422, "INVALID_WORKING_DIRECTORY", f"Service {service_name} uses an invalid working directory")
            if service.get("user") and not re.fullmatch(r"[0-9]{1,10}(?::[0-9]{1,10})?", str(service["user"])):
                api_error(422, "INVALID_CONTAINER_USER", f"Service {service_name} must use a numeric UID or UID:GID")
            for port in service.get("ports", []) or []:
                if not PORT_RE.fullmatch(str(port)):
                    api_error(422, "INVALID_PORT", f"Invalid port mapping in {service_name}")
            for volume in service.get("volumes", []) or []:
                raw = str(volume)
                source = raw.split(":", 1)[0]
                if source.startswith("/"):
                    resolved = Path(source).resolve(strict=False)
                    allowed = [Path("/srv"), Path("/mnt"), Path("/media"), Path(get_config().paths.data_dir)]
                    if not any(resolved == root or root in resolved.parents for root in allowed) or str(resolved) == "/var/run/docker.sock":
                        api_error(422, "UNSAFE_VOLUME", f"Host volume {source} is outside approved data roots")
                elif not SLUG_RE.fullmatch(source):
                    api_error(422, "INVALID_VOLUME", f"Invalid named volume in {service_name}")
            environment = service.get("environment") or {}
            if not isinstance(environment, (dict, list)):
                api_error(422, "INVALID_ENVIRONMENT", f"Invalid environment in {service_name}")
            if isinstance(environment, dict) and any(len(str(value).encode("utf-8")) > 8192 for value in environment.values()):
                api_error(422, "INVALID_ENVIRONMENT", f"Environment value is too large in {service_name}")
            for tmpfs in service.get("tmpfs", []) or []:
                path = str(tmpfs).split(":", 1)[0]
                if not path.startswith("/") or ".." in Path(path).parts:
                    api_error(422, "INVALID_TMPFS", f"Invalid tmpfs path in {service_name}")
        for section in ("networks", "volumes"):
            definitions = document.get(section) or {}
            if not isinstance(definitions, dict):
                api_error(422, "INVALID_COMPOSE", f"Compose {section} must be a mapping")
            for name, definition in definitions.items():
                if not SLUG_RE.fullmatch(str(name)) or definition not in (None, {}) and not isinstance(definition, dict):
                    api_error(422, "INVALID_COMPOSE", f"Invalid {section} definition")
                if isinstance(definition, dict) and set(definition) - {"name", "driver", "internal", "labels", "ipam", "external"}:
                    api_error(422, "UNSAFE_COMPOSE", f"Unsupported {section} options")
                if isinstance(definition, dict) and definition.get("driver") not in {None, "bridge", "local"}:
                    api_error(422, "UNSAFE_COMPOSE", f"Unsupported {section} driver")
        return document

    def save_compose(self, project: str, content: str, *, environment: dict[str, str] | None = None, secret_environment: dict[str, str] | None = None, actor: str = "", description: str = "") -> dict[str, Any]:
        if not SLUG_RE.fullmatch(project):
            api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
        document = self.validate_compose(content)
        directory = self.compose_dir / project
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = directory / "compose.yaml"
        tmp = directory / "compose.tmp"
        with tmp.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(document, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        public_environment = environment or {}
        private_environment = secret_environment
        secret_path = directory / ".env.secrets"
        self._write_private(directory / ".env", "".join(f"{key}={value}\n" for key, value in public_environment.items()))
        if private_environment is not None:
            self._write_private(secret_path, "".join(f"{key}={value}\n" for key, value in private_environment.items()))
        history_dir = directory / "history"
        history_dir.mkdir(mode=0o700, exist_ok=True)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        revision = f"{int(time.time() * 1000)}-{digest[:12]}"
        revision_path = history_dir / f"{revision}.json"
        self._write_private(revision_path, json.dumps({
            "id": revision, "created_at": time.time(), "created_by": actor, "description": description[:200],
            "checksum": digest, "content": target.read_text(encoding="utf-8"), "environment": public_environment,
            "secrets_omitted": secret_path.is_file() and bool(secret_path.stat().st_size),
        }, ensure_ascii=False, indent=2))
        history = sorted(history_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in history[50:]:
            stale.unlink(missing_ok=True)
        return {"name": project, "updated_at": target.stat().st_mtime, "size": target.stat().st_size, "revision": revision, "secrets_configured": secret_path.is_file() and bool(secret_path.stat().st_size)}

    def get_compose(self, project: str) -> dict[str, Any]:
        if not SLUG_RE.fullmatch(project):
            api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
        target = self.compose_dir / project / "compose.yaml"
        if not target.is_file():
            api_error(404, "COMPOSE_PROJECT_NOT_FOUND", "Compose project not found")
        environment: dict[str, str] = {}
        env_path = target.parent / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    environment[key] = value
        return {
            "name": project, "content": target.read_text(encoding="utf-8", errors="replace"), "updated_at": target.stat().st_mtime,
            "size": target.stat().st_size, "environment": environment, "secrets_configured": (target.parent / ".env.secrets").is_file() and bool((target.parent / ".env.secrets").stat().st_size),
        }

    def compose_history(self, project: str) -> list[dict[str, Any]]:
        self.get_compose(project)
        history_dir = self.compose_dir / project / "history"
        result: list[dict[str, Any]] = []
        for path in sorted(history_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                item.pop("content", None)
                item.pop("environment", None)
                result.append(item)
            except (OSError, ValueError):
                continue
        return result

    def compose_secret_environment(self, project: str) -> dict[str, str]:
        if not SLUG_RE.fullmatch(project):
            api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
        values: dict[str, str] = {}
        path = self.compose_dir / project / ".env.secrets"
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    values[key] = value
        return values

    def rollback_compose(self, project: str, revision: str, actor: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]{10,16}-[a-f0-9]{12}", revision):
            api_error(400, "INVALID_COMPOSE_REVISION", "Invalid Compose revision")
        path = self.compose_dir / project / "history" / f"{revision}.json"
        if not path.is_file():
            api_error(404, "COMPOSE_REVISION_NOT_FOUND", "Compose revision not found")
        item = json.loads(path.read_text(encoding="utf-8"))
        validation = self.validate_compose_runtime(str(item["content"]), environment=dict(item.get("environment") or {}), secret_environment=self.compose_secret_environment(project))
        if not validation["valid"]:
            api_error(422, "COMPOSE_VALIDATION_FAILED", "docker compose config rejected the selected revision", errors=validation["errors"])
        return self.save_compose(project, str(item["content"]), environment=dict(item.get("environment") or {}), actor=actor, description=f"Rollback to {revision}")

    def validate_compose_runtime(
        self,
        content: str,
        *,
        environment: dict[str, str] | None = None,
        secret_environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        model = self.validate_compose(content)
        with tempfile.TemporaryDirectory(prefix="compose-validate-", dir=self.manager_store.inputs_dir) as directory_value:
            directory = Path(directory_value)
            os.chmod(directory, 0o700)
            compose_file = directory / "compose.yaml"
            env_file = directory / ".env"
            self._write_private(compose_file, yaml.safe_dump(model, sort_keys=False, allow_unicode=True))
            combined = {**(environment or {}), **(secret_environment or {})}
            self._write_private(env_file, "".join(f"{key}={value}\n" for key, value in combined.items()))
            result = self._run([*self._compose_tool(), "--ansi", "never", "--env-file", str(env_file), "-f", str(compose_file), "config", "--quiet"], timeout=60)
        return {"valid": result.returncode == 0, "errors": [] if result.returncode == 0 else [redact(result.stderr.strip() or result.stdout.strip())], "model": model}

    def compose_plan(self, project: str) -> dict[str, Any]:
        current = self.get_compose(project)
        secret_environment = self.compose_secret_environment(project)
        validation = self.validate_compose_runtime(current["content"], environment=current["environment"], secret_environment=secret_environment)
        return {
            "valid": validation["valid"],
            "errors": validation["errors"],
            "steps": ["Validate Compose model", "Pull referenced images", "Reconcile containers", "Verify project containers"],
            "project": current["name"],
        }

    def compose_status(self, project: str) -> dict[str, Any]:
        current = self.get_compose(project)
        file = self.compose_dir / project / "compose.yaml"
        env_file = file.parent / f".env.read-{secrets.token_hex(6)}"
        self._write_private(env_file, "".join(f"{key}={value}\n" for key, value in {**current["environment"], **self.compose_secret_environment(project)}.items()))
        try:
            result = self._run([*self._compose_tool(), "--ansi", "never", "--env-file", str(env_file), "-f", str(file), "-p", project, "ps", "--format", "json"], timeout=60)
        finally:
            env_file.unlink(missing_ok=True)
        self._result(result, "Could not read Compose project status")
        try:
            parsed = json.loads(result.stdout)
            items = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
        except json.JSONDecodeError:
            items = self._json_lines(result.stdout)
        return {"project": current["name"], "items": _redact_value(items), "total": len(items)}

    def compose_logs(self, project: str, *, service: str = "", tail: int = 500, since: str = "") -> dict[str, Any]:
        current = self.get_compose(project)
        file = self.compose_dir / project / "compose.yaml"
        env_file = file.parent / f".env.read-{secrets.token_hex(6)}"
        self._write_private(env_file, "".join(f"{key}={value}\n" for key, value in {**current["environment"], **self.compose_secret_environment(project)}.items()))
        command = [*self._compose_tool(), "--ansi", "never", "--env-file", str(env_file), "-f", str(file), "-p", project, "logs", "--no-color", "--timestamps", "--tail", str(min(max(tail, 1), 5000))]
        if since:
            if not re.fullmatch(r"(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?|\d+[smhd])", since):
                api_error(422, "INVALID_LOG_TIME", "Invalid Compose log since value")
            command += ["--since", since]
        if service:
            command.append(self._checked_identifier(service, "service"))
        try:
            result = self._run(command, timeout=60)
        finally:
            env_file.unlink(missing_ok=True)
        self._result(result, "Could not read Compose logs")
        lines: list[str] = []
        size = 0
        for line in (result.stdout + result.stderr).splitlines()[-5000:]:
            safe = redact(line)
            size += len(safe.encode("utf-8", errors="replace")) + 1
            if size > 1024 * 1024:
                break
            lines.append(safe)
        return {"project": project, "service": service, "lines": lines, "total": len(lines), "truncated": size > 1024 * 1024}

    def images(self, *, page: int = 1, page_size: int = 50, search: str = "", sort: str = "Repository", direction: str = "asc") -> dict[str, Any]:
        items = self._json_lines(self._docker(["image", "ls", "--digests", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        containers = self._json_lines(self._docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        for item in items:
            image_id = str(item.get("ID") or "")
            reference = f"{item.get('Repository')}:{item.get('Tag')}"
            item["consumers"] = [container.get("Names") for container in containers if str(container.get("ImageID") or "") == image_id or str(container.get("Image") or "") == reference]
        return self._paginate(items, page=page, page_size=page_size, search=search, sort=sort, direction=direction)

    def image_details(self, target: str) -> dict[str, Any]:
        inspect = self._inspect("image", target)
        consumers = self._json_lines(self._docker(["ps", "-a", "--filter", f"ancestor={target}", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        return _redact_value({
            "id": inspect.get("Id"), "repo_tags": inspect.get("RepoTags") or [], "repo_digests": inspect.get("RepoDigests") or [],
            "created": inspect.get("Created"), "size": inspect.get("Size"), "architecture": inspect.get("Architecture"), "os": inspect.get("Os"),
            "labels": (inspect.get("Config") or {}).get("Labels") or {}, "consumers": consumers,
        })

    def volumes(self, *, page: int = 1, page_size: int = 50, search: str = "", sort: str = "Name", direction: str = "asc") -> dict[str, Any]:
        items = self._json_lines(self._docker(["volume", "ls", "--format", "{{json .}}"], timeout=30))
        for item in items:
            name = str(item.get("Name") or "")
            users = self._json_lines(self._docker(["ps", "-a", "--filter", f"volume={name}", "--format", "{{json .}}"], timeout=30)) if name else []
            item["consumers"] = [user.get("Names") for user in users]
        return self._paginate(items, page=page, page_size=page_size, search=search, sort=sort, direction=direction)

    def volume_details(self, target: str) -> dict[str, Any]:
        inspect = self._inspect("volume", target)
        users = self._json_lines(self._docker(["ps", "-a", "--filter", f"volume={target}", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        inspect.pop("Mountpoint", None)
        return _redact_value({**inspect, "consumers": users, "size": None})

    def networks(self, *, page: int = 1, page_size: int = 50, search: str = "", sort: str = "Name", direction: str = "asc") -> dict[str, Any]:
        items = self._json_lines(self._docker(["network", "ls", "--no-trunc", "--format", "{{json .}}"], timeout=30))
        ids = [str(item.get("ID") or item.get("Name") or "") for item in items[:500] if item.get("ID") or item.get("Name")]
        inspections: list[dict[str, Any]] = []
        if ids:
            inspected = self._run(["docker", "network", "inspect", *ids], timeout=60)
            if inspected.returncode == 0:
                try:
                    value = json.loads(inspected.stdout)
                    inspections = value if isinstance(value, list) else []
                except json.JSONDecodeError:
                    inspections = []
        inspection_by_id = {str(item.get("Id") or ""): item for item in inspections}
        inspection_by_name = {str(item.get("Name") or ""): item for item in inspections}
        enriched: list[dict[str, Any]] = []
        for item in items:
            detail = inspection_by_id.get(str(item.get("ID") or "")) or inspection_by_name.get(str(item.get("Name") or "")) or {}
            ipam = detail.get("IPAM") if isinstance(detail.get("IPAM"), dict) else {}
            configs = ipam.get("Config") if isinstance(ipam, dict) and isinstance(ipam.get("Config"), list) else []
            containers = detail.get("Containers") if isinstance(detail.get("Containers"), dict) else {}
            attached = [
                {
                    "id": str(container_id),
                    "name": str(value.get("Name") or ""),
                    "endpoint_id": str(value.get("EndpointID") or ""),
                    "mac_address": str(value.get("MacAddress") or ""),
                    "ipv4_address": str(value.get("IPv4Address") or ""),
                    "ipv6_address": str(value.get("IPv6Address") or ""),
                }
                for container_id, value in containers.items()
                if isinstance(value, dict)
            ]
            name = str(detail.get("Name") or item.get("Name") or "")
            enriched.append({
                **item,
                "Name": name,
                "ID": str(detail.get("Id") or item.get("ID") or ""),
                "Driver": str(detail.get("Driver") or item.get("Driver") or ""),
                "Scope": str(detail.get("Scope") or item.get("Scope") or ""),
                "IPv6": bool(detail.get("EnableIPv6")),
                "subnets": [str(config.get("Subnet")) for config in configs if isinstance(config, dict) and config.get("Subnet")],
                "gateways": [str(config.get("Gateway")) for config in configs if isinstance(config, dict) and config.get("Gateway")],
                "ip_ranges": [str(config.get("IPRange")) for config in configs if isinstance(config, dict) and config.get("IPRange")],
                "container_count": len(attached),
                "containers": attached,
                "internal": bool(detail.get("Internal")),
                "attachable": bool(detail.get("Attachable")),
                "system": name in SYSTEM_NETWORKS,
                "options": detail.get("Options") if isinstance(detail.get("Options"), dict) else {},
                "labels": detail.get("Labels") if isinstance(detail.get("Labels"), dict) else {},
            })
        return self._paginate(enriched, page=page, page_size=page_size, search=search, sort=sort, direction=direction)

    def network_details(self, target: str) -> dict[str, Any]:
        inspect = self._inspect("network", target)
        containers = cast(dict[str, Any], inspect.get("Containers")) if isinstance(inspect.get("Containers"), dict) else {}
        return _redact_value({
            "id": inspect.get("Id"), "name": inspect.get("Name"), "driver": inspect.get("Driver"), "scope": inspect.get("Scope"),
            "internal": inspect.get("Internal"), "attachable": inspect.get("Attachable"), "ipv6": inspect.get("EnableIPv6"),
            "ipam": inspect.get("IPAM"), "labels": inspect.get("Labels") or {},
            "containers": [{"id": key, **(value if isinstance(value, dict) else {})} for key, value in containers.items()],
            "system": str(inspect.get("Name") or "") in SYSTEM_NETWORKS,
        })

    def network_container_candidates(self, target: str) -> dict[str, Any]:
        network = self._checked_identifier(target, "network")
        if network in SYSTEM_NETWORKS:
            api_error(403, "SYSTEM_NETWORK_PROTECTED", "Docker system networks cannot be modified")
        detail = self._inspect("network", network)
        attached = detail.get("Containers") if isinstance(detail.get("Containers"), dict) else {}
        attached_ids = {str(value) for value in attached}
        containers = self._json_lines(
            self._docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=30)
        )
        items = [
            {
                "id": str(item.get("ID") or ""),
                "name": str(item.get("Names") or ""),
                "state": str(item.get("State") or ""),
                "connected": any(
                    identifier and (
                        identifier == str(item.get("ID") or "")
                        or str(item.get("ID") or "").startswith(identifier)
                        or identifier.startswith(str(item.get("ID") or ""))
                    )
                    for identifier in attached_ids
                ),
            }
            for item in containers
            if item.get("ID") and item.get("Names")
        ]
        items.sort(key=lambda item: item["name"].lower())
        return {"items": items, "total": len(items), "network": network}

    def default_bridge_config(self) -> dict[str, Any]:
        config = self.get_config().get("config") or {}
        if not isinstance(config, dict):
            config = {}
        bip = str(config.get("bip") or "")
        ipv4_subnet: str | None = None
        ipv4_gateway: str | None = None
        if bip:
            try:
                interface = ipaddress.ip_interface(bip)
                if interface.version == 4:
                    ipv4_subnet = str(interface.network)
                    ipv4_gateway = str(interface.ip)
            except ValueError:
                pass
        return {
            "ipv4_mode": "manual" if ipv4_subnet and ipv4_gateway else "auto",
            "ipv4_subnet": ipv4_subnet,
            "ipv4_ip_range": str(config.get("fixed-cidr") or "") or None,
            "ipv4_gateway": ipv4_gateway or (str(config.get("default-gateway") or "") or None),
            "ipv6_mode": "manual" if config.get("ipv6") and config.get("fixed-cidr-v6") else "none",
            "ipv6_subnet": str(config.get("fixed-cidr-v6") or "") or None,
            "ipv6_gateway": str(config.get("default-gateway-v6") or "") or None,
            "disable_ip_masquerade": config.get("ip-masq") is False,
        }

    def merge_default_bridge_config(self, settings: dict[str, Any]) -> dict[str, Any]:
        from ..docker_manager.models import DefaultBridgeConfigRequest

        request = DefaultBridgeConfigRequest.model_validate(settings)
        current = self.get_config()
        if not current.get("valid", False):
            api_error(409, "INVALID_EXISTING_DAEMON_CONFIG", "The existing daemon.json must be repaired before changing the default bridge")
        config = dict(current.get("config") or {})
        managed = {
            "bip", "fixed-cidr", "default-gateway", "ipv6", "fixed-cidr-v6",
            "default-gateway-v6", "ip-masq",
        }
        for key in managed:
            config.pop(key, None)
        if request.ipv4_mode == "manual":
            network = ipaddress.ip_network(str(request.ipv4_subnet), strict=False)
            config["bip"] = f"{request.ipv4_gateway}/{network.prefixlen}"
            if request.ipv4_ip_range:
                config["fixed-cidr"] = request.ipv4_ip_range
        if request.ipv6_mode == "manual":
            config["ipv6"] = True
            config["fixed-cidr-v6"] = request.ipv6_subnet
            if request.ipv6_gateway:
                config["default-gateway-v6"] = request.ipv6_gateway
        if request.disable_ip_masquerade:
            config["ip-masq"] = False
        return config

    def prune_plan(self, resources: list[str]) -> dict[str, Any]:
        allowed = {"containers", "images", "networks", "volumes", "build_cache"}
        selected = list(dict.fromkeys(item for item in resources if item in allowed))
        if not selected:
            return {"resources": [], "items": [], "estimated_reclaimable": 0}
        items: list[dict[str, Any]] = []
        if "containers" in selected:
            stopped = self._json_lines(self._docker(["ps", "-a", "--filter", "status=exited", "--format", "{{json .}}"], timeout=30))
            items += [{"type": "container", "id": item.get("ID"), "name": item.get("Names"), "size": item.get("Size")} for item in stopped]
        if "images" in selected:
            dangling = self._json_lines(self._docker(["image", "ls", "--filter", "dangling=true", "--format", "{{json .}}"], timeout=30))
            items += [{"type": "image", "id": item.get("ID"), "name": f"{item.get('Repository')}:{item.get('Tag')}", "size": item.get("Size")} for item in dangling]
        if "networks" in selected:
            networks = self._json_lines(self._docker(["network", "ls", "--filter", "type=custom", "--format", "{{json .}}"], timeout=30))
            for item in networks:
                try:
                    detail = self._inspect("network", str(item.get("ID") or item.get("Name")))
                except Exception:
                    continue
                if not detail.get("Containers"):
                    items.append({"type": "network", "id": item.get("ID"), "name": item.get("Name"), "size": 0})
        if "volumes" in selected:
            dangling_volumes = self._json_lines(self._docker(["volume", "ls", "--filter", "dangling=true", "--format", "{{json .}}"], timeout=30))
            items += [{"type": "volume", "id": item.get("Name"), "name": item.get("Name"), "size": None} for item in dangling_volumes]
        return {"resources": selected, "items": items[:1000], "total": len(items), "estimated_reclaimable": sum(_bytes(str(item.get("size") or "0").split("(", 1)[0]) for item in items)}

    def _volume_mountpoint(self, volume: str) -> Path:
        inspect = self._inspect("volume", volume)
        mountpoint = Path(str(inspect.get("Mountpoint") or "")).resolve(strict=True)
        allowed = Path("/var/lib/docker/volumes").resolve(strict=False)
        if allowed not in mountpoint.parents:
            api_error(409, "VOLUME_PATH_UNAVAILABLE", "Volume data is not in the managed Docker volume directory")
        return mountpoint

    @staticmethod
    def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
        root = destination.resolve()
        members = archive.getmembers()
        for member in members:
            target = (destination / member.name).resolve(strict=False)
            if member.isdev() or member.issym() or member.islnk() or not (target == root or root in target.parents):
                api_error(422, "UNSAFE_ARCHIVE", "Backup archive contains an unsafe entry")
        archive.extractall(destination, members=members, filter="data")

    def _volume_archive(self, volume: str, actor: str, *, display_name: str | None = None) -> dict[str, Any]:
        source = self._volume_mountpoint(volume)
        filename = f"volume-{int(time.time())}-{hashlib.sha256(volume.encode()).hexdigest()[:12]}.tar.gz"
        target = self.manager_store.artifacts_dir / filename
        with tarfile.open(target, "w:gz") as archive:
            archive.add(source, arcname="data", recursive=True)
        os.chmod(target, 0o600)
        return self.manager_store.register_artifact(target, kind="volume_backup", display_name=display_name or f"{volume}.tar.gz", actor=actor, metadata={"volume": volume, "secrets_omitted": True})

    def _container_backup(self, target: str, actor: str, log: LogCallback) -> dict[str, Any]:
        normalized = self._checked_identifier(target, "container")
        inspect = self._inspect("container", normalized)
        name = str(inspect.get("Name") or "").removeprefix("/")
        definition = self._container_definition(inspect, name=name)
        environment_keys = sorted((definition.pop("secret_environment", {}) or {}).keys())
        filename = f"backup-{int(time.time())}-{hashlib.sha256(name.encode()).hexdigest()[:12]}.tar.gz"
        target_path = self.manager_store.artifacts_dir / filename
        with tempfile.TemporaryDirectory(prefix="container-backup-", dir=self.manager_store.artifacts_dir) as raw_temp:
            temporary = Path(raw_temp)
            rootfs = temporary / "rootfs.tar"
            export = self._run(["docker", "container", "export", "--output", str(rootfs), normalized], timeout=3600)
            for line in (export.stdout + export.stderr).splitlines()[-200:]:
                log("stdout" if export.returncode == 0 else "stderr", redact(line))
            self._result(export, "Could not export container filesystem")
            volume_names = [
                str(item.get("Name"))
                for item in inspect.get("Mounts") or []
                if item.get("Type") == "volume" and item.get("Name")
            ]
            metadata: dict[str, Any] = {
                "format": 1, "container": name, "created_at": time.time(), "definition": definition,
                "environment_keys": environment_keys, "secrets_omitted": True,
                "image_config": {key: (inspect.get("Config") or {}).get(key) for key in ("Cmd", "Entrypoint", "WorkingDir", "User")},
                "volumes": volume_names,
            }
            with tarfile.open(target_path, "w:gz") as archive:
                info = tarfile.TarInfo("manifest.json")
                content = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
                info.size = len(content)
                info.mode = 0o600
                info.mtime = int(time.time())
                archive.addfile(info, io.BytesIO(content))
                archive.add(rootfs, arcname="rootfs.tar", recursive=False)
                for volume in volume_names:
                    archive.add(self._volume_mountpoint(volume), arcname=f"volumes/{volume}", recursive=True)
        os.chmod(target_path, 0o600)
        return self.manager_store.register_artifact(target_path, kind="container_backup", display_name=f"{name}-webnas-backup.tar.gz", actor=actor, metadata={"container": name, "environment_keys": environment_keys, "secrets_omitted": True})

    def _restore_container_backup(self, backup_id: str, new_name: str, actor: str, log: LogCallback, secret_environment: dict[str, str] | None = None) -> dict[str, Any]:
        path, artifact = self.manager_store.artifact(backup_id)
        if artifact["kind"] != "container_backup":
            api_error(409, "INVALID_BACKUP_KIND", "Artifact is not a WebNAS container backup")
        name = self._checked_identifier(new_name, "container name")
        if self._inspect_container(name):
            api_error(409, "CONTAINER_NAME_EXISTS", "Restore target container already exists")
        with tempfile.TemporaryDirectory(prefix="container-restore-", dir=self.manager_store.artifacts_dir) as raw_temp:
            temporary = Path(raw_temp)
            with tarfile.open(path, "r:gz") as archive:
                self._safe_extract(archive, temporary)
            try:
                metadata = json.loads((temporary / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise RuntimeError("Container backup manifest is invalid") from error
            if metadata.get("format") != 1 or not (temporary / "rootfs.tar").is_file():
                api_error(422, "INVALID_CONTAINER_BACKUP", "Container backup format is not supported")
            required_secrets = [str(key) for key in metadata.get("environment_keys") or []]
            supplied_secrets = secret_environment or {}
            missing_secrets = [key for key in required_secrets if not supplied_secrets.get(key)]
            if missing_secrets:
                api_error(422, "RESTORE_SECRETS_REQUIRED", "Re-enter the secret environment values omitted from the backup", fields=missing_secrets)
            image = f"webnas-restored/{name}:{backup_id[:12]}"
            import_args = ["docker", "image", "import"]
            image_config = metadata.get("image_config") if isinstance(metadata.get("image_config"), dict) else {}
            if image_config.get("Cmd"):
                import_args += ["--change", f"CMD {json.dumps(image_config['Cmd'])}"]
            if image_config.get("Entrypoint"):
                import_args += ["--change", f"ENTRYPOINT {json.dumps(image_config['Entrypoint'])}"]
            if image_config.get("WorkingDir"):
                import_args += ["--change", f"WORKDIR {image_config['WorkingDir']}"]
            if image_config.get("User"):
                import_args += ["--change", f"USER {image_config['User']}"]
            import_args += [str(temporary / "rootfs.tar"), image]
            imported = self._run(import_args, timeout=3600)
            self._result(imported, "Could not import container backup filesystem")
            definition = dict(metadata.get("definition") or {})
            definition["name"] = name
            definition["image"] = image
            definition["pull_policy"] = "never"
            mounts = []
            restored_volumes: list[str] = []
            for mount in definition.get("mounts") or []:
                if mount.get("type") != "volume":
                    mounts.append(mount)
                    continue
                original = self._checked_identifier(mount.get("source"), "volume")
                restored = f"{name}-{hashlib.sha256(original.encode()).hexdigest()[:8]}"
                create = self._run(["docker", "volume", "create", restored], timeout=120)
                self._result(create, "Could not create restored volume")
                source = temporary / "volumes" / original
                if source.is_dir():
                    destination = self._volume_mountpoint(restored)
                    for item in source.iterdir():
                        if item.is_dir():
                            shutil.copytree(item, destination / item.name, symlinks=False)
                        elif item.is_file() and not item.is_symlink():
                            shutil.copy2(item, destination / item.name, follow_symlinks=False)
                mount["source"] = restored
                mounts.append(mount)
                restored_volumes.append(restored)
            definition["mounts"] = mounts
            container = self._run_container(definition, supplied_secrets, log)
        return {"container": container, "backup_id": backup_id, "restored_volumes": restored_volumes, "secrets_reentered": sorted(supplied_secrets), "actor": actor}

    def _restore_volume(self, volume: str, backup_id: str) -> dict[str, Any]:
        path, metadata = self.manager_store.artifact(backup_id)
        if metadata["kind"] != "volume_backup":
            api_error(409, "INVALID_BACKUP_KIND", "Artifact is not a volume backup")
        destination = self._volume_mountpoint(volume)
        if any(destination.iterdir()):
            api_error(409, "VOLUME_NOT_EMPTY", "Restore requires an empty target volume")
        with tarfile.open(path, "r:gz") as archive:
            data_members = []
            for member in archive.getmembers():
                if member.name == "data":
                    continue
                if member.name.startswith("data/"):
                    member.name = member.name.removeprefix("data/")
                    data_members.append(member)
            for member in data_members:
                target = (destination / member.name).resolve(strict=False)
                if member.isdev() or member.issym() or member.islnk() or destination.resolve() not in target.parents:
                    api_error(422, "UNSAFE_ARCHIVE", "Backup archive contains an unsafe entry")
            archive.extractall(destination, members=data_members, filter="data")
        return {"volume": volume, "backup_id": backup_id, "restored": True}

    def _container_definition(self, inspect: dict[str, Any], *, name: str, image: str | None = None) -> dict[str, Any]:
        from ..docker_manager.models import ContainerCreateRequest

        config = inspect.get("Config") or {}
        host = inspect.get("HostConfig") or {}
        if host.get("Privileged") or host.get("NetworkMode") in {"host", "none"} or host.get("PidMode") or host.get("IpcMode") == "host" or host.get("Devices") or host.get("CapAdd"):
            api_error(409, "UNSAFE_CONTAINER_CONFIGURATION", "Container uses high-risk settings that cannot be duplicated or recreated")
        env: dict[str, str] = {}
        for raw in config.get("Env") or []:
            if "=" in str(raw):
                key, value = str(raw).split("=", 1)
                env[key] = value
        ports: list[dict[str, Any]] = []
        for target, bindings in (host.get("PortBindings") or {}).items():
            port, protocol = str(target).split("/", 1)
            for binding in bindings or []:
                if binding.get("HostPort"):
                    ports.append({"host_ip": binding.get("HostIp") or None, "published": int(binding["HostPort"]), "target": int(port), "protocol": protocol})
        mounts: list[dict[str, Any]] = []
        for mount in inspect.get("Mounts") or []:
            kind = str(mount.get("Type") or "")
            if kind not in {"volume", "bind", "tmpfs"}:
                continue
            mounts.append({"type": kind, "source": "" if kind == "tmpfs" else mount.get("Name") if kind == "volume" else mount.get("Source"), "target": mount.get("Destination"), "read_only": not bool(mount.get("RW", True))})
        network_names = list(((inspect.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        limits = {"cpus": float(host.get("NanoCpus") or 0) / 1_000_000_000 or None, "memory_mb": int(host.get("Memory") or 0) // (1024 * 1024) or None, "memory_swap_mb": int(host.get("MemorySwap") or 0) // (1024 * 1024) or None, "pids": host.get("PidsLimit") if int(host.get("PidsLimit") or 0) >= 16 else None}
        return ContainerCreateRequest.model_validate({
            "name": name, "image": image or config.get("Image"), "pull_policy": "never", "environment": {}, "secret_environment": env,
            "ports": ports, "mounts": mounts, "network": next((item for item in network_names if item not in SYSTEM_NETWORKS), "bridge"),
            "hostname": config.get("Hostname") or None, "working_dir": config.get("WorkingDir") or None,
            "user": config.get("User") if re.fullmatch(r"[0-9]{1,10}(?::[0-9]{1,10})?", str(config.get("User") or "")) else None,
            "restart_policy": (host.get("RestartPolicy") or {}).get("Name") or "no", "limits": limits,
            "labels": {key: value for key, value in (config.get("Labels") or {}).items() if not key.startswith("com.docker.compose.")},
            "read_only": bool(host.get("ReadonlyRootfs")), "init": host.get("Init") is not False,
            "auto_start": bool((inspect.get("State") or {}).get("Running")),
        }).model_dump(mode="json")

    def generate_compose(self, target: str) -> dict[str, Any]:
        inspect = self._inspect("container", target)
        name = str(inspect.get("Name") or "").removeprefix("/")
        definition = self._container_definition(inspect, name=name)
        environment = {key: f"${{{key}}}" for key in sorted((definition.pop("secret_environment", {}) or {}).keys())}
        service: dict[str, Any] = {
            "image": definition["image"], "container_name": name, "restart": definition["restart_policy"],
            "environment": environment, "labels": definition.get("labels") or {}, "read_only": bool(definition.get("read_only")),
        }
        for key in ("hostname", "working_dir", "user"):
            if definition.get(key):
                service[key] = definition[key]
        service["ports"] = [f"{item['host_ip'] + ':' if item.get('host_ip') else ''}{item['published']}:{item['target']}/{item['protocol']}" for item in definition.get("ports") or []]
        service["volumes"] = [f"{item.get('source', '')}:{item['target']}{':ro' if item.get('read_only') else ''}" for item in definition.get("mounts") or [] if item["type"] != "tmpfs"]
        tmpfs = [item["target"] for item in definition.get("mounts") or [] if item["type"] == "tmpfs"]
        if tmpfs:
            service["tmpfs"] = tmpfs
        if definition.get("network") != "bridge":
            service["networks"] = [definition["network"]]
        document: dict[str, Any] = {"services": {name: service}}
        named_volumes: dict[str, dict[str, Any]] = {
            item["source"]: {} for item in definition.get("mounts") or [] if item["type"] == "volume"
        }
        if named_volumes:
            document["volumes"] = named_volumes
        if definition.get("network") != "bridge":
            document["networks"] = {definition["network"]: {"external": True}}
        content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
        self.validate_compose(content)
        return {"content": content, "secrets_omitted": bool(environment), "environment_keys": sorted(environment)}

    def _run_container(self, definition: dict[str, Any], secrets_payload: dict[str, str], log: LogCallback) -> dict[str, Any]:
        from ..docker_manager.models import ContainerCreateRequest

        request = ContainerCreateRequest.model_validate({**definition, "secret_environment": secrets_payload})
        if self._inspect_container(request.name):
            api_error(409, "CONTAINER_NAME_EXISTS", "A container with this name already exists")
        if request.pull_policy in {"always", "missing"}:
            inspect = self._run(["docker", "image", "inspect", request.image], timeout=30)
            if request.pull_policy == "always" or inspect.returncode != 0:
                pull = self._run(["docker", "pull", request.image], timeout=1800)
                for line in (pull.stdout + pull.stderr).splitlines()[-500:]:
                    log("stdout" if pull.returncode == 0 else "stderr", redact(line))
                self._result(pull, "Could not pull container image")
        env_path = self.manager_store.inputs_dir / f"env-{hashlib.sha256((request.name + str(time.time())).encode()).hexdigest()[:20]}.list"
        self._write_private(env_path, "".join(f"{key}={value}\n" for key, value in {**request.environment, **request.secret_environment}.items()))
        args = ["docker", "run", "-d"] if request.auto_start else ["docker", "create"]
        args += ["--name", request.name, "--restart", request.restart_policy, "--network", request.network, "--label", "io.webnas.managed=true", "--env-file", str(env_path)]
        for alias in request.network_aliases:
            args += ["--network-alias", alias]
        if request.hostname:
            args += ["--hostname", request.hostname]
        if request.working_dir:
            args += ["--workdir", request.working_dir]
        if request.user:
            args += ["--user", request.user]
        if request.init:
            args.append("--init")
        if request.read_only:
            args.append("--read-only")
        for port in request.ports:
            host = f"{port.host_ip}:" if port.host_ip else ""
            args += ["--publish", f"{host}{port.published}:{port.target}/{port.protocol}"]
        for mount in request.mounts:
            if mount.type == "bind":
                source = self._allowed_bind_path(mount.source)
                source.mkdir(parents=True, exist_ok=True)
                spec = f"type=bind,src={source},dst={mount.target}"
            elif mount.type == "volume":
                spec = f"type=volume,src={mount.source},dst={mount.target}"
            else:
                spec = f"type=tmpfs,dst={mount.target}"
                if mount.tmpfs_size_mb:
                    spec += f",tmpfs-size={mount.tmpfs_size_mb * 1024 * 1024}"
            if mount.read_only:
                spec += ",readonly"
            args += ["--mount", spec]
        for key, value in request.labels.items():
            args += ["--label", f"{key}={value}"]
        if request.limits.cpus:
            args += ["--cpus", str(request.limits.cpus)]
        if request.limits.memory_mb:
            args += ["--memory", f"{request.limits.memory_mb}m"]
        if request.limits.memory_swap_mb:
            args += ["--memory-swap", f"{request.limits.memory_swap_mb}m"]
        if request.limits.pids:
            args += ["--pids-limit", str(request.limits.pids)]
        if request.healthcheck.type != "none" and request.healthcheck.port:
            # The command is generated entirely from typed port/path values; raw executable input is never accepted.
            command = f"wget -q -O /dev/null http://127.0.0.1:{request.healthcheck.port}{request.healthcheck.path}" if request.healthcheck.type == "http" else f"nc -z 127.0.0.1 {request.healthcheck.port}"
            args += ["--health-cmd", command, "--health-interval", f"{request.healthcheck.interval_seconds}s", "--health-timeout", f"{request.healthcheck.timeout_seconds}s", "--health-retries", str(request.healthcheck.retries)]
            if request.healthcheck.start_period_seconds:
                args += ["--health-start-period", f"{request.healthcheck.start_period_seconds}s"]
        args.append(request.image)
        try:
            result = self._run(args, timeout=1800)
        finally:
            env_path.unlink(missing_ok=True)
        self._result(result, "Could not create container")
        return self.container_details(request.name)

    def _safe_update_container(self, target: str, image: str | None, actor: str, log: LogCallback) -> dict[str, Any]:
        normalized = self._checked_identifier(target, "container")
        inspect = self._inspect("container", normalized)
        original_name = str(inspect.get("Name") or "").removeprefix("/")
        new_image = image or str((inspect.get("Config") or {}).get("Image") or "")
        if not IMAGE_RE.fullmatch(new_image):
            api_error(409, "INVALID_IMAGE", "Container image reference is invalid")
        pull = self._run(["docker", "pull", new_image], timeout=1800)
        for line in (pull.stdout + pull.stderr).splitlines()[-500:]:
            log("stdout" if pull.returncode == 0 else "stderr", redact(line))
        self._result(pull, "Could not pull updated image")
        definition = self._container_definition(inspect, name=original_name, image=new_image)
        private_environment = dict(definition.pop("secret_environment", {}))
        rollback_name = f"{original_name}-webnas-rollback-{int(time.time())}"
        was_running = bool((inspect.get("State") or {}).get("Running"))
        if was_running:
            self._result(self._run(["docker", "stop", "--time", "30", normalized], timeout=60), "Could not stop container for update")
        self._result(self._run(["docker", "rename", normalized, rollback_name], timeout=30), "Could not create rollback snapshot")
        try:
            created = self._run_container(definition, private_environment, log)
            time.sleep(2)
            state = self._inspect("container", original_name).get("State") or {}
            if (was_running and not state.get("Running")) or (state.get("Health") or {}).get("Status") == "unhealthy":
                raise RuntimeError("Updated container did not become healthy")
        except Exception:
            self._run(["docker", "rm", "-f", original_name], timeout=60)
            self._run(["docker", "rename", rollback_name, original_name], timeout=30)
            if was_running:
                self._run(["docker", "start", original_name], timeout=60)
            raise
        self._result(self._run(["docker", "rm", "-f", rollback_name], timeout=60), "Could not remove update rollback container")
        return {"container": created, "updated": True, "rolled_back": False, "actor": actor}

    @staticmethod
    def _registry_ca_path(server: str) -> Path:
        if not REGISTRY_RE.fullmatch(server) or server.startswith("-") or ".." in server:
            api_error(400, "INVALID_REGISTRY_SERVER", "Invalid registry server")
        return Path("/etc/docker/certs.d") / server / "webnas-ca.crt"

    def configure_registry_trust(self, server: str, ca_certificate: str) -> None:
        target = self._registry_ca_path(server)
        if ca_certificate:
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            self._write_private(target, ca_certificate)
        else:
            target.unlink(missing_ok=True)

    def _assert_insecure_registry_configured(self, server: str) -> None:
        config = self.get_config().get("config") or {}
        insecure = config.get("insecure-registries") if isinstance(config, dict) else []
        if server not in (insecure if isinstance(insecure, list) else []):
            api_error(409, "INSECURE_REGISTRY_NOT_CONFIGURED", "Add this server to the controlled Docker daemon insecure-registries setting before using it without TLS")

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation in {"app_install", "app_start", "app_stop", "app_restart", "app_update", "app_remove"}:
            app_id = str(payload.get("app_id") or "")
            if app_id not in CONTAINER_APPS_BY_ID:
                api_error(400, "INVALID_CONTAINER_APP", "Unknown container application")
            inspect = self._inspect_container(CONTAINER_APPS_BY_ID[app_id].container)
            labels = inspect.get("Config", {}).get("Labels") or {} if inspect else {}
            configured_image = str(inspect.get("Config", {}).get("Image") or "") if inspect else ""
            managed = labels.get("io.webnas.app") == app_id or (app_id == "home-assistant" and configured_image == CONTAINER_APPS_BY_ID[app_id].image)
            if inspect and not managed:
                api_error(409, "CONTAINER_NOT_MANAGED", "A container with the reserved name exists outside the WebNAS application catalog")
            app_secrets: dict[str, str] = {}
            if operation == "app_install":
                input_ref = str(payload.get("input_ref") or "")
                private = self.manager_store.consume_input(input_ref) if input_ref else {}
                app_secrets = dict(private.get("environment") or {})
            if app_id in {"pihole", "adguard-home", "home-assistant"}:
                from . import get_provider

                provider = get_provider(app_id, actor)
                if operation == "app_install" and app_id == "pihole":
                    if not isinstance(provider, ApiConnectionProvider):
                        api_error(500, "INVALID_APP_PROVIDER", "Pi-hole provider cannot store its API connection")
                    password = app_secrets.get("WEBPASSWORD", "")
                    if not password:
                        api_error(422, "APP_SECRETS_REQUIRED", "Pi-hole requires an administration password", fields=["WEBPASSWORD"])
                    panel_port = int(payload.get("panel_port") or 8080)
                    provider.save_connection(f"http://127.0.0.1:{panel_port}", "", password)
                delegated = {"app_install": "install_container", "app_start": "container_start", "app_stop": "container_stop", "app_restart": "container_restart", "app_update": "update_container", "app_remove": "remove_container"}[operation]
                delegated_result = provider.manage(delegated, payload, actor, log, progress, cancelled)
                return {"operation": operation, "app_id": app_id, **delegated_result}
            if operation == "app_install":
                definition = CONTAINER_APPS_BY_ID[app_id].container_definition(app_secrets)
                return {"operation": operation, "app_id": app_id, "container": self._run_container(definition, app_secrets, log)}
            target = CONTAINER_APPS_BY_ID[app_id].container
            if operation == "app_update":
                return {"operation": operation, "app_id": app_id, **self._safe_update_container(target, CONTAINER_APPS_BY_ID[app_id].image, actor, log)}
            command = {"app_start": ["start", target], "app_stop": ["stop", "--time", "30", target], "app_restart": ["restart", "--time", "30", target], "app_remove": ["rm", "-f", target]}[operation]
            app_process = self._run(["docker", *command], timeout=120)
            self._result(app_process, "Container application operation failed")
            return {"operation": operation, "app_id": app_id, "status": "not_installed" if operation == "app_remove" else self.container_details(target)}

        progress(10, "Preparing Docker operation")
        if cancelled():
            raise InterruptedError("Docker operation cancelled before execution")

        result: subprocess.CompletedProcess[str] | None = None
        response: dict[str, Any] | None = None
        target = str(payload.get("target") or "")
        if operation == "container_create":
            definition = dict(payload.get("definition") or {})
            input_ref = str(payload.get("input_ref") or "")
            private = self.manager_store.consume_input(input_ref) if input_ref else {}
            response = {"container": self._run_container(definition, dict(private.get("environment") or {}), log)}
        elif operation == "container_settings":
            response = self.update_container_settings(str(payload.get("target") or ""), dict(payload.get("settings") or {}))
        elif operation in {"container_start", "container_stop", "container_restart", "container_pause", "container_unpause", "container_kill", "container_rename", "container_remove"}:
            normalized = self._checked_identifier(target, "container")
            if operation == "container_start":
                command = ["start", normalized]
            elif operation == "container_stop":
                command = ["stop", "--time", str(min(max(int(payload.get("timeout") or 10), 1), 300)), normalized]
            elif operation == "container_restart":
                command = ["restart", "--time", str(min(max(int(payload.get("timeout") or 10), 1), 300)), normalized]
            elif operation == "container_pause":
                command = ["pause", normalized]
            elif operation == "container_unpause":
                command = ["unpause", normalized]
            elif operation == "container_kill":
                signal = str(payload.get("signal") or "KILL")
                if signal not in {"KILL", "TERM", "HUP", "INT", "QUIT", "USR1", "USR2"}:
                    api_error(400, "INVALID_SIGNAL", "Unsupported container signal")
                command = ["kill", "--signal", signal, normalized]
            elif operation == "container_rename":
                command = ["rename", normalized, self._checked_identifier(payload.get("new_name"), "container name")]
            else:
                command = ["rm"]
                if bool(payload.get("force")):
                    command.append("--force")
                command.append(normalized)
            result = self._run(["docker", *command], timeout=300)
        elif operation in {"container_duplicate", "container_recreate", "container_update"}:
            normalized = self._checked_identifier(target, "container")
            if operation == "container_duplicate":
                definition = self._container_definition(self._inspect("container", normalized), name=self._checked_identifier(payload.get("new_name"), "container name"), image=str(payload.get("image") or "") or None)
                private = dict(definition.pop("secret_environment", {}))
                response = {"container": self._run_container(definition, private, log), "duplicated_from": normalized}
            else:
                response = self._safe_update_container(normalized, str(payload.get("image") or "") or None, actor, log)
        elif operation == "container_check_update":
            normalized = self._checked_identifier(target, "container")
            inspect = self._inspect("container", normalized)
            image = str((inspect.get("Config") or {}).get("Image") or "")
            if not IMAGE_RE.fullmatch(image):
                api_error(409, "INVALID_IMAGE", "Container image reference is invalid")
            before = str(inspect.get("Image") or "")
            pull = self._run(["docker", "pull", image], timeout=1800)
            self._result(pull, "Could not check the remote container image")
            after = str(self._inspect("image", image).get("Id") or "")
            response = {"image": image, "local_image_id": before, "remote_image_id": after, "update_available": bool(before and after and before != after), "container_changed": False}
        elif operation == "container_import":
            private = self.manager_store.consume_input(str(payload.get("input_ref") or ""))
            artifact_id = str(private.get("artifact_id") or "")
            repository = str(private.get("repository") or "")
            if not IMAGE_RE.fullmatch(repository):
                api_error(400, "INVALID_IMAGE", "Invalid target image reference")
            path, metadata = self.manager_store.artifact(artifact_id)
            if metadata["kind"] != "container_filesystem_upload":
                api_error(409, "INVALID_CONTAINER_ARCHIVE", "Uploaded artifact is not a container filesystem archive")
            result = self._run(["docker", "container", "import", str(path), repository], timeout=3600)
            response = {"repository": repository, "warning": "A filesystem import does not contain image history, container configuration, secrets, networks, or volume data"}
        elif operation == "container_export":
            normalized = self._checked_identifier(target, "container")
            filename = f"container-{int(time.time())}-{hashlib.sha256(normalized.encode()).hexdigest()[:12]}.tar"
            path = self.manager_store.artifacts_dir / filename
            result = self._run(["docker", "container", "export", "--output", str(path), normalized], timeout=3600)
            if result.returncode == 0:
                os.chmod(path, 0o600)
                response = {"artifact": self.manager_store.register_artifact(path, kind="container_export", display_name=f"{normalized}.tar", actor=actor, metadata={"container": normalized, "secrets_omitted": True})}
        elif operation == "container_backup":
            response = {"artifact": self._container_backup(target, actor, log)}
        elif operation == "container_restore":
            input_ref = str(payload.get("input_ref") or "")
            private = self.manager_store.consume_input(input_ref) if input_ref else {}
            response = self._restore_container_backup(str(payload.get("backup_id") or ""), str(payload.get("new_name") or ""), actor, log, dict(private.get("environment") or {}))
        elif operation in {"image_pull", "image_update"}:
            image = str(payload.get("image") or target)
            if not IMAGE_RE.fullmatch(image):
                api_error(400, "INVALID_IMAGE", "Invalid image reference")
            before_result = self._run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=30) if operation == "image_update" else None
            command = ["pull"]
            platform = str(payload.get("platform") or "")
            if platform:
                if platform not in {"linux/amd64", "linux/arm64", "linux/arm/v7"}:
                    api_error(400, "INVALID_PLATFORM", "Unsupported image platform")
                command += ["--platform", platform]
            command.append(image)
            result = self._run(["docker", *command], timeout=3600)
            if operation == "image_update" and result.returncode == 0:
                after_result = self._run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=30)
                self._result(after_result, "Could not inspect the updated image")
                before = before_result.stdout.strip() if before_result and before_result.returncode == 0 else ""
                after = after_result.stdout.strip()
                response = {"image": image, "digest_changed": bool(before and after and before != after), "before_image_id": before, "after_image_id": after}
        elif operation == "image_remove":
            image = str(payload.get("image") or target)
            if not IMAGE_RE.fullmatch(image):
                api_error(400, "INVALID_IMAGE", "Invalid image reference")
            result = self._run(["docker", "image", "rm", *(["--force"] if payload.get("force") else []), image], timeout=600)
        elif operation == "image_prune":
            result = self._run(["docker", "image", "prune", "--force"], timeout=1800)
        elif operation == "image_save":
            image = str(payload.get("image") or target)
            if not IMAGE_RE.fullmatch(image):
                api_error(400, "INVALID_IMAGE", "Invalid image reference")
            filename = f"image-{int(time.time())}-{hashlib.sha256(image.encode()).hexdigest()[:12]}.tar"
            path = self.manager_store.artifacts_dir / filename
            result = self._run(["docker", "image", "save", "--output", str(path), image], timeout=3600)
            if result.returncode == 0:
                os.chmod(path, 0o600)
                response = {"artifact": self.manager_store.register_artifact(path, kind="image_archive", display_name=f"{image.replace('/', '_')}.tar", actor=actor, metadata={"image": image})}
        elif operation == "image_load":
            input_ref = str(payload.get("input_ref") or "")
            private = self.manager_store.consume_input(input_ref)
            artifact_id = str(private.get("artifact_id") or "")
            path, metadata = self.manager_store.artifact(artifact_id)
            if metadata["kind"] != "image_upload":
                api_error(409, "INVALID_IMAGE_ARCHIVE", "Uploaded artifact is not an image archive")
            result = self._run(["docker", "image", "load", "--input", str(path)], timeout=3600)
        elif operation in {"registry_login", "registry_logout"}:
            registry_id = str(payload.get("registry_id") or "")
            credentials = self.manager_store.registry_credentials(registry_id)
            if operation == "registry_login":
                if credentials.get("tls") != "true":
                    self._assert_insecure_registry_configured(credentials["server"])
                self.configure_registry_trust(credentials["server"], credentials.get("ca_certificate", ""))
                result = self._run(["docker", "login", credentials["server"], "--username", credentials["username"], "--password-stdin"], input_text=credentials["password"] + "\n", timeout=120)
            else:
                result = self._run(["docker", "logout", credentials["server"]], timeout=120)
        elif operation == "volume_create":
            from ..docker_manager.models import VolumeCreateRequest

            volume_request = VolumeCreateRequest.model_validate(payload.get("definition") or {})
            command = ["volume", "create"]
            for key, value in volume_request.labels.items():
                command += ["--label", f"{key}={value}"]
            command.append(volume_request.name)
            result = self._run(["docker", *command], timeout=120)
        elif operation in {"volume_remove", "volume_prune", "volume_backup", "volume_restore", "volume_clone"}:
            if operation == "volume_prune":
                result = self._run(["docker", "volume", "prune", "--force"], timeout=1800)
            else:
                volume = self._checked_identifier(target, "volume")
                if operation == "volume_remove":
                    result = self._run(["docker", "volume", "rm", *(["--force"] if payload.get("force") else []), volume], timeout=300)
                elif operation == "volume_backup":
                    response = {"artifact": self._volume_archive(volume, actor)}
                elif operation == "volume_restore":
                    response = self._restore_volume(volume, str(payload.get("backup_id") or ""))
                else:
                    target_name = self._checked_identifier(payload.get("target_name"), "volume name")
                    create = self._run(["docker", "volume", "create", target_name], timeout=120)
                    self._result(create, "Could not create cloned volume")
                    backup = self._volume_archive(volume, actor, display_name=f"temporary-{volume}.tar.gz")
                    response = self._restore_volume(target_name, backup["id"])
        elif operation == "network_create":
            from ..docker_manager.models import NetworkCreateRequest

            network_request = NetworkCreateRequest.model_validate(payload.get("definition") or {})
            network_items = self._json_lines(self._docker(["network", "ls", "--format", "{{json .}}"], timeout=30))
            if any(str(item.get("Name") or "") == network_request.name for item in network_items):
                api_error(409, "NETWORK_NAME_EXISTS", "A Docker network with this name already exists")
            requested_networks = [
                ipaddress.ip_network(value, strict=False)
                for value in (network_request.ipv4_subnet, network_request.ipv6_subnet)
                if value
            ]
            if requested_networks:
                for network_item in network_items:
                    detail = self._inspect("network", str(network_item.get("ID") or network_item.get("Name")))
                    for config in (detail.get("IPAM") or {}).get("Config") or []:
                        existing = config.get("Subnet") if isinstance(config, dict) else None
                        if not existing:
                            continue
                        try:
                            existing_network = ipaddress.ip_network(existing, strict=False)
                        except ValueError:
                            continue
                        if any(
                            requested.version == existing_network.version and requested.overlaps(existing_network)
                            for requested in requested_networks
                        ):
                            api_error(409, "NETWORK_SUBNET_CONFLICT", "Requested subnet overlaps an existing Docker network")
            command = ["network", "create", "--driver", "bridge"]
            if network_request.internal:
                command.append("--internal")
            if network_request.ipv6_mode == "manual":
                command.append("--ipv6")
            if network_request.disable_ip_masquerade:
                command += ["--opt", "com.docker.network.bridge.enable_ip_masquerade=false"]
            for subnet, ip_range, gateway in (
                (network_request.ipv4_subnet, network_request.ipv4_ip_range, network_request.ipv4_gateway),
                (network_request.ipv6_subnet, network_request.ipv6_ip_range, network_request.ipv6_gateway),
            ):
                if subnet:
                    command += ["--subnet", subnet]
                if ip_range:
                    command += ["--ip-range", ip_range]
                if gateway:
                    command += ["--gateway", gateway]
            for key, value in network_request.labels.items():
                command += ["--label", f"{key}={value}"]
            command.append(network_request.name)
            result = self._run(["docker", *command], timeout=120)
        elif operation in {"network_remove", "network_prune", "network_connect", "network_disconnect"}:
            if operation == "network_prune":
                result = self._run(["docker", "network", "prune", "--force"], timeout=1800)
            else:
                network = self._checked_identifier(target, "network")
                if network in SYSTEM_NETWORKS:
                    api_error(403, "SYSTEM_NETWORK_PROTECTED", "Docker system networks cannot be modified")
                if operation == "network_remove":
                    detail = self._inspect("network", network)
                    if detail.get("Containers"):
                        api_error(409, "NETWORK_IN_USE", "Disconnect all containers before removing the Docker network")
                    result = self._run(["docker", "network", "rm", network], timeout=300)
                else:
                    container = self._checked_identifier(payload.get("container"), "container")
                    verb = "connect" if operation == "network_connect" else "disconnect"
                    result = self._run(["docker", "network", verb, *(["--force"] if verb == "disconnect" and payload.get("force") else []), network, container], timeout=120)
        elif operation.startswith("compose_"):
            project = str(payload.get("project") or "")
            if not SLUG_RE.fullmatch(project):
                api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
            file = self.compose_dir / project / "compose.yaml"
            if not file.is_file():
                api_error(404, "COMPOSE_PROJECT_NOT_FOUND", "Compose project not found")
            verb = operation.removeprefix("compose_")
            if verb == "delete":
                down_payload = {**payload, "operation": "compose_down", "remove_volumes": payload.get("remove_volumes")}
                self.manage("compose_down", down_payload, actor, log, progress, cancelled)
                directory = file.parent.resolve()
                try:
                    directory.relative_to(self.compose_dir.resolve())
                except ValueError:
                    api_error(422, "UNSAFE_COMPOSE_PATH", "Compose project path escapes the managed directory")
                shutil.rmtree(directory)
                response = {"deleted": True, "project": project}
            else:
                command_verb = "up" if verb == "recreate" else verb
                if command_verb not in {"up", "down", "start", "stop", "restart", "pull", "scale"}:
                    api_error(400, "INVALID_COMPOSE_ACTION", "Unsupported Compose action")
                merged_env = file.parent / f".env.job-{hashlib.sha256((actor + str(time.time())).encode()).hexdigest()[:12]}"
                public = (file.parent / ".env").read_text(encoding="utf-8", errors="replace") if (file.parent / ".env").is_file() else ""
                private = (file.parent / ".env.secrets").read_text(encoding="utf-8", errors="replace") if (file.parent / ".env.secrets").is_file() else ""
                self._write_private(merged_env, public + private)
                command = [*self._compose_tool(), "--ansi", "never", "--env-file", str(merged_env), "-f", str(file), "-p", project, command_verb]
                if command_verb == "up":
                    command += ["-d"]
                    if verb == "recreate":
                        command.append("--force-recreate")
                if command_verb == "down" and payload.get("remove_volumes"):
                    command.append("--volumes")
                if command_verb == "scale":
                    scale = payload.get("scale") or {}
                    if not isinstance(scale, dict) or not scale:
                        api_error(422, "COMPOSE_SCALE_REQUIRED", "At least one service replica count is required")
                    command += [f"{self._checked_identifier(service, 'service')}={int(replicas)}" for service, replicas in scale.items()]
                else:
                    services = [self._checked_identifier(item, "service") for item in payload.get("services") or []]
                    command += services
                try:
                    result = self._run(command, timeout=3600)
                finally:
                    merged_env.unlink(missing_ok=True)
        elif operation == "system_prune":
            resources = set(payload.get("resources") or [])
            outputs: list[str] = []
            commands = []
            if "containers" in resources:
                commands.append(["container", "prune", "--force"])
            if "images" in resources:
                commands.append(["image", "prune", "--force"])
            if "networks" in resources:
                commands.append(["network", "prune", "--force"])
            if "volumes" in resources:
                commands.append(["volume", "prune", "--force"])
            if "build_cache" in resources:
                commands.append(["builder", "prune", "--force"])
            for command in commands:
                item = self._run(["docker", *command], timeout=1800)
                self._result(item, "Docker prune failed")
                outputs.append(item.stdout)
            response = {"resources": sorted(resources), "output": redact("\n".join(outputs))}
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)

        progress(85, "Verifying Docker operation")
        if result is not None:
            for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
                log("stdout" if result.returncode == 0 else "stderr", redact(line))
            self._result(result, "Docker operation failed")
        if cancelled():
            raise InterruptedError("Docker operation cancelled after execution")
        progress(95, "Refreshing Docker state")
        return {"operation": operation, "target": target or payload.get("project"), **(response or {}), "status": self.get_status().model_dump(mode="json")}

    def get_config(self) -> dict[str, Any]:
        try:
            raw = self.daemon_path.read_text(encoding="utf-8")
            config = json.loads(raw)
            if not isinstance(config, dict):
                raise ValueError("daemon configuration must be an object")
        except FileNotFoundError:
            config = {}
        except (OSError, ValueError) as error:
            return {"config": {}, "path": str(self.daemon_path), "valid": False, "error": redact(str(error))}
        return {"config": _redact_value(config), "path": str(self.daemon_path), "valid": True, "error": ""}

    @staticmethod
    def _daemon_policy_errors(config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        unknown = sorted(set(config) - DAEMON_CONFIG_FIELDS)
        if unknown:
            errors.append(f"Unsupported daemon settings: {', '.join(unknown)}")
        if config.get("log-driver") not in {None, "json-file", "local", "journald"}:
            errors.append("log-driver must be json-file, local or journald")
        log_options = config.get("log-opts")
        if log_options is not None:
            if not isinstance(log_options, dict) or set(log_options) - {"max-size", "max-file", "compress"}:
                errors.append("log-opts supports only max-size, max-file and compress")
            else:
                if "max-size" in log_options and not re.fullmatch(r"[1-9][0-9]{0,5}[kKmMgG]", str(log_options["max-size"])):
                    errors.append("log-opts max-size must be a bounded size such as 10m")
                if "max-file" in log_options and not re.fullmatch(r"[1-9][0-9]?", str(log_options["max-file"])):
                    errors.append("log-opts max-file must be between 1 and 99")
                if "compress" in log_options and str(log_options["compress"]).lower() not in {"true", "false"}:
                    errors.append("log-opts compress must be true or false")
        for key in ("live-restore", "ipv6", "userland-proxy", "experimental"):
            if key in config and not isinstance(config[key], bool):
                errors.append(f"{key} must be a boolean")
        if "ip-masq" in config and not isinstance(config["ip-masq"], bool):
            errors.append("ip-masq must be a boolean")
        for key, version in (("fixed-cidr", 4), ("fixed-cidr-v6", 6)):
            if key in config:
                try:
                    network = ipaddress.ip_network(str(config[key]), strict=False)
                    if network.version != version or network.is_multicast or network.prefixlen == 0:
                        raise ValueError
                except ValueError:
                    errors.append(f"{key} must be a valid IPv{version} network")
        if "bip" in config:
            try:
                bridge = ipaddress.ip_interface(str(config["bip"]))
                if bridge.version != 4 or bridge.network.is_multicast or bridge.network.prefixlen == 0:
                    raise ValueError
            except ValueError:
                errors.append("bip must be a valid IPv4 interface with prefix")
        for key, version in (("default-gateway", 4), ("default-gateway-v6", 6)):
            if key in config:
                try:
                    gateway = ipaddress.ip_address(str(config[key]))
                    if gateway.version != version or gateway.is_multicast:
                        raise ValueError
                except ValueError:
                    errors.append(f"{key} must be a valid IPv{version} address")
        dns = config.get("dns")
        if dns is not None:
            if not isinstance(dns, list) or len(dns) > 16:
                errors.append("dns must be a list of at most 16 IP addresses")
            else:
                try:
                    [ipaddress.ip_address(str(value)) for value in dns]
                except ValueError:
                    errors.append("dns contains an invalid IP address")
        insecure = config.get("insecure-registries")
        if insecure is not None:
            if not isinstance(insecure, list) or len(insecure) > 32:
                errors.append("insecure-registries must be a list of at most 32 entries")
            else:
                for value in insecure:
                    item = str(value)
                    try:
                        network = ipaddress.ip_network(item, strict=False)
                        if network.prefixlen == 0:
                            raise ValueError
                    except ValueError:
                        if not REGISTRY_RE.fullmatch(item):
                            errors.append(f"Invalid insecure registry: {item[:80]}")
        mirrors = config.get("registry-mirrors")
        if mirrors is not None:
            if not isinstance(mirrors, list) or len(mirrors) > 16:
                errors.append("registry-mirrors must be a list of at most 16 HTTPS origins")
            else:
                for value in mirrors:
                    parsed = urllib.parse.urlsplit(str(value))
                    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                        errors.append("registry-mirrors accepts HTTPS origins without credentials, query or fragment")
        pools = config.get("default-address-pools")
        if pools is not None:
            if not isinstance(pools, list) or len(pools) > 16:
                errors.append("default-address-pools must contain at most 16 pools")
            else:
                for pool in pools:
                    if not isinstance(pool, dict) or set(pool) != {"base", "size"}:
                        errors.append("Each default address pool requires only base and size")
                        continue
                    try:
                        network = ipaddress.ip_network(str(pool["base"]), strict=False)
                        size = int(pool["size"])
                        if network.is_multicast or size < network.prefixlen or size > network.max_prefixlen:
                            raise ValueError
                    except (TypeError, ValueError):
                        errors.append("A default address pool is invalid")
        features = config.get("features")
        if features is not None and (not isinstance(features, dict) or set(features) - {"containerd-snapshotter"} or not all(isinstance(value, bool) for value in features.values())):
            errors.append("features supports only the boolean containerd-snapshotter setting")
        return errors

    def validate_config(self, config: dict[str, Any]) -> ModuleValidationResult:
        if any(key in config for key in {"hosts", "authorization-plugins"}):
            return ModuleValidationResult(ok=False, errors=["Remote daemon listeners and authorization plugins are not managed by WebNAS"])
        policy_errors = self._daemon_policy_errors(config)
        if policy_errors:
            return ModuleValidationResult(ok=False, errors=policy_errors)
        try:
            content = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        except (TypeError, ValueError) as error:
            return ModuleValidationResult(ok=False, errors=[f"Configuration is not JSON serializable: {error}"])
        if len(content.encode("utf-8")) > 256 * 1024:
            return ModuleValidationResult(ok=False, errors=["Docker daemon configuration exceeds 256 KiB"])
        candidate = self.manager_store.inputs_dir / f"daemon-validate-{hashlib.sha256(content.encode()).hexdigest()[:16]}.json"
        self._write_private(candidate, content)
        output = ""
        warnings: list[str] = []
        try:
            if shutil.which("dockerd"):
                result = self._run(["dockerd", "--validate", "--config-file", str(candidate)], timeout=30)
                output = redact(result.stdout.strip() or result.stderr.strip())
                if result.returncode != 0:
                    return ModuleValidationResult(ok=False, errors=[output or "dockerd rejected the configuration"], generated_config=content, validator_output=output)
            else:
                warnings.append("dockerd is not installed; only JSON and policy validation was performed")
        finally:
            candidate.unlink(missing_ok=True)
        current = self.get_config().get("config") or {}
        changes = [{"path": key, "before": current.get(key), "after": config.get(key)} for key in sorted(set(current) | set(config)) if current.get(key) != config.get(key)]
        return ModuleValidationResult(ok=True, warnings=warnings, changes=changes, generated_config=content, validator_output=output)

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        content = self.daemon_path.read_bytes() if self.daemon_path.is_file() else b"{}\n"
        return self._store_backup(actor, description or "Docker daemon configuration", content, ".daemon.json", automatic=automatic)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        source, _ = self._backup_metadata(backup_id)
        try:
            config = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("Docker configuration backup is invalid") from error
        validation = self.validate_config(config)
        if not validation.ok:
            api_error(422, "CONFIG_VALIDATION_FAILED", "Docker configuration backup is invalid", errors=validation.errors)
        self.daemon_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_private(self.daemon_path, validation.generated_config)
        restart = self._systemctl("docker", "restart")
        log("stdout" if restart.returncode == 0 else "stderr", redact(restart.stdout.strip() or restart.stderr.strip()))
        if restart.returncode != 0 or self.get_status().service_state != "active":
            raise RuntimeError("Docker did not become active after restoring configuration")
        return {"backup_id": backup_id, "restored": True, "status": self.get_status().model_dump(mode="json")}

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if action == PackageAction.apply:
            config = payload.get("config")
            if not isinstance(config, dict):
                api_error(422, "INVALID_DAEMON_CONFIG", "Docker daemon configuration must be an object")
            validation = self.validate_config(config)
            if not validation.ok:
                api_error(422, "CONFIG_VALIDATION_FAILED", "Docker daemon configuration is invalid", errors=validation.errors)
            progress(20, "Docker configuration validated")
            if cancelled():
                raise InterruptedError("Configuration update cancelled before write")
            backup = self.create_backup(actor, "Automatic backup before daemon configuration update", automatic=True)
            progress(40, "Configuration backup created")
            previous = self.daemon_path.read_bytes() if self.daemon_path.is_file() else None
            try:
                self.daemon_path.parent.mkdir(parents=True, exist_ok=True)
                self._write_private(self.daemon_path, validation.generated_config)
                progress(60, "Restarting Docker service")
                restart = self._systemctl("docker", "restart")
                log("stdout" if restart.returncode == 0 else "stderr", redact(restart.stdout.strip() or restart.stderr.strip()))
                if restart.returncode != 0 or self.get_status().service_state != "active":
                    raise RuntimeError("Docker service verification failed after configuration update")
            except Exception:
                if previous is None:
                    self.daemon_path.unlink(missing_ok=True)
                else:
                    temp = self.daemon_path.with_suffix(".rollback")
                    temp.write_bytes(previous)
                    os.chmod(temp, 0o600)
                    os.replace(temp, self.daemon_path)
                rollback = self._systemctl("docker", "restart")
                log("stderr", "Docker configuration was rolled back")
                if rollback.returncode != 0:
                    log("stderr", redact(rollback.stderr.strip() or "Docker failed to restart after rollback"))
                raise
            progress(95, "Docker configuration verified")
            return {"backup": backup, "validation": validation.model_dump(mode="json"), "status": self.get_status().model_dump(mode="json")}
        return super().execute_operation(action, payload, actor, log, progress, cancelled)

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        info = self._run(["docker", "info", "--format", "{{json .}}"], timeout=30) if shutil.which("docker") else None
        compose = self._run(["docker", "compose", "version"], timeout=15) if shutil.which("docker") else None
        disk = shutil.disk_usage("/var/lib/docker") if Path("/var/lib/docker").exists() else None
        try:
            info_payload = json.loads(info.stdout) if info and info.returncode == 0 else {}
        except json.JSONDecodeError:
            info_payload = {}
        diagnostics = [
            ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="Docker Engine", description=status.health_message, details=(info.stderr if info and info.returncode else ""), severity="ok" if status.health == ModuleHealth.healthy else "critical", recommended_action="Start the Docker service" if status.health != ModuleHealth.healthy else ""),
            ModuleDiagnostic(status="ok" if Path("/var/run/docker.sock").exists() else "critical", title="Docker socket", description="Docker Unix socket is present" if Path("/var/run/docker.sock").exists() else "Docker Unix socket is missing", severity="ok" if Path("/var/run/docker.sock").exists() else "critical", recommended_action="Check docker.service and its socket activation" if not Path("/var/run/docker.sock").exists() else ""),
            ModuleDiagnostic(status="info", title="Client, server and API versions", description=f"Client {status.metrics.get('client_version') or 'unknown'} / server {status.metrics.get('server_version') or 'unknown'}", details=f"API client {status.metrics.get('client_api_version') or 'unknown'} / server {status.metrics.get('server_api_version') or 'unknown'}", severity="info"),
            ModuleDiagnostic(status="info", title="Containers", description=f"{status.metrics.get('running_containers', 0)} running of {status.metrics.get('containers', 0)}", severity="info"),
            ModuleDiagnostic(status="ok" if compose and compose.returncode == 0 else "warning", title="Docker Compose", description=compose.stdout.strip() if compose and compose.returncode == 0 else "Docker Compose plugin is unavailable", details=redact(compose.stderr.strip()) if compose and compose.returncode else "", severity="ok" if compose and compose.returncode == 0 else "warning", recommended_action="Install docker-compose-plugin" if not compose or compose.returncode else ""),
            ModuleDiagnostic(status="info", title="Storage driver", description=str(info_payload.get("Driver") or "Unavailable"), details=f"Docker data root: {redact(str(info_payload.get('DockerRootDir') or 'unknown'))}", severity="info"),
            ModuleDiagnostic(status="info", title="Control groups", description=f"cgroup {info_payload.get('CgroupVersion') or 'unknown'} using {info_payload.get('CgroupDriver') or 'unknown'}", severity="info"),
        ]
        if disk:
            percent = round(disk.used / max(disk.total, 1) * 100, 1)
            diagnostics.append(ModuleDiagnostic(status="warning" if percent >= 90 else "ok", title="Docker storage", description=f"{percent}% of the filesystem is used", details=f"Free bytes: {disk.free}", severity="warning" if percent >= 90 else "ok", recommended_action="Review unused images and stopped containers" if percent >= 90 else ""))
        if status.service_state == "active":
            containers = self._json_lines(self._docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=30))
            ids = [str(item.get("ID") or "") for item in containers if item.get("ID")]
            inspections: list[dict[str, Any]] = []
            if ids:
                inspected = self._run(["docker", "container", "inspect", *ids[:500]], timeout=60)
                if inspected.returncode == 0:
                    try:
                        value = json.loads(inspected.stdout)
                        inspections = value if isinstance(value, list) else []
                    except json.JSONDecodeError:
                        inspections = []
            unhealthy = [item for item in inspections if ((item.get("State") or {}).get("Health") or {}).get("Status") == "unhealthy"]
            restart_loops = [item for item in inspections if (item.get("State") or {}).get("Restarting") or int(item.get("RestartCount") or 0) >= 10]
            failed = [item for item in inspections if str((item.get("State") or {}).get("Status") or "") in {"dead", "removing"}]
            privileged = [item for item in inspections if (item.get("HostConfig") or {}).get("Privileged")]
            host_network = [item for item in inspections if (item.get("HostConfig") or {}).get("NetworkMode") == "host"]
            socket_mounts = [item for item in inspections if any(str(mount.get("Source") or "") == "/var/run/docker.sock" for mount in item.get("Mounts") or [])]
            root_users = [item for item in inspections if str((item.get("Config") or {}).get("User") or "") in {"", "0", "root", "0:0"}]
            bindings: dict[tuple[str, str], list[str]] = {}
            for item in inspections:
                name = str(item.get("Name") or "").removeprefix("/")
                for values in ((item.get("HostConfig") or {}).get("PortBindings") or {}).values():
                    for binding in values or []:
                        key = (str(binding.get("HostIp") or "0.0.0.0"), str(binding.get("HostPort") or ""))
                        if key[1]:
                            bindings.setdefault(key, []).append(name)
            conflicts = {f"{host}:{port}": names for (host, port), names in bindings.items() if len(names) > 1}
            images = self._json_lines(self._docker(["image", "ls", "--digests", "--format", "{{json .}}"], timeout=30))
            missing_digests = [item for item in images if str(item.get("Digest") or "") in {"", "<none>"}]
            prune = self.prune_plan(["images", "volumes"])
            daemon = self.get_config().get("config") or {}
            log_driver = daemon.get("log-driver", "json-file") if isinstance(daemon, dict) else "json-file"
            log_options = daemon.get("log-opts", {}) if isinstance(daemon, dict) else {}
            rotation = log_driver == "local" or isinstance(log_options, dict) and bool(log_options.get("max-size"))
            checks = [
                ("Unhealthy containers", unhealthy, "Review container healthcheck output and recent logs"),
                ("Restart loops", restart_loops, "Inspect restart policy, application logs and dependencies"),
                ("Failed containers", failed, "Inspect the failed container state before removing it"),
                ("Privileged containers", privileged, "Recreate privileged containers with the least required access"),
                ("Host-network containers", host_network, "Prefer a user-defined bridge network and explicit ports"),
                ("Docker socket mounts", socket_mounts, "Remove Docker socket mounts unless explicitly audited"),
                ("Containers running as root", root_users, "Configure a numeric non-root UID:GID where the image supports it"),
                ("Images without a repository digest", missing_digests, "Pull images by digest for reproducible deployments"),
            ]
            for title, items, recommendation in checks:
                diagnostics.append(ModuleDiagnostic(status="warning" if items else "ok", title=title, description=f"{len(items)} detected", severity="warning" if items else "ok", recommended_action=recommendation if items else ""))
            diagnostics.append(ModuleDiagnostic(status="warning" if conflicts else "ok", title="Published port conflicts", description=f"{len(conflicts)} conflicts detected", details=redact(json.dumps(conflicts, ensure_ascii=False)), severity="warning" if conflicts else "ok", recommended_action="Change one of the conflicting published ports" if conflicts else ""))
            diagnostics.append(ModuleDiagnostic(status="info", title="Unused resources", description=f"{prune.get('total', 0)} unused images or volumes", details=f"Estimated reclaimable bytes: {prune.get('estimated_reclaimable', 0)}", severity="info"))
            diagnostics.append(ModuleDiagnostic(status="ok" if rotation else "warning", title="Container log rotation", description=f"Driver: {log_driver}; bounded rotation {'configured' if rotation else 'not configured'}", severity="ok" if rotation else "warning", recommended_action="Set controlled log-opts max-size/max-file or use the local log driver" if not rotation else ""))
        return diagnostics
