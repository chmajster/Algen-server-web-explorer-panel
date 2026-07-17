from __future__ import annotations

import json
import os
import secrets
import shutil
import tarfile
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from ...config import get_config
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .infrastructure import ApiConnectionProvider


class HomeAssistantProvider(ApiConnectionProvider):
    allowed_tools = {"docker"}
    image = "ghcr.io/home-assistant/home-assistant:stable"
    container = "homeassistant"

    def default_base_url(self) -> str:
        return "http://127.0.0.1:8123"

    @property
    def config_dir(self) -> Path:
        path = Path(get_config().paths.data_dir) / "home-assistant" / "config"
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def _docker(self, args: list[str], *, timeout: int = 120) -> str:
        return self._result(self._run(["docker", *args], timeout=timeout), "Home Assistant Docker operation failed")

    def _inspect(self) -> dict[str, Any] | None:
        if not shutil.which("docker"):
            return None
        result = self._run(["docker", "inspect", self.container], timeout=15)
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
            return payload[0] if isinstance(payload, list) and payload else None
        except (json.JSONDecodeError, IndexError):
            return None

    def get_status(self) -> ModuleStatus:
        inspect = self._inspect()
        installed = inspect is not None
        running = bool(inspect and inspect.get("State", {}).get("Running"))
        image = str(inspect.get("Config", {}).get("Image") or "") if inspect else ""
        panel = self.public_connection()["base_url"]
        return ModuleStatus(installed=installed, package_version=image or None, service_state="active" if running else "inactive" if installed else "not_installed", services={"homeassistant-container": {"state": "active" if running else "inactive", "enabled": installed, "required": True}}, health=ModuleHealth.healthy if running else ModuleHealth.degraded if installed else ModuleHealth.not_installed, health_message="Home Assistant container is running" if running else "Home Assistant container is stopped" if installed else "Home Assistant container is not installed", metrics={"panel_url": panel, "secure_panel": str(panel).startswith("https://") or str(panel).startswith("http://127.0.0.1") or str(panel).startswith("http://localhost")})

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        if resource == "container":
            inspect = self._inspect()
            safe = None if not inspect else {"id": str(inspect.get("Id", ""))[:12], "name": self.container, "image": inspect.get("Config", {}).get("Image"), "state": inspect.get("State", {}), "created": inspect.get("Created")}
            return {"resource": resource, "items": [safe] if safe else [], "total": 1 if safe else 0}
        if resource == "logs":
            result = self._run(["docker", "logs", "--tail", str(limit), "--timestamps", self.container], timeout=30)
            if result.returncode != 0:
                self._result(result, "Could not read Home Assistant logs")
            lines = (result.stdout + result.stderr).splitlines()
            return {"resource": resource, "items": [{"line": line} for line in lines], "total": len(lines)}
        if resource == "panel":
            status = self.get_status()
            return {"resource": resource, "items": [{"url": status.metrics.get("panel_url"), "secure": status.metrics.get("secure_panel"), "authentication": "Home Assistant manages authentication; WebNAS never proxies or stores a Home Assistant session token"}], "total": 1}
        if resource == "updates":
            inspect = self._inspect()
            image = str(inspect.get("Config", {}).get("Image") or self.image) if inspect else self.image
            return {"resource": resource, "items": [{"image": image, "update_method": "Pull stable image and recreate the controlled container"}], "total": 1}
        return super().list_resources(resource, limit=limit, search=search)

    def _run_container(self, image: str, timezone: str) -> None:
        self._docker(["run", "-d", "--name", self.container, "--label", "io.webnas.app=home-assistant", "--restart", "unless-stopped", "--network", "host", "-e", f"TZ={timezone}", "-v", f"{self.config_dir}:/config", image], timeout=180)

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        timezone = str(payload.get("timezone") or "UTC")
        if timezone not in available_timezones():
            api_error(422, "INVALID_TIMEZONE", "Timezone must be a known IANA timezone")
        inspect = self._inspect()
        if operation == "install_container":
            if inspect:
                api_error(409, "CONTAINER_EXISTS", "The controlled Home Assistant container already exists")
            progress(15, "Pulling Home Assistant image")
            self._docker(["pull", self.image], timeout=1800)
            self._run_container(self.image, timezone)
        elif operation in {"container_start", "container_stop", "container_restart"}:
            if not inspect:
                api_error(404, "CONTAINER_NOT_FOUND", "Home Assistant container is not installed")
            self._docker([operation.removeprefix("container_"), self.container], timeout=180)
        elif operation == "update_container":
            if not inspect:
                api_error(404, "CONTAINER_NOT_FOUND", "Home Assistant container is not installed")
            old_image = str(inspect.get("Image") or inspect.get("Config", {}).get("Image") or self.image)
            progress(15, "Pulling updated Home Assistant image")
            self._docker(["pull", self.image], timeout=1800)
            self._docker(["stop", self.container], timeout=180)
            self._docker(["rm", self.container], timeout=180)
            try:
                self._run_container(self.image, timezone)
            except RuntimeError:
                self._run_container(old_image, timezone)
                log("stderr", "Updated container failed; the previous image was restored")
                raise
        elif operation == "remove_container":
            if not inspect:
                api_error(404, "CONTAINER_NOT_FOUND", "Home Assistant container is not installed")
            if bool(inspect.get("State", {}).get("Running")):
                self._docker(["stop", self.container], timeout=180)
            self._docker(["rm", self.container], timeout=180)
            log("stdout", "Home Assistant container removed; configuration data was preserved")
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        log("stdout", f"Home Assistant operation {operation} completed")
        progress(95, "Verifying Home Assistant container")
        return {"operation": operation, "status": self.get_status().model_dump(mode="json")}

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        target = self.backup_dir / f"{secrets.token_hex(12)}.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            for path in sorted(self.config_dir.rglob("*")):
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    continue
                archive.add(path, arcname=path.relative_to(self.config_dir), recursive=False)
        os.chmod(target, 0o600)
        return self._register_backup(actor, description, target, automatic=automatic)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        source, _ = self._backup_metadata(backup_id)
        staging = self.config_dir.parent / f"restore-{secrets.token_hex(8)}"
        staging.mkdir(mode=0o700)
        try:
            with tarfile.open(source, "r:gz") as archive:
                for member in archive.getmembers():
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts or member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                        raise RuntimeError("Home Assistant backup contains an unsafe entry")
                    target = staging / member_path
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            raise RuntimeError("Home Assistant backup entry cannot be read")
                        with target.open("wb") as output:
                            shutil.copyfileobj(extracted, output)
            inspect = self._inspect()
            running = bool(inspect and inspect.get("State", {}).get("Running"))
            if running:
                self._docker(["stop", self.container], timeout=180)
            old = self.config_dir.parent / f"config-old-{secrets.token_hex(8)}"
            os.replace(self.config_dir, old)
            try:
                os.replace(staging, self.config_dir)
                if running:
                    self._docker(["start", self.container], timeout=180)
                shutil.rmtree(old)
            except Exception:
                if self.config_dir.exists():
                    shutil.rmtree(self.config_dir)
                os.replace(old, self.config_dir)
                if running:
                    self._docker(["start", self.container], timeout=180)
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        log("stdout", "Home Assistant configuration restored from a verified archive")
        return {"restored": backup_id}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        secure = bool(status.metrics.get("secure_panel"))
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "warning", title="Home Assistant container", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "warning"), ModuleDiagnostic(status="ok" if secure else "warning", title="Panel access", description="Configured URL uses HTTPS or loopback access" if secure else "Configured panel URL uses unencrypted non-loopback HTTP", severity="ok" if secure else "warning", recommended_action="Configure an HTTPS reverse proxy URL" if not secure else "")]
