from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from ...config import get_config
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .container_apps import CONTAINER_APPS, CONTAINER_APPS_BY_ID
from .infrastructure import CommandProvider, SLUG_RE


IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
PORT_RE = re.compile(r"^(?:[0-9.:[\]]+:)?[1-9][0-9]{0,4}(?:-[1-9][0-9]{0,4})?:[1-9][0-9]{0,4}(?:-[1-9][0-9]{0,4})?(?:/(?:tcp|udp))?$")
COMPOSE_SERVICE_FIELDS = {"image", "container_name", "restart", "ports", "volumes", "environment", "networks", "depends_on"}


class DockerProvider(CommandProvider):
    allowed_tools = {"docker"}

    @property
    def compose_dir(self) -> Path:
        path = Path(get_config().paths.data_dir) / "compose"
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def _docker(self, args: list[str], *, timeout: int = 60) -> str:
        return self._result(self._run(["docker", *args], timeout=timeout), "Docker operation failed")

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
        result = self._run(["docker", "version", "--format", "{{json .Server}}"], timeout=15)
        active = result.returncode == 0
        version = ""
        try:
            version = str(json.loads(result.stdout).get("Version") or "")
        except (json.JSONDecodeError, AttributeError):
            pass
        containers = self._json_lines(self._run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=15).stdout) if active else []
        running = sum(1 for item in containers if str(item.get("State", "")).lower() == "running")
        return ModuleStatus(installed=True, package_version=version or None, service_state="active" if active else "inactive", service_enabled=self._systemctl("docker", "is-enabled").returncode == 0, services={"docker": {"state": "active" if active else "inactive", "enabled": self._systemctl("docker", "is-enabled").returncode == 0, "required": True}}, health=ModuleHealth.healthy if active else ModuleHealth.degraded, health_message="Docker Engine is available" if active else "Docker Engine is unavailable", metrics={"containers": len(containers), "running_containers": running})

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        commands = {
            "containers": ["ps", "-a", "--no-trunc", "--format", "{{json .}}"],
            "images": ["image", "ls", "--no-trunc", "--format", "{{json .}}"],
            "networks": ["network", "ls", "--no-trunc", "--format", "{{json .}}"],
            "volumes": ["volume", "ls", "--format", "{{json .}}"],
            "stats": ["stats", "--no-stream", "--format", "{{json .}}"],
        }
        if resource in commands:
            items = self._json_lines(self._docker(commands[resource], timeout=30))
            needle = search.lower().strip()
            if needle:
                items = [item for item in items if needle in json.dumps(item, ensure_ascii=False).lower()]
            return {"resource": resource, "items": items[:limit], "total": len(items)}
        if resource == "logs":
            target = self._checked_identifier(search, "container")
            result = self._run(["docker", "logs", "--tail", str(limit), "--timestamps", target], timeout=30)
            if result.returncode != 0:
                self._result(result, "Could not read container logs")
            lines = (result.stdout + result.stderr).splitlines()
            return {"resource": resource, "items": [{"line": line} for line in lines], "total": len(lines)}
        if resource == "compose":
            items = []
            for path in sorted(self.compose_dir.glob("*/compose.yaml")):
                stat = path.stat()
                items.append({"name": path.parent.name, "updated_at": stat.st_mtime, "size": stat.st_size})
            return {"resource": resource, "items": items[:limit], "total": len(items)}
        if resource == "apps":
            items: list[dict[str, Any]] = []
            for app in CONTAINER_APPS:
                inspect = self._inspect_container(app.container)
                state = inspect.get("State", {}) if inspect else {}
                labels = inspect.get("Config", {}).get("Labels") or {} if inspect else {}
                configured_image = str(inspect.get("Config", {}).get("Image") or "") if inspect else ""
                managed = bool(inspect and (labels.get("io.webnas.app") == app.id or (app.id == "home-assistant" and configured_image == app.image)))
                running = bool(state.get("Running"))
                items.append({
                    "id": app.id,
                    "name": app.name,
                    "description": app.description,
                    "category": app.category,
                    "image": app.image,
                    "container": app.container,
                    "ports": list(app.ports),
                    "panel_port": app.panel_port,
                    "installed": inspect is not None,
                    "running": running,
                    "managed": managed,
                    "status": "running" if running else "stopped" if inspect else "not_installed",
                })
            needle = search.lower().strip()
            if needle:
                items = [item for item in items if needle in f"{item['name']} {item['description']} {item['category']}".lower()]
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
        return document

    def save_compose(self, project: str, content: str) -> dict[str, Any]:
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
        return {"name": project, "updated_at": target.stat().st_mtime, "size": target.stat().st_size}

    def get_compose(self, project: str) -> dict[str, Any]:
        if not SLUG_RE.fullmatch(project):
            api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
        target = self.compose_dir / project / "compose.yaml"
        if not target.is_file():
            api_error(404, "COMPOSE_PROJECT_NOT_FOUND", "Compose project not found")
        return {"name": project, "content": target.read_text(encoding="utf-8", errors="replace"), "updated_at": target.stat().st_mtime, "size": target.stat().st_size}

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
            from . import get_provider

            provider = get_provider(app_id, actor)
            delegated = {
                "app_install": "install_container",
                "app_start": "container_start",
                "app_stop": "container_stop",
                "app_restart": "container_restart",
                "app_update": "update_container",
                "app_remove": "remove_container",
            }[operation]
            result = provider.manage(delegated, payload, actor, log, progress, cancelled)
            return {"operation": operation, "app_id": app_id, **result}
        if operation in {"container_start", "container_stop", "container_restart"}:
            target = self._checked_identifier(payload.get("target"), "container")
            command = [operation.removeprefix("container_"), target]
        elif operation == "image_update":
            target = str(payload.get("target") or "")
            if not IMAGE_RE.fullmatch(target):
                api_error(400, "INVALID_IMAGE", "Invalid image reference")
            command = ["pull", target]
        elif operation in {"compose_up", "compose_down", "compose_pull", "compose_restart"}:
            project = str(payload.get("project") or "")
            if not SLUG_RE.fullmatch(project):
                api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
            file = self.compose_dir / project / "compose.yaml"
            if not file.is_file():
                api_error(404, "COMPOSE_PROJECT_NOT_FOUND", "Compose project not found")
            verb = operation.removeprefix("compose_")
            command = ["compose", "--ansi", "never", "-f", str(file), "-p", project, verb]
            if verb == "up":
                command.append("-d")
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        progress(15, "Executing Docker operation")
        if cancelled():
            raise InterruptedError("Docker operation cancelled before execution")
        result = self._run(["docker", *command], timeout=1800)
        for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
            log("stdout" if result.returncode == 0 else "stderr", line)
        self._result(result, "Docker operation failed")
        progress(95, "Refreshing Docker state")
        return {"operation": operation, "target": payload.get("target") or payload.get("project"), "status": self.get_status().model_dump(mode="json")}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        info = self._run(["docker", "info", "--format", "{{json .}}"], timeout=30) if shutil.which("docker") else None
        return [
            ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="Docker Engine", description=status.health_message, details=(info.stderr if info and info.returncode else ""), severity="ok" if status.health == ModuleHealth.healthy else "critical", recommended_action="Start the Docker service" if status.health != ModuleHealth.healthy else ""),
            ModuleDiagnostic(status="info", title="Containers", description=f"{status.metrics.get('running_containers', 0)} running of {status.metrics.get('containers', 0)}", severity="info"),
        ]
