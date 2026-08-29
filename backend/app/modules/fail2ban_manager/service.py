from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...core.events import bus
from .models import JailConfigInput

JAIL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.,:/@*+\-\[\] ]*$")


class Fail2BanUnavailable(RuntimeError):
    pass


class Fail2BanCommandError(RuntimeError):
    def __init__(self, message: str, *, command: str = "", output: str = "") -> None:
        super().__init__(message)
        self.command = command
        self.output = output[:4000]


class Fail2BanService:
    def __init__(self, *, jail_dir: Path = Path("/etc/fail2ban/jail.d"), timeout: float = 12.0) -> None:
        self.jail_dir = jail_dir
        self.timeout = timeout
        self.client = shutil.which("fail2ban-client")
        self.systemctl = shutil.which("systemctl")
        self.journalctl = shutil.which("journalctl")
        self._lock = threading.RLock()

    @staticmethod
    def _jail(value: str) -> str:
        value = value.strip()
        if not JAIL_NAME.fullmatch(value):
            raise ValueError("invalid Fail2Ban jail name")
        return value

    @staticmethod
    def _ip(value: str) -> str:
        return str(ipaddress.ip_address(value.strip()))

    def _run(self, args: list[str], *, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        if not args or not os.path.isabs(args[0]):
            raise ValueError("Fail2Ban commands require an absolute executable path")
        try:
            result = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Fail2BanCommandError(type(error).__name__, command=Path(args[0]).name) from error
        if check and result.returncode != 0:
            raise Fail2BanCommandError(
                f"{Path(args[0]).name} exited with status {result.returncode}",
                command=Path(args[0]).name,
                output=result.stdout,
            )
        return result

    def _client(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        if not self.client:
            raise Fail2BanUnavailable("fail2ban-client is not installed")
        return self._run([self.client, *args], check=check)

    def _systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        if not self.systemctl:
            raise Fail2BanUnavailable("systemctl is not available")
        return self._run([self.systemctl, *args], check=check)

    def installed(self) -> bool:
        return bool(self.client)

    def version(self) -> str:
        if not self.client:
            return ""
        output = self._client("version", check=False).stdout.strip()
        return output.splitlines()[0][:120] if output else ""

    @staticmethod
    def _line_value(output: str, label: str) -> str:
        for line in output.splitlines():
            normalized = line.strip().lstrip("|-` ")
            if normalized.startswith(label + ":"):
                return normalized.split(":", 1)[1].strip()
        return ""

    def jail_names(self) -> list[str]:
        if not self.client:
            return []
        output = self._client("status", check=False).stdout
        raw = self._line_value(output, "Jail list")
        return sorted({self._jail(item) for item in raw.split(",") if item.strip()}) if raw else []

    def jail_status(self, jail: str) -> dict[str, Any]:
        jail = self._jail(jail)
        result = self._client("status", jail, check=False)
        if result.returncode != 0:
            return {
                "name": jail,
                "enabled": False,
                "status": "unavailable",
                "banned_count": 0,
                "total_banned": 0,
                "banned_ips": [],
            }
        output = result.stdout
        banned = self._line_value(output, "Banned IP list")
        ips = []
        for value in banned.split():
            try:
                ips.append(str(ipaddress.ip_address(value)))
            except ValueError:
                continue
        current = self._line_value(output, "Currently banned")
        total = self._line_value(output, "Total banned")
        return {
            "name": jail,
            "enabled": True,
            "status": "active",
            "filter": self._line_value(output, "Filter"),
            "backend": "",
            "port": "",
            "maxretry": None,
            "findtime": "",
            "bantime": "",
            "action": "",
            "banned_count": int(current) if current.isdigit() else len(ips),
            "total_banned": int(total) if total.isdigit() else 0,
            "banned_ips": ips,
        }

    def status(self) -> dict[str, Any]:
        installed = self.installed()
        service_active = False
        service_enabled = False
        if self.systemctl:
            service_active = self._systemctl("is-active", "fail2ban", check=False).returncode == 0
            service_enabled = self._systemctl("is-enabled", "fail2ban", check=False).returncode == 0
        ping = self._client("ping", check=False).returncode == 0 if self.client else False
        names = self.jail_names() if ping else []
        jails = [self.jail_status(name) for name in names]
        return {
            "installed": installed,
            "client_available": bool(self.client),
            "version": self.version(),
            "service_active": service_active,
            "service_enabled": service_enabled,
            "responding": ping,
            "active_jails": len(names),
            "currently_banned": sum(int(item["banned_count"]) for item in jails),
            "total_banned": sum(int(item["total_banned"]) for item in jails),
            "jails": jails,
        }

    def ban(self, jail: str, address: str) -> dict[str, Any]:
        jail = self._jail(jail)
        address = self._ip(address)
        self._client("set", jail, "banip", address)
        bus.publish("fail2ban.ip_banned", {"jail": jail, "ip": address})
        return {"ok": True, "jail": jail, "ip": address}

    def unban(self, jail: str, address: str) -> dict[str, Any]:
        jail = self._jail(jail)
        address = self._ip(address)
        self._client("set", jail, "unbanip", address)
        bus.publish("fail2ban.ip_unbanned", {"jail": jail, "ip": address})
        return {"ok": True, "jail": jail, "ip": address}

    def reload(self) -> dict[str, Any]:
        self._client("reload")
        bus.publish("fail2ban.service_changed", {"action": "reload"})
        return {"ok": True, "action": "reload"}

    def restart(self) -> dict[str, Any]:
        self._systemctl("restart", "fail2ban")
        bus.publish("fail2ban.service_changed", {"action": "restart"})
        return {"ok": True, "action": "restart"}

    @staticmethod
    def _safe_config_value(value: str, field: str) -> str:
        if not value:
            return ""
        if not SAFE_TOKEN.fullmatch(value):
            raise ValueError(f"invalid characters in {field}")
        return value

    def _render_config(self, jail: str, payload: JailConfigInput) -> str:
        jail = self._jail(jail)
        lines = [
            "# Managed by WebNAS Fail2Ban Manager. Manual changes may be replaced.",
            f"[{jail}]",
            f"enabled = {'true' if payload.enabled else 'false'}",
        ]
        for name, raw in (
            ("filter", payload.filter),
            ("backend", payload.backend),
            ("port", payload.port),
            ("findtime", payload.findtime),
            ("bantime", payload.bantime),
            ("action", payload.action),
        ):
            value = self._safe_config_value(raw, name)
            if value:
                lines.append(f"{name} = {value}")
        if payload.maxretry is not None:
            lines.append(f"maxretry = {payload.maxretry}")
        return "\n".join(lines) + "\n"

    def config_path(self, jail: str) -> Path:
        return self.jail_dir / f"webnas-{self._jail(jail)}.local"

    def read_managed_config(self, jail: str) -> dict[str, Any]:
        path = self.config_path(jail)
        return {"jail": self._jail(jail), "path": str(path), "managed": path.exists(), "content": path.read_text(encoding="utf-8") if path.exists() else ""}

    def save_config(self, jail: str, payload: JailConfigInput) -> dict[str, Any]:
        jail = self._jail(jail)
        candidate = self._render_config(jail, payload)
        path = self.config_path(jail)
        self.jail_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            previous = path.read_bytes() if path.exists() else None
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".webnas-{jail}-", suffix=".local", dir=self.jail_dir)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(candidate)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o644)
                os.replace(temporary, path)
                directory_fd = os.open(self.jail_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                validation = self._client("-t", check=False)
                if validation.returncode != 0:
                    raise Fail2BanCommandError("Fail2Ban configuration validation failed", command="fail2ban-client", output=validation.stdout)
                reload_result = self._client("reload", check=False)
                if reload_result.returncode != 0:
                    raise Fail2BanCommandError("Fail2Ban reload failed", command="fail2ban-client", output=reload_result.stdout)
            except Exception:
                try:
                    if previous is None:
                        path.unlink(missing_ok=True)
                    else:
                        rollback = path.with_name(f".{path.name}.rollback")
                        rollback.write_bytes(previous)
                        os.chmod(rollback, 0o644)
                        os.replace(rollback, path)
                    if self.client:
                        self._client("reload", check=False)
                finally:
                    temporary.unlink(missing_ok=True)
                raise
            finally:
                temporary.unlink(missing_ok=True)
        bus.publish("fail2ban.jail_changed", {"jail": jail, "enabled": payload.enabled})
        return {"ok": True, "jail": jail, "path": str(path), "enabled": payload.enabled}

    def set_enabled(self, jail: str, enabled: bool) -> dict[str, Any]:
        current = self.read_managed_config(jail)
        values: dict[str, Any] = {"enabled": enabled, "confirm": True}
        if current["content"]:
            for line in current["content"].splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]
                if key in {"filter", "backend", "port", "findtime", "bantime", "action"}:
                    values[key] = value
                elif key == "maxretry" and value.isdigit():
                    values[key] = int(value)
        return self.save_config(jail, JailConfigInput.model_validate(values))

    def logs(self, *, limit: int = 250, query: str = "", jail: str = "", address: str = "", action: str = "") -> list[dict[str, str]]:
        if not self.journalctl:
            raise Fail2BanUnavailable("journalctl is not available")
        limit = max(1, min(int(limit), 2000))
        output = self._run(
            [self.journalctl, "-u", "fail2ban", "--no-pager", "-n", str(limit), "-o", "short-iso"],
            timeout=max(self.timeout, 20),
        ).stdout
        query_lower = query.lower().strip()
        jail_lower = self._jail(jail).lower() if jail else ""
        ip_value = self._ip(address) if address else ""
        action_lower = action.lower().strip()
        if action_lower and action_lower not in {"ban", "unban"}:
            raise ValueError("action must be ban or unban")
        result: list[dict[str, str]] = []
        for line in output.splitlines():
            lower = line.lower()
            if query_lower and query_lower not in lower:
                continue
            if jail_lower and f"[{jail_lower}]" not in lower:
                continue
            if ip_value and not re.search(
                rf"(?<![0-9A-Fa-f:.]){re.escape(ip_value)}(?![0-9A-Fa-f:.])", line
            ):
                continue
            if action_lower and not re.search(rf"\b{re.escape(action_lower)}\b", lower):
                continue
            timestamp, _, message = line.partition(" ")
            result.append({"timestamp": timestamp[:40], "message": message[:4000]})
        return result


@lru_cache(maxsize=1)
def service() -> Fail2BanService:
    return Fail2BanService()
