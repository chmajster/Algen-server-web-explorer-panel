from __future__ import annotations

import json
import os
import re
import shutil
import socket
import struct
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
from .models import (
    NtpAllowedNetwork,
    NtpBackend,
    NtpConfiguration,
    NtpMode,
    NtpSourceInput,
    NtpSourceKind,
    validate_host,
)

_BEGIN = "# BEGIN WEBNAS NTP"
_END = "# END WEBNAS NTP"
_SERVER_RE = re.compile(r"^(?:server|pool)\s+(\S+)(.*)$")
_ALLOW_RE = re.compile(r"^allow\s+(\S+)$")
_NTP_EPOCH = 2_208_988_800


class NtpUnavailable(RuntimeError):
    pass


class NtpService:
    def __init__(self) -> None:
        data_root = Path(get_config().paths.data_dir)
        self.root = data_root / "ntp-manager"
        self.backups_root = data_root / "ntp-backups"
        self.settings_path = self.root / "settings.json"
        self.history_path = self.root / "history.jsonl"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backups_root.mkdir(parents=True, exist_ok=True, mode=0o700)

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
            response = BrokerClient().request(
                Operation.NTP,
                {"action": "service", "service_action": action, "unit": unit},
                actor=actor,
            )
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

    def _base_config_path(self, backend: NtpBackend) -> Path:
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

    def _config_path(self, backend: NtpBackend) -> Path:
        base = self._base_config_path(backend)
        if backend != NtpBackend.chrony:
            return base
        text = base.read_text(encoding="utf-8", errors="replace") if base.exists() else ""
        confdirs = (
            (re.compile(r"^\s*confdir\s+/etc/chrony/conf\.d\s*$", re.MULTILINE), Path("/etc/chrony/conf.d/webnas.conf")),
            (re.compile(r"^\s*confdir\s+/etc/chrony\.d\s*$", re.MULTILINE), Path("/etc/chrony.d/webnas.conf")),
        )
        for pattern, path in confdirs:
            if pattern.search(text):
                return path
        return base

    @staticmethod
    def _config_target(path: Path) -> str:
        mapping = {
            "/etc/chrony/chrony.conf": "chrony_debian",
            "/etc/chrony.conf": "chrony_rhel",
            "/etc/chrony/conf.d/webnas.conf": "chrony_debian_webnas",
            "/etc/chrony.d/webnas.conf": "chrony_rhel_webnas",
            "/etc/systemd/timesyncd.conf": "timesyncd",
            "/etc/ntp.conf": "ntpd",
        }
        normalized = str(path.resolve(strict=False))
        if normalized not in mapping:
            raise NtpUnavailable("NTP configuration path is not allowlisted")
        return mapping[normalized]

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
            elif "=" in line:
                key, value = line.split("=", 1)
            else:
                continue
            result[key.strip().casefold()] = value.strip().strip('"')
        return result

    def _read_settings(self) -> NtpConfiguration | None:
        if not self.settings_path.exists():
            return None
        try:
            return NtpConfiguration.model_validate_json(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_settings(self, configuration: NtpConfiguration) -> None:
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(configuration.model_dump_json(indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.settings_path)

    def _managed_text(self, backend: NtpBackend) -> str:
        path = self._config_path(backend)
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    def _managed_sources(self, text: str) -> list[NtpSourceInput]:
        if _BEGIN in text and _END in text:
            block = text.split(_BEGIN, 1)[1].split(_END, 1)[0]
        else:
            block = text
        result: list[NtpSourceInput] = []
        if "[Time]" in block:
            for line in block.splitlines():
                if line.strip().startswith("NTP="):
                    for server in line.split("=", 1)[1].split():
                        try:
                            result.append(NtpSourceInput(server=server, enabled=True))
                        except ValueError:
                            continue
            return result
        for line in block.splitlines():
            stripped = line.strip()
            enabled = not stripped.startswith("#")
            candidate = stripped.lstrip("#").strip()
            match = _SERVER_RE.match(candidate)
            if match:
                kind = NtpSourceKind.pool if candidate.startswith("pool ") else NtpSourceKind.server
                try:
                    result.append(
                        NtpSourceInput(
                            server=match.group(1),
                            kind=kind,
                            prefer=" prefer" in match.group(2),
                            enabled=enabled,
                        )
                    )
                except ValueError:
                    continue
        return result

    def _managed_networks(self, text: str) -> list[NtpAllowedNetwork]:
        block = text.split(_BEGIN, 1)[1].split(_END, 1)[0] if _BEGIN in text and _END in text else text
        result: list[NtpAllowedNetwork] = []
        for line in block.splitlines():
            stripped = line.strip()
            enabled = not stripped.startswith("#")
            match = _ALLOW_RE.match(stripped.lstrip("#").strip())
            if match:
                try:
                    result.append(NtpAllowedNetwork(cidr=match.group(1), enabled=enabled))
                except ValueError:
                    continue
        return result

    def _unmanaged_config_detected(self, backend: NtpBackend) -> bool:
        base = self._base_config_path(backend)
        if not base.exists():
            return False
        text = base.read_text(encoding="utf-8", errors="replace")
        outside = text.split(_BEGIN, 1)[0]
        if _END in text:
            outside += text.split(_END, 1)[1]
        if backend == NtpBackend.timesyncd:
            return any(line.strip().startswith(("NTP=", "FallbackNTP=")) and line.split("=", 1)[1].strip() for line in outside.splitlines())
        return any(_SERVER_RE.match(line.strip()) for line in outside.splitlines() if not line.strip().startswith("#"))

    def configuration(self) -> dict[str, Any]:
        backend = self.detect_backend()
        configured = self._read_settings()
        if configured is None:
            if backend == NtpBackend.none:
                configured = NtpConfiguration(mode=NtpMode.disabled)
            else:
                text = self._managed_text(backend)
                sources = self._managed_sources(text)
                networks = self._managed_networks(text) if backend == NtpBackend.chrony else []
                mode = NtpMode.client
                if networks:
                    mode = NtpMode.client_server if sources else NtpMode.server
                if not sources and not networks:
                    mode = NtpMode.disabled
                local_match = re.search(r"^\s*local\s+stratum\s+(\d+)\s*$", text, re.MULTILINE)
                configured = NtpConfiguration.model_construct(
                    mode=mode,
                    sources=sources,
                    allowed_networks=networks,
                    local_time_when_unsynced=bool(local_match),
                    local_stratum=int(local_match.group(1)) if local_match else 10,
                )
        return {
            **configured.model_dump(mode="json"),
            "backend": backend.value,
            "managed_path": str(self._config_path(backend)) if backend != NtpBackend.none else "",
            "unmanaged_config_detected": self._unmanaged_config_detected(backend) if backend != NtpBackend.none else False,
        }

    def _render(self, backend: NtpBackend, original: str, configuration: NtpConfiguration | list[NtpSourceInput]) -> str:
        if isinstance(configuration, list):
            configuration = NtpConfiguration.model_construct(
                mode=NtpMode.client,
                sources=configuration,
                allowed_networks=[],
                local_time_when_unsynced=False,
                local_stratum=10,
            )
        before = original.split(_BEGIN, 1)[0].rstrip()
        after = original.split(_END, 1)[1].lstrip() if _END in original else ""
        rows: list[str] = [_BEGIN]
        if backend == NtpBackend.timesyncd:
            if configuration.mode not in {NtpMode.disabled, NtpMode.client}:
                raise ValueError("systemd-timesyncd cannot operate as an NTP server")
            active = " ".join(item.server for item in configuration.sources if item.enabled) if configuration.mode == NtpMode.client else ""
            rows.extend(["[Time]", f"NTP={active}"])
        else:
            client_enabled = configuration.mode in {NtpMode.client, NtpMode.client_server}
            for item in configuration.sources:
                prefix = "" if item.enabled and client_enabled else "# "
                rows.append(f"{prefix}{item.kind.value} {item.server} iburst{' prefer' if item.prefer else ''}")
            if backend == NtpBackend.chrony and configuration.mode in {NtpMode.server, NtpMode.client_server}:
                for network in configuration.allowed_networks:
                    rows.append(f"{'' if network.enabled else '# '}allow {network.cidr}")
                if configuration.local_time_when_unsynced:
                    rows.append(f"local stratum {configuration.local_stratum}")
        rows.append(_END)
        block = "\n".join(rows)
        return "\n\n".join(part for part in (before, block, after.rstrip()) if part) + "\n"

    def _validate_candidate(self, backend: NtpBackend, candidate: str) -> dict[str, Any]:
        if "allow all" in candidate.casefold():
            raise ValueError("allow all is forbidden; configure explicit client networks")
        if backend != NtpBackend.chrony:
            return {"ok": True, "validator": "typed-webnas-validation", "output": ""}
        chronyd = self._which("chronyd")
        if not chronyd:
            return {"ok": True, "validator": "typed-webnas-validation", "output": "chronyd binary unavailable for native validation"}
        fd, name = tempfile.mkstemp(prefix="webnas-chrony-", suffix=".conf", dir=self.root)
        os.close(fd)
        candidate_path = Path(name)
        try:
            candidate_path.write_text(candidate, encoding="utf-8")
            result = self._run([chronyd, "-p", "-f", str(candidate_path)], timeout=15)
            if result.returncode != 0:
                raise ValueError((result.stderr or result.stdout or "chrony configuration validation failed")[:1000])
            return {"ok": True, "validator": "chronyd -p", "output": result.stdout[-2000:]}
        finally:
            candidate_path.unlink(missing_ok=True)

    def _backup(self, path: Path, original: str, *, actor: str, change: str, existed: bool) -> dict[str, Any]:
        backup_id = f"{int(time.time() * 1000)}-{os.getpid()}"
        data_path = self.backups_root / f"{backup_id}.conf"
        meta_path = self.backups_root / f"{backup_id}.json"
        data_path.write_text(original, encoding="utf-8")
        data_path.chmod(0o600)
        metadata = {
            "id": backup_id,
            "timestamp": time.time(),
            "actor": actor,
            "change": change,
            "path": str(path),
            "existed": existed,
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        meta_path.chmod(0o600)
        return metadata

    def list_backups(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.backups_root.glob("*.json"), reverse=True):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(item, dict) and item.get("id"):
                    items.append(item)
            except (OSError, json.JSONDecodeError):
                continue
        return items

    def apply_configuration(self, configuration: NtpConfiguration, *, actor: str, change: str = "config_apply") -> dict[str, Any]:
        backend = self.detect_backend()
        if configuration.mode in {NtpMode.server, NtpMode.client_server} and backend != NtpBackend.chrony:
            raise ValueError("NTP server mode requires chrony")
        if backend == NtpBackend.none:
            raise NtpUnavailable("No supported NTP backend is installed")
        path = self._config_path(backend)
        existed = path.exists()
        original = path.read_text(encoding="utf-8", errors="replace") if existed else ""
        candidate = self._render(backend, original, configuration)
        validation = self._validate_candidate(backend, candidate)
        backup = self._backup(path, original, actor=actor, change=change, existed=existed)
        unit = self._service_name(backend)
        try:
            self._write_config(path, candidate, actor=actor)
            if unit:
                result = self._mutating_service("restart", unit, actor=actor)
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout or "NTP restart failed")[:1000])
            self._write_settings(configuration)
        except Exception:
            self._write_config(path, original, actor=actor)
            if unit:
                self._mutating_service("restart", unit, actor=actor)
            raise
        return {
            "backend": backend.value,
            "path": str(path),
            "backup": backup,
            "validation": validation,
            "configuration": configuration.model_dump(mode="json"),
            "status": self.status(),
        }

    def save_sources(self, sources: list[NtpSourceInput], *, actor: str) -> dict[str, Any]:
        current = self.configuration()
        configuration = NtpConfiguration.model_validate(
            {
                "mode": current.get("mode", NtpMode.client.value),
                "sources": [item.model_dump(mode="json", exclude={"confirm"}) for item in sources],
                "allowed_networks": current.get("allowed_networks", []),
                "local_time_when_unsynced": current.get("local_time_when_unsynced", False),
                "local_stratum": current.get("local_stratum", 10),
            }
        )
        return self.apply_configuration(configuration, actor=actor, change="sources_update")

    def restore_backup(self, backup_id: str, *, actor: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]{10,16}-[0-9]+", backup_id):
            raise ValueError("invalid backup id")
        metadata_path = self.backups_root / f"{backup_id}.json"
        content_path = self.backups_root / f"{backup_id}.conf"
        if not metadata_path.exists() or not content_path.exists():
            raise FileNotFoundError("NTP backup not found")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        target = Path(str(metadata.get("path") or ""))
        self._config_target(target)
        current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        self._backup(target, current, actor=actor, change=f"before_restore:{backup_id}", existed=target.exists())
        restored = content_path.read_text(encoding="utf-8")
        self._validate_candidate(self.detect_backend(), restored)
        self._write_config(target, restored, actor=actor)
        unit = self._service_name(self.detect_backend())
        if unit:
            result = self._mutating_service("restart", unit, actor=actor)
            if result.returncode != 0:
                self._write_config(target, current, actor=actor)
                self._mutating_service("restart", unit, actor=actor)
                raise RuntimeError("NTP restore failed; previous configuration was restored")
        return {"restored": backup_id, "path": str(target), "status": self.status()}

    def status(self) -> dict[str, Any]:
        backend = self.detect_backend()
        timedate: dict[str, str] = {}
        timedatectl = self._which("timedatectl")
        if timedatectl:
            result = self._run(
                [timedatectl, "show", "--property=Timezone,NTPSynchronized,NTP,LocalRTC,TimeUSec,RTCTimeUSec"],
                timeout=8,
            )
            timedate = self._kv(result.stdout)
        configuration = self.configuration() if backend != NtpBackend.none else {"mode": NtpMode.disabled.value}
        data: dict[str, Any] = {
            "backend": backend.value,
            "available": backend != NtpBackend.none,
            "role": configuration.get("mode", NtpMode.disabled.value),
            "synchronized": timedate.get("ntpsynchronized", "no").casefold() == "yes",
            "timezone": timedate.get("timezone", ""),
            "system_time": time.time(),
            "local_time": timedate.get("timeusec", ""),
            "rtc_time": timedate.get("rtctimeusec", ""),
            "rtc_local_tz": timedate.get("localrtc", "no").casefold() == "yes",
            "ntp_service_enabled": timedate.get("ntp", "no").casefold() == "yes",
            "source": "",
            "offset": "",
            "stratum": None,
            "reachability": "",
            "jitter": "",
            "service": "",
            "service_state": "unknown",
            "enabled": False,
            "source_count": len(configuration.get("sources", [])),
            "unmanaged_config_detected": configuration.get("unmanaged_config_detected", False),
        }
        if backend != NtpBackend.none:
            unit = self._service_name(backend)
            data["service"] = unit
            if unit:
                active = self._systemctl("is-active", unit, timeout=8)
                enabled = self._systemctl("is-enabled", unit, timeout=8)
                data["service_state"] = active.stdout.strip() or "unknown"
                data["enabled"] = enabled.returncode == 0
        if backend == NtpBackend.chrony and self._which("chronyc"):
            values = self._kv(self._run([self._which("chronyc") or "chronyc", "tracking"], timeout=10).stdout)
            data.update(
                {
                    "source": values.get("reference id", ""),
                    "stratum": int(values["stratum"]) if values.get("stratum", "").isdigit() else None,
                    "offset": values.get("last offset", values.get("system time", "")),
                    "jitter": values.get("root dispersion", ""),
                    "last_sync": values.get("reference time (utc)", values.get("reference time", "")),
                    "leap_status": values.get("leap status", ""),
                }
            )
        return data

    def sources(self) -> list[dict[str, Any]]:
        backend = self.detect_backend()
        if backend == NtpBackend.none:
            return []
        if backend == NtpBackend.chrony and self._which("chronyc"):
            from .diagnostics import parse_chrony_sources

            result = self._run([self._which("chronyc") or "chronyc", "-n", "sources", "-v"], timeout=10)
            parsed = parse_chrony_sources(result.stdout) if result.returncode == 0 else []
            if parsed:
                return parsed
        path = self._config_path(backend)
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        return [item.model_dump(mode="json") for item in self._managed_sources(text)]

    def clients(self) -> list[dict[str, Any]]:
        if self.detect_backend() != NtpBackend.chrony or not self._which("chronyc"):
            return []
        result = self._run([self._which("chronyc") or "chronyc", "clients"], timeout=10)
        if result.returncode != 0:
            return []
        items: list[dict[str, Any]] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or line.startswith(("Hostname", "===")):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            address = parts[0]
            try:
                hostname = socket.gethostbyaddr(address)[0]
            except OSError:
                hostname = ""
            items.append(
                {
                    "address": address,
                    "hostname": hostname,
                    "ntp_requests": int(parts[1]) if parts[1].isdigit() else 0,
                    "dropped": int(parts[2]) if parts[2].isdigit() else 0,
                    "last_activity": parts[5] if len(parts) > 5 else "",
                }
            )
        return items

    def test_server(self, server: str) -> dict[str, Any]:
        server = validate_host(server)
        packet = bytearray(48)
        packet[0] = 0x1B
        started_wall = time.time()
        started = time.monotonic()
        errors: list[str] = []
        for family, socktype, proto, _canon, sockaddr in socket.getaddrinfo(server, 123, type=socket.SOCK_DGRAM):
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(3.0)
            try:
                sock.sendto(packet, sockaddr)
                data, _ = sock.recvfrom(512)
                received_wall = time.time()
                delay = time.monotonic() - started
                if len(data) < 48:
                    raise OSError("short NTP response")
                stratum = int(data[1])
                recv_sec, recv_frac = struct.unpack("!II", data[32:40])
                tx_sec, tx_frac = struct.unpack("!II", data[40:48])
                server_recv = recv_sec - _NTP_EPOCH + recv_frac / 2**32
                server_tx = tx_sec - _NTP_EPOCH + tx_frac / 2**32
                offset = ((server_recv - started_wall) + (server_tx - received_wall)) / 2.0
                return {
                    "server": server,
                    "ok": 1 <= stratum <= 15,
                    "address": sockaddr[0],
                    "stratum": stratum,
                    "offset_ms": round(offset * 1000, 3),
                    "delay_ms": round(delay * 1000, 3),
                    "status": "ok" if 1 <= stratum <= 15 else "invalid_stratum",
                }
            except OSError as error:
                errors.append(type(error).__name__)
            finally:
                sock.close()
        return {
            "server": server,
            "ok": False,
            "stratum": None,
            "offset_ms": None,
            "delay_ms": round((time.monotonic() - started) * 1000, 3),
            "status": "unreachable",
            "error": errors[-1] if errors else "resolution_failed",
        }

    def timezones(self) -> list[str]:
        binary = self._which("timedatectl")
        if not binary:
            return ["UTC"]
        result = self._run([binary, "list-timezones"], timeout=15)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else ["UTC"]

    def set_timezone(self, timezone: str, *, actor: str) -> dict[str, Any]:
        if timezone not in set(self.timezones()):
            raise ValueError("timezone is not present in timedatectl list-timezones")
        if broker_required():
            response = BrokerClient().request(Operation.NTP, {"action": "timezone", "timezone": timezone}, actor=actor)
            result = subprocess.CompletedProcess(["timedatectl", "set-timezone", timezone], response.exit_code, response.stdout, response.stderr)
        else:
            binary = self._which("timedatectl")
            if not binary:
                raise NtpUnavailable("timedatectl is unavailable")
            result = self._run([binary, "set-timezone", timezone], timeout=30)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "timezone change failed")[:500])
        return self.status()

    def firewall_status(self) -> dict[str, Any]:
        if broker_required():
            response = BrokerClient().request(Operation.NTP, {"action": "firewall_status"}, actor="ntp-manager")
            if response.exit_code == 0:
                try:
                    return json.loads(response.stdout)
                except json.JSONDecodeError:
                    pass
        if self._which("firewall-cmd"):
            result = self._run([self._which("firewall-cmd") or "firewall-cmd", "--query-port=123/udp"], timeout=10)
            return {"backend": "firewalld", "status": "open" if result.returncode == 0 else "blocked", "managed_by_webnas": False}
        if self._which("ufw"):
            result = self._run([self._which("ufw") or "ufw", "status"], timeout=10)
            open_port = any("123/udp" in line and "ALLOW" in line for line in result.stdout.splitlines())
            return {"backend": "ufw", "status": "open" if open_port else "blocked", "managed_by_webnas": "WebNAS NTP" in result.stdout}
        if self._which("nft"):
            result = self._run([self._which("nft") or "nft", "list", "ruleset"], timeout=10)
            open_port = bool(re.search(r"udp\s+dport\s+123\b.*\baccept\b", result.stdout))
            return {"backend": "nftables", "status": "open" if open_port else "blocked", "managed_by_webnas": "webnas-ntp" in result.stdout}
        return {"backend": "none", "status": "unknown", "managed_by_webnas": False}

    def open_firewall(self, *, actor: str) -> dict[str, Any]:
        if not broker_required():
            raise NtpUnavailable("firewall changes require the WebNAS privileged broker")
        response = BrokerClient().request(Operation.NTP, {"action": "firewall_open"}, actor=actor)
        if response.exit_code != 0:
            raise RuntimeError((response.stderr or response.stdout or "failed to open UDP/123")[:500])
        return self.firewall_status()

    def install_chrony(self, *, actor: str) -> dict[str, Any]:
        managers = [
            ("apt-get", ["install", "-y", "chrony"]),
            ("dnf", ["install", "-y", "chrony"]),
            ("yum", ["install", "-y", "chrony"]),
            ("zypper", ["--non-interactive", "install", "chrony"]),
        ]
        selected = next(((tool, args) for tool, args in managers if self._which(tool)), None)
        if not selected:
            raise NtpUnavailable("no supported package manager is available")
        tool, args = selected
        if broker_required():
            response = BrokerClient().request(Operation.PACKAGE, {"tool": tool, "args": args, "timeout": 600}, actor=actor)
            result = subprocess.CompletedProcess([tool, *args], response.exit_code, response.stdout, response.stderr)
        else:
            result = self._run([self._which(tool) or tool, *args], timeout=600)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "chrony installation failed")[:1000])
        return {"installed": self.detect_backend() == NtpBackend.chrony, "backend": self.detect_backend().value}

    def diagnostics(self) -> list[dict[str, Any]]:
        backend = self.detect_backend()
        status = self.status()
        items: list[dict[str, Any]] = []
        items.append({"code": "backend", "status": "PASS" if backend != NtpBackend.none else "FAIL", "detail": backend.value})
        items.append({"code": "service", "status": "PASS" if status.get("service_state") == "active" else "FAIL", "detail": str(status.get("service_state"))})
        items.append({"code": "synchronization", "status": "PASS" if status.get("synchronized") else "WARNING", "detail": str(status.get("source") or "no synchronized source")})
        firewall = self.firewall_status()
        role = str(status.get("role") or "")
        server_mode = role in {NtpMode.server.value, NtpMode.client_server.value}
        items.append({"code": "firewall", "status": "PASS" if not server_mode or firewall.get("status") == "open" else "WARNING", "detail": f"UDP/123: {firewall.get('status')} ({firewall.get('backend')})"})
        conflicts: list[str] = []
        active_units = []
        for unit in ("chrony", "chronyd", "systemd-timesyncd", "ntp", "ntpd"):
            if self._unit_exists(unit) and self._systemctl("is-active", unit, timeout=5).returncode == 0:
                active_units.append(unit)
        logical = set("chrony" if unit in {"chrony", "chronyd"} else "ntpd" if unit in {"ntp", "ntpd"} else unit for unit in active_units)
        if len(logical) > 1:
            conflicts = sorted(active_units)
        items.append({"code": "conflicts", "status": "FAIL" if conflicts else "PASS", "detail": ", ".join(conflicts) if conflicts else "no conflicting NTP services"})
        if backend != NtpBackend.none:
            try:
                candidate = self._managed_text(backend)
                validation = self._validate_candidate(backend, candidate)
                items.append({"code": "configuration", "status": "PASS", "detail": validation.get("validator", "validated")})
            except Exception as error:
                items.append({"code": "configuration", "status": "FAIL", "detail": str(error)[:300]})
        return items

    def _append_history(self, sample: dict[str, Any]) -> None:
        last_timestamp = 0.0
        if self.history_path.exists():
            try:
                with self.history_path.open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    size = stream.tell()
                    stream.seek(max(0, size - 4096))
                    lines = stream.read().decode("utf-8", errors="ignore").splitlines()
                    if lines:
                        last_timestamp = float(json.loads(lines[-1]).get("timestamp") or 0)
            except (OSError, ValueError, json.JSONDecodeError):
                last_timestamp = 0
        if time.time() - last_timestamp < 300:
            return
        with self.history_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
        self.history_path.chmod(0o600)

    def record_history(self) -> None:
        status = self.status()
        self._append_history(
            {
                "timestamp": time.time(),
                "server": status.get("source", ""),
                "stratum": status.get("stratum"),
                "offset": status.get("offset", ""),
                "synchronized": bool(status.get("synchronized")),
            }
        )

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in self.history_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    items.append(value)
            except json.JSONDecodeError:
                continue
        return items

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
        result_status = self.status()
        self.record_history()
        return result_status

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
        if action not in {"start", "stop", "restart"}:
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
