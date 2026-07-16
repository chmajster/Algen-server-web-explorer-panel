from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ...config import get_config
from ...package_center.executor import redact
from ...package_center.models import ModuleBackup, ModuleHealth, ModuleStatus, PackageAction, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .base import ModuleProvider


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+,-]{0,255}$")
SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class CommandProvider(ModuleProvider):
    allowed_tools: set[str] = set()

    def _run(self, args: list[str], *, timeout: int = 30, input_text: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        if not args or args[0] not in self.allowed_tools:
            api_error(400, "COMMAND_NOT_ALLOWED", "Provider command is not allowed")
        executable = shutil.which(args[0])
        if not executable:
            return subprocess.CompletedProcess(args, 127, "", f"{args[0]} is unavailable")
        clean_env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        if env:
            clean_env.update(env)
        return subprocess.run([executable, *args[1:]], input=input_text, capture_output=True, text=True, timeout=timeout, check=False, shell=False, env=clean_env)

    @staticmethod
    def _checked_identifier(value: Any, label: str = "identifier") -> str:
        normalized = str(value or "").strip()
        if not IDENTIFIER_RE.fullmatch(normalized) or normalized.startswith("-"):
            api_error(400, "INVALID_IDENTIFIER", f"Invalid {label}")
        return normalized

    @staticmethod
    def _json_lines(output: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for line in output.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    @staticmethod
    def _result(result: subprocess.CompletedProcess[str], message: str) -> str:
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.strip() or result.stdout.strip() or message))
        return result.stdout


