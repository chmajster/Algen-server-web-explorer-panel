from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ...config import get_config
from ...jobs.models import JobPriority
from ...jobs.service import JobContext, service as jobs
from ...privileged_broker.client import BrokerClient
from ...privileged_broker.protocol import Operation
from ...privileged_broker.runtime import broker_required
from .models import NtpBackend, NtpSourceInput

_BEGIN = "# BEGIN WEBNAS NTP"
_END = "# END WEBNAS NTP"
_SERVER_RE = re.compile(r"^(?:server|pool)\s+(\S+)(.*)$")


class NtpUnavailable(RuntimeError):
    pass


class NtpService:
    def _run(self, args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, shell=False)

    @staticmethod
    def _which(name: str) -> str | None:
        return shutil.which(name)

    def _systemctl(self, *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        binary = self._which("systemctl")
        if not binary:
            raise NtpUnavailable("systemctl is unavailable")
        return self._run([binary, *args], timeout=timeout)

    def _mutating_service(self, action: str, unit: str, *, actor: str) -> subprocess.CompletedProcess[str]:
        if broker_required():
            response = BrokerClient().request(Operation.NTP, {"action": "service", "service_action": action, "unit": unit}, actor=actor)
            return subprocess.CompletedProcess(["systemctl", action, unit], response.exit_code, response.stdout, response.stderr)
        return self._systemctl(action, unit, timeout=45)

    def _unit_exists(self, unit: str) -> bool:
        try:
            result = self._systemctl("show", unit, "--property=LoadState", "--value", timeout=8)
        except NtpUnavailable:
            return False
        return result.returncode == 0 and result.stdout.strip() not in {"", "not-found"}

    def detect_backend(self) -> NtpBackend:
        candidates = [
            (NtpBackend.chrony, "chronyc", ("chrony", "chronyd")),
            (NtpBackend.timesyncd, "timedatectl", ("systemd-timesyncd",)),
            (NtpBackend.ntpd, "ntpq", ("ntp", "ntpd")),
        ]
        available: list[NtpBackend] = []
        for backend, executable, units in candidates:
            if not self._which(executable):
                continue
            available.append(backend)
            for unit in units:
                if self._unit_exists(unit) and self._systemctl("is-active", unit, timeout=8).returncode == 0:
                    return backend
        return available[0] if available else NtpBackend.none

    def _service_name(self, backend: NtpBackend) -> str:
        candidates = {
            NtpBackend.chrony: ("chrony", "chronyd"),
            NtpBackend.timesyncd: ("systemd-timesyncd",),
            NtpBackend.ntpd: ("ntp", "ntpd"),
        }.get(backend, ())
        for unit in candidates:
            if self._unit_exists(unit):
                return unit
        return candidates[0] if candidates else ""

    def _config_path(self, backend: NtpBackend) -> Path:
        candidates = {
            NtpBackend.chrony: (Path("/etc/chrony/chrony.conf"), Path("/etc/chrony.conf")),
            NtpBackend.timesyncd: (Path("/etc/systemd/timesyncd.conf"),),
            NtpBackend.ntpd: (Path("/etc/ntp.conf"),),
        }.get(backend, ())
        for path in candidates:
            if path.exists():
                return path
        if not candidates:
            raise NtpUnavailable("No supported NTP backend is installed")
        return candidates[0]

    @staticmethod
    def _config_target(path: Path) -> str:
        mapping = {
            "/etc/chrony/chrony.conf": "chrony_debian",
            "/etc/chrony.conf": "chrony_rhel",
            "/etc/systemd/timesyncd.conf": "timesyncd",
            "/etc/ntp.conf": "ntpd",
        }
        try:
            return mapping[str(path.resolve(strict=False))]
        except KeyError as error:
            raise NtpUnavailable("NTP configuration path is not allowlisted") from error

    def _write_config(self, path: Path, content: str, *, actor: str) -> None:
        if broker_required():
            BrokerClient().require(
                Operation.NTP,
                {"action": "write_config", "target": self._config_target(path), "content": content},
                actor=actor,
            )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.webnas-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_name, 0o644)
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _kv(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                result[key.strip().casefold()] = value.strip()
            elif "=" in line:
                key, value = line.split("=", 1)
                result[key.strip().casefold()] = value.strip()
        return result

    def status(self) -> dict[str, Any]:
        backend = self.detect_backend()
        timedate: dict[str, str] = {}
        timedatectl = self._which("timedatectl")
        if timedatectl:
            result = self._run([timedatectl, "show", "--property=Timezone,NTPSynchronized,NTP,TimeUSec"], timeout=8)
            timedate = self._kv(result.stdout)
        data: dict[str, Any] = {
            "backend": backend.value,
            "available": backend != NtpBackend.none,
            "synchronized": timedate.get("ntpsynchronized", "no").casefold() == "yes",
            "timezone": timedate.get("timezone", ""),
            "system_time": time.time(),
            "source": "",
            "offset": "",
            "stratum": None,
            "reachability": "",
            "jitter": "",
            "service": "",
            "service_state": "unknown",
            "enabled": False,
        }
        if backend != NtpBackend.none:
            unit = self._service_name(backend)
            data["service"] = unit
            if unit:
                active = self._systemctl("is-active", unit, timeout=8)
                enabled = self._systemctl("is-enabled", unit, timeout=8)
                data["service_state"] = active.stdout.strip() or "unknown"
                data["enabled"] = enabled.returncode == 0
        if backend == NtpBackend.chrony:
            chronyc = self._which("chronyc")
            if chronyc:
                values = self._kv(self._run([chronyc, "tracking"], timeout=10).stdout)
                data.update(
                    {
                        "source": values.get("reference id", ""),
                        "stratum": int(values["stratum"]) if values.get("stratum", "").isdigit() else None,
                        "offset": values.get("last offset", values.get("system time", "")),
                        "jitter": values.get("root dispersion", ""),
                        "leap_status": values.get("leap status", ""),
                    }
                )
        return data

    def sources(self) -> list[dict[str, Any]]:
        backend = self.detect_backend()
        if backend == NtpBackend.none:
            return []
        if backend == NtpBackend.chrony and self._which("chronyc"):
            result = self._run([self._which("chronyc") or "chronyc", "-n", "sources"], timeout=10)
            items: list[dict[str, Any]] = []
            for line in result.stdout.splitlines():
                match = re.match(r"^([\^=][*+\-?x~])\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+)$", line.strip())
                if match:
                    marker, server, stratum, poll, reach, rest = match.groups()
                    items.append(
                        {
                            "server": server,
                            "selected": marker[1] == "*",
                            "state": marker[1],
                            "stratum": int(stratum),
                            "poll": int(poll),
                            "reach": int(reach),
                            "details": rest,
                        }
                    )
            return items
        path = self._config_path(backend)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        items: list[dict[str, Any]] = []
        if backend == NtpBackend.timesyncd:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("NTP=") or stripped.startswith("FallbackNTP="):
                    key, values = stripped.split("=", 1)
                    for server in values.split():
                        items.append({"server": server, "selected": False, "state": "configured", "kind": key})
        else:
            for line in text.splitlines():
                match = _SERVER_RE.match(line.strip().lstrip("#").strip())
                if match:
                    items.append({"server": match.group(1), "selected": False, "state": "configured", "enabled": not line.lstrip().startswith("#")})
        return items

    def test_server(self, server: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(server, 123, type=socket.SOCK_DGRAM)})
        except OSError as error:
            return {"server": server, "ok": False, "error": str(error)[:300], "addresses": []}
        return {"server": server, "ok": bool(addresses), "addresses": addresses[:8], "dns_ms": round((time.monotonic() - started) * 1000, 2)}

    def _managed_sources(self, text: str) -> list[NtpSourceInput]:
        if _BEGIN not in text or _END not in text:
            return []
        block = text.split(_BEGIN, 1)[1].split(_END, 1)[0]
        result: list[NtpSourceInput] = []
        if "[Time]" in block:
            for line in block.splitlines():
                if line.strip().startswith("NTP="):
                    for server in line.split("=", 1)[1].split():
                        result.append(NtpSourceInput(server=server, enabled=True))
            return result
        for line in block.splitlines():
            stripped = line.strip()
            enabled = not stripped.startswith("#")
            match = _SERVER_RE.match(stripped.lstrip("#").strip())
            if match:
                result.append(NtpSourceInput(server=match.group(1), prefer=" prefer" in match.group(2), enabled=enabled))
        return result

    def _render(self, backend: NtpBackend, original: str, sources: list[NtpSourceInput]) -> str:
        before = original.split(_BEGIN, 1)[0].rstrip()
        after = original.split(_END, 1)[1].lstrip() if _END in original else ""
        if backend == NtpBackend.timesyncd:
            active = " ".join(item.server for item in sources if item.enabled)
            block = f"{_BEGIN}\n[Time]\nNTP={active}\n{_END}"
        else:
            rows = [f"{'' if item.enabled else '# '}server {item.server} iburst{' prefer' if item.prefer else ''}" for item in sources]
            block = "\n".join([_BEGIN, *rows, _END])
        return "\n\n".join(part for part in (before, block, after.rstrip()) if part) + "\n"

    def save_sources(self, sources: list[NtpSourceInput], *, actor: str) -> dict[str, Any]:
        backend = self.detect_backend()
        if backend == NtpBackend.none:
            raise NtpUnavailable("No supported NTP backend is installed")
        path = self._config_path(backend)
        original = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        candidate = self._render(backend, original, sources)
        data_dir = Path(get_config().paths.data_dir) / "ntp-backups"
        data_dir.mkdir(parents=True, exist_ok=True)
        backup = data_dir / f"{path.name}.{int(time.time())}.bak"
        backup.write_text(original, encoding="utf-8")
        backup.chmod(0o600)
        try:
            self._write_config(path, candidate, actor=actor)
            unit = self._service_name(backend)
            if unit:
                result = self._mutating_service("restart", unit, actor=actor)
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout or "NTP restart failed")[:500])
        except Exception:
            self._write_config(path, original, actor=actor)
            raise
        return {"backend": backend.value, "path": str(path), "backup": str(backup), "sources": len(sources)}

    def resync(self, context: JobContext, metadata: dict[str, Any]) -> dict[str, Any]:
        backend = self.detect_backend()
        actor = str(metadata.get("actor") or "webnas")
        context.set_progress(20, "Detected NTP backend", current_step="detect")
        unit = self._service_name(backend)
        if broker_required():
            response = BrokerClient().request(Operation.NTP, {"action": "resync", "backend": backend.value, "unit": unit}, actor=actor)
            result = subprocess.CompletedProcess(["ntp-resync"], response.exit_code, response.stdout, response.stderr)
        elif backend == NtpBackend.chrony:
            binary = self._which("chronyc")
            if not binary:
                raise NtpUnavailable("chronyc is unavailable")
            result = self._run([binary, "makestep"], timeout=30)
        elif backend in {NtpBackend.timesyncd, NtpBackend.ntpd}:
            result = self._systemctl("restart", unit, timeout=30)
        else:
            raise NtpUnavailable("No supported NTP backend is installed")
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "NTP resync failed")[:500])
        context.set_progress(100, "NTP resync complete", current_step="verify")
        return self.status()

    def enqueue_resync(self, actor: str):
        return jobs().submit_callable(
            job_type="ntp.resync",
            module="ntp-manager",
            created_by=actor,
            handler=self.resync,
            metadata={"actor": actor},
            retryable=True,
            cancellable=False,
            priority=JobPriority.high,
            max_retries=1,
            timeout=60,
            name="NTP resync",
            description="Force time synchronization and verify state",
            dedup_key="ntp.resync",
            total_steps=2,
        )

    def service_action(self, action: str, *, actor: str) -> dict[str, Any]:
        if action not in {"start", "stop", "restart", "reload", "enable", "disable"}:
            raise ValueError("unsupported service action")
        backend = self.detect_backend()
        unit = self._service_name(backend)
        if not unit:
            raise NtpUnavailable("NTP service is unavailable")
        result = self._mutating_service(action, unit, actor=actor)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "NTP service action failed")[:500])
        return self.status()


_instance: NtpService | None = None


def service() -> NtpService:
    global _instance
    if _instance is None:
        _instance = NtpService()
    return _instance