class PrivateBackupProvider(CommandProvider):
    @property
    def backup_dir(self) -> Path:
        path = Path(get_config().paths.data_dir) / "module-backups" / self.module_id
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def _backup_metadata(self, backup_id: str) -> tuple[Path, dict[str, Any]]:
        if not re.fullmatch(r"[a-f0-9]{24}", backup_id):
            api_error(400, "INVALID_BACKUP_ID", "Invalid backup identifier")
        metadata_path = self.backup_dir / f"{backup_id}.json"
        if not metadata_path.is_file():
            api_error(404, "BACKUP_NOT_FOUND", "Backup not found")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("Backup metadata is invalid") from error
        data_path = self.backup_dir / str(metadata.get("filename") or "")
        try:
            data_path.resolve().relative_to(self.backup_dir.resolve())
        except ValueError:
            api_error(422, "INVALID_BACKUP", "Backup path escapes its private directory")
        digest = hashlib.sha256()
        if data_path.is_file():
            with data_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        if not data_path.is_file() or digest.hexdigest() != metadata.get("checksum"):
            api_error(409, "BACKUP_CHECKSUM_MISMATCH", "Backup checksum verification failed")
        return data_path, metadata

    def _store_backup(self, actor: str, description: str, content: bytes, suffix: str, *, automatic: bool = False) -> dict[str, Any]:
        backup_id = secrets.token_hex(12)
        filename = f"{backup_id}{suffix}"
        data_path = self.backup_dir / filename
        tmp = data_path.with_suffix(data_path.suffix + ".tmp")
        with tmp.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, data_path)
        return self._register_backup(actor, description, data_path, automatic=automatic)

    def _register_backup(self, actor: str, description: str, data_path: Path, *, automatic: bool = False) -> dict[str, Any]:
        digest = hashlib.sha256()
        with data_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        backup_id = data_path.name.split(".", 1)[0]
        filename = data_path.name
        metadata = {
            "id": backup_id, "module_id": self.module_id, "created_at": time.time(), "created_by": actor,
            "description": description[:200], "automatic": automatic, "checksum": checksum,
            "package_version": self.get_status().package_version or "", "size": data_path.stat().st_size, "files": [filename], "filename": filename,
        }
        metadata_path = self.backup_dir / f"{backup_id}.json"
        metadata_tmp = self.backup_dir / f"{backup_id}.json.tmp"
        with metadata_tmp.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(metadata_tmp, 0o600)
        os.replace(metadata_tmp, metadata_path)
        self._prune_automatic()
        return ModuleBackup.model_validate(metadata).model_dump(mode="json")

    def _prune_automatic(self) -> None:
        automatic = [item for item in self.list_backups() if item["automatic"]]
        for item in automatic[20:]:
            self.delete_backup(item["id"])

    def list_backups(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in self.backup_dir.glob("*.json"):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                result.append(ModuleBackup.model_validate(metadata).model_dump(mode="json"))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def delete_backup(self, backup_id: str) -> None:
        data_path, _ = self._backup_metadata(backup_id)
        data_path.unlink(missing_ok=True)
        (self.backup_dir / f"{backup_id}.json").unlink(missing_ok=True)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        api_error(409, "RESTORE_NOT_IMPLEMENTED", "This module has no restore adapter")

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if action == PackageAction.restore:
            backup_id = str(payload.get("backup_id") or "")
            self._backup_metadata(backup_id)
            progress(15, "Backup checksum verified")
            if cancelled():
                raise InterruptedError("Restore cancelled before execution")
            safety = self.create_backup(actor, "Automatic safety backup before restore", automatic=True)
            progress(40, "Safety backup created")
            result = self.restore_backup(backup_id, actor, log)
            progress(95, "Restore completed")
            return {"safety_backup": safety, **result}
        return super().execute_operation(action, payload, actor, log, progress, cancelled)


class ApiConnectionProvider(PrivateBackupProvider):
    @property
    def connection_path(self) -> Path:
        path = Path(get_config().paths.data_dir) / "module-config"
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path / f"{self.module_id}.json"

    def connection(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.connection_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def public_connection(self) -> dict[str, Any]:
        config = self.connection()
        return {"base_url": config.get("base_url", self.default_base_url()), "username": config.get("username", ""), "secret_configured": bool(config.get("secret"))}

    def default_base_url(self) -> str:
        return "http://127.0.0.1"

    @staticmethod
    def _validate_base_url(value: str) -> str:
        if len(value) > 300:
            api_error(422, "INVALID_API_URL", "API URL is too long")
        parsed = urllib.parse.urlsplit(value.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            api_error(422, "INVALID_API_URL", "API URL must be an HTTP(S) origin without credentials, query or fragment")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        except OSError as error:
            raise HTTPConnectionError("API host cannot be resolved") from error
        if not addresses or any(not (ipaddress.ip_address(address).is_private or ipaddress.ip_address(address).is_loopback) for address in addresses):
            api_error(422, "API_HOST_NOT_PRIVATE", "Module APIs must resolve only to private or loopback addresses")
        return value.rstrip("/")

    def save_connection(self, base_url: str, username: str, secret: str | None) -> dict[str, Any]:
        current = self.connection()
        stored_secret = current.get("secret")
        next_secret = secret if secret else stored_secret
        value = {"base_url": self._validate_base_url(base_url), "username": username.strip()[:128], "secret": next_secret}
        if len(str(value["secret"])) > 2048:
            api_error(422, "SECRET_TOO_LONG", "API secret is too long")
        tmp = self.connection_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.connection_path)
        os.chmod(self.connection_path, 0o600)
        return self.public_connection()

    def _request(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 10) -> Any:
        config = self.connection()
        base = self._validate_base_url(str(config.get("base_url") or self.default_base_url()))
        if not path.startswith("/") or ".." in path:
            api_error(400, "INVALID_API_PATH", "Invalid module API path")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(base + path, data=data, method=method, headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
                content = response.read(2 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Module API returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise RuntimeError("Module API is unavailable") from error
        if len(content) > 2 * 1024 * 1024:
            raise RuntimeError("Module API response exceeds 2 MiB")
        return json.loads(content.decode("utf-8")) if content else {}


class HTTPConnectionError(RuntimeError):
    pass


def tool_status(provider: CommandProvider, command: str, service: str | None = None) -> ModuleStatus:
    executable = shutil.which(command)
    state = "not_installed"
    services: dict[str, dict[str, Any]] = {}
    if service and executable:
        result = provider._systemctl(service, "is-active")
        state = result.stdout.strip() or "inactive"
        services[service] = {"state": state, "enabled": provider._systemctl(service, "is-enabled").returncode == 0, "required": True}
    health = ModuleHealth.not_installed if not executable else ModuleHealth.healthy if not service or state == "active" else ModuleHealth.degraded
    return ModuleStatus(installed=bool(executable), service_state=state if service else "available" if executable else "not_installed", services=services, health=health, health_message="Available" if executable else f"{command} is not installed")
