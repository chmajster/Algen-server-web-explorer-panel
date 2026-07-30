#!/usr/bin/env python3
"""Hosts Manager Linux agent.

The agent intentionally uses only the Python standard library so it can run on
APT, DNF/YUM, Zypper, Pacman and APK based systems without a Python package
bootstrap step. JSON is used inside the .yaml configuration file; JSON is a
valid YAML 1.2 subset and keeps the runtime dependency-free.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


VERSION = "1.0.0"
DEFAULT_CONFIG = Path("/etc/hosts-manager-agent/config.yaml")
DEFAULT_STATE = Path("/var/lib/hosts-manager-agent/state.json")
DEFAULT_LOG = Path("/var/log/hosts-manager-agent/agent.log")


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def command(args: list[str], timeout: int = 10, accepted_codes: tuple[int, ...] = (0,)) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode in accepted_codes else ""


def os_release() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.lower()] = value.strip().strip("\"'")
    return result


def memory() -> dict[str, int | float]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - available)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent": round(used * 100 / total, 2) if total else 0,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0, swap_total - swap_free),
        "swap_percent": round((swap_total - swap_free) * 100 / swap_total, 2) if swap_total else 0,
    }


def uptime_seconds() -> int:
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return 0


def addresses() -> list[str]:
    result: list[str] = []
    try:
        records = socket.getaddrinfo(socket.gethostname(), None)
    except socket.gaierror:
        records = []
    for record in records:
        raw_address = record[4][0]
        if not isinstance(raw_address, str):
            continue
        address = raw_address.split("%", 1)[0]
        if address not in {"127.0.0.1", "::1"} and address not in result:
            result.append(address)
    route = command(["ip", "-j", "address"], timeout=5)
    if route:
        try:
            for interface in json.loads(route):
                for item in interface.get("addr_info", []):
                    address = str(item.get("local") or "")
                    if address and address not in {"127.0.0.1", "::1"} and address not in result:
                        result.append(address)
        except (ValueError, TypeError):
            pass
    return result


def interfaces() -> list[dict[str, Any]]:
    result = []
    root = Path("/sys/class/net")
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        try:
            mac = (path / "address").read_text().strip()
            state = (path / "operstate").read_text().strip()
        except OSError:
            mac, state = "", "unknown"
        result.append({"name": path.name, "mac_address": mac, "state": state})
    return result


def filesystems() -> list[dict[str, Any]]:
    output = command(["df", "-P", "-k"], timeout=10)
    result = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            total, used, available = (int(parts[1]) * 1024, int(parts[2]) * 1024, int(parts[3]) * 1024)
        except ValueError:
            continue
        result.append({
            "device": parts[0],
            "mountpoint": parts[-1],
            "total_bytes": total,
            "used_bytes": used,
            "available_bytes": available,
            "used_percent": round(used * 100 / total, 2) if total else 0,
            "free_percent": round(available * 100 / total, 2) if total else 0,
        })
    return result


def disks() -> list[dict[str, Any]]:
    output = command(["lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINT"], timeout=10)
    try:
        value = json.loads(output)
    except (ValueError, TypeError):
        return []
    return value.get("blockdevices", []) if isinstance(value, dict) else []


def cpu_info() -> dict[str, Any]:
    model = ""
    physical: set[tuple[str, str]] = set()
    try:
        current: dict[str, str] = {}
        for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines() + [""]:
            if not line:
                if current:
                    physical.add((current.get("physical id", "0"), current.get("core id", current.get("processor", "0"))))
                    model = model or current.get("model name", current.get("Processor", ""))
                    current = {}
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                current[key.strip()] = value.strip()
    except OSError:
        pass
    threads = os.cpu_count() or 0
    return {
        "model": model or platform.processor(),
        "sockets": 1,
        "cores": len(physical) or threads,
        "threads": threads,
    }


def cpu_usage_percent() -> float:
    def sample() -> tuple[int, int]:
        try:
            values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        except (OSError, ValueError, IndexError):
            return 0, 0
        idle = sum(values[3:5])
        return sum(values), idle

    total_before, idle_before = sample()
    time.sleep(0.1)
    total_after, idle_after = sample()
    total_delta = total_after - total_before
    idle_delta = idle_after - idle_before
    return round(max(0.0, min(100.0, (total_delta - idle_delta) * 100 / total_delta)), 2) if total_delta else 0.0


def dmi_value(name: str) -> str:
    try:
        return (Path("/sys/class/dmi/id") / name).read_text(errors="replace").strip()
    except OSError:
        return ""


def package_manager() -> str:
    for name in ("apt-get", "dnf", "yum", "zypper", "pacman", "apk"):
        if shutil.which(name):
            return name.removesuffix("-get")
    return "unknown"


def package_summary(manager: str) -> dict[str, Any]:
    installed_count = 0
    available_updates = 0
    security_updates = 0
    installed_packages: list[str] = []
    available_update_items: list[str] = []
    repositories: list[str] = []
    if manager == "apt":
        installed_packages = command(["dpkg-query", "-W", "-f=${binary:Package}=${Version}\\n"], 30).splitlines()
        installed_count = len(installed_packages)
        updates = [
            line for line in command(["apt-get", "-s", "upgrade"], 30).splitlines()
            if line.startswith("Inst ")
        ]
        available_updates = len(updates)
        available_update_items = updates
        security_updates = sum("-security" in line.lower() or "security" in line.lower() for line in updates)
        for path in [Path("/etc/apt/sources.list"), *Path("/etc/apt/sources.list.d").glob("*.list")]:
            try:
                repositories.extend(
                    line.strip() for line in path.read_text(errors="replace").splitlines()
                    if line.strip().startswith(("deb ", "deb-src "))
                )
            except OSError:
                pass
    elif manager in {"dnf", "yum"}:
        installed_packages = command(["rpm", "-qa"], 30).splitlines()
        installed_count = len(installed_packages)
        repositories = command([manager, "repolist", "--enabled", "-q"], 20).splitlines()
        updates = command([manager, "check-update", "-q"], 30, (0, 100)).splitlines()
        available_update_items = [
            line for line in updates
            if bool(line.split()) and "." in line.split()[0] and len(line.split()) >= 3
        ]
        available_updates = len(available_update_items)
        security_updates = sum(
            bool(line.split()) and not line.lstrip().startswith(("Last ", "Obsoleting"))
            for line in command([manager, "updateinfo", "list", "--security", "-q"], 30, (0, 100)).splitlines()
        )
    elif manager == "zypper":
        installed_packages = command(["rpm", "-qa"], 30).splitlines()
        installed_count = len(installed_packages)
        repositories = command(["zypper", "--non-interactive", "lr", "-u"], 20).splitlines()
        updates = command(["zypper", "--non-interactive", "list-updates"], 30, (0, 100)).splitlines()
        available_update_items = [line for line in updates if line.startswith("v |")]
        available_updates = len(available_update_items)
        security_updates = sum("security" in line.lower() for line in updates if line.startswith("v |"))
    elif manager == "pacman":
        installed_packages = command(["pacman", "-Q"], 30).splitlines()
        installed_count = len(installed_packages)
        available_update_items = command(["pacman", "-Qu"], 30, (0, 1)).splitlines()
        available_updates = len(available_update_items)
        try:
            repositories = [
                line.strip() for line in Path("/etc/pacman.conf").read_text(errors="replace").splitlines()
                if line.strip().startswith("[") and line.strip() != "[options]"
            ]
        except OSError:
            pass
    elif manager == "apk":
        installed_packages = command(["apk", "info", "-v"], 30).splitlines()
        installed_count = len(installed_packages)
        available_update_items = command(["apk", "version", "-l", "<"], 30, (0, 1)).splitlines()
        available_updates = len(available_update_items)
        try:
            repositories = [
                line.strip() for line in Path("/etc/apk/repositories").read_text(errors="replace").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        except OSError:
            pass
    history_paths = {
        "apt": Path("/var/log/dpkg.log"),
        "dnf": Path("/var/log/dnf.log"),
        "yum": Path("/var/log/yum.log"),
        "zypper": Path("/var/log/zypp/history"),
        "pacman": Path("/var/log/pacman.log"),
        "apk": Path("/lib/apk/db/installed"),
    }
    history_path = history_paths.get(manager)
    history: list[str] = []
    last_system_update_at = 0.0
    if history_path:
        try:
            last_system_update_at = history_path.stat().st_mtime
            history = [line[:500] for line in history_path.read_text(errors="replace").splitlines()[-200:]]
        except OSError:
            pass
    return {
        "manager": manager,
        "installed_count": installed_count,
        "available_updates_count": available_updates,
        "security_updates_count": security_updates,
        "installed_packages": installed_packages[:20_000],
        "available_updates": available_update_items[:2_000],
        "last_system_update_at": last_system_update_at,
        "history": history,
        "repositories": repositories[:500],
    }


def network_configuration() -> dict[str, Any]:
    nameservers: list[str] = []
    search: list[str] = []
    try:
        for line in Path("/etc/resolv.conf").read_text(errors="replace").splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] == "nameserver":
                nameservers.append(fields[1])
            elif len(fields) >= 2 and fields[0] in {"search", "domain"}:
                search.extend(fields[1:])
    except OSError:
        pass
    return {
        "default_routes": (
            command(["ip", "-4", "route", "show", "default"], 5).splitlines()
            + command(["ip", "-6", "route", "show", "default"], 5).splitlines()
        )[:50],
        "dns_nameservers": nameservers[:20],
        "dns_search": search[:20],
    }


def agent_log_tail(path: Path) -> list[str]:
    try:
        lines = path.read_text(errors="replace").splitlines()[-100:]
    except OSError:
        return []
    return [
        re.sub(
            r"(?i)(authorization:\s*bearer|token[\"'=:\s]+)\s*[A-Za-z0-9._~+/=-]{12,}",
            r"\1 [REDACTED]",
            line[:2_000],
        )
        for line in lines
    ]


def service_summary() -> dict[str, Any]:
    if not shutil.which("systemctl"):
        return {"init_system": "other", "active": [], "failed": []}
    active = command(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"], 15)
    failed = command(["systemctl", "list-units", "--type=service", "--state=failed", "--no-legend", "--no-pager"], 15)
    return {
        "init_system": "systemd",
        "active": [line.split()[0] for line in active.splitlines() if line.split()][:500],
        "failed": [line.split()[0] for line in failed.splitlines() if line.split()][:200],
    }


def collect_report(log_path: Path = DEFAULT_LOG) -> dict[str, Any]:
    release = os_release()
    up = uptime_seconds()
    now = time.time()
    memory_value = memory()
    try:
        load = list(os.getloadavg())
    except OSError:
        load = []
    manager = package_manager()
    return {
        "basic": {
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn(),
            "addresses": addresses(),
            "mac_address": f"{uuid.getnode():012x}",
            "distribution": release.get("id", platform.system()),
            "distribution_name": release.get("pretty_name", ""),
            "system_version": release.get("version_id", platform.release()),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "uptime_seconds": up,
            "timezone": time.tzname[0] if time.tzname else "",
            "current_time": now,
            "last_boot_at": now - up,
            "agent_version": VERSION,
        },
        "hardware": {
            "manufacturer": dmi_value("sys_vendor"),
            "model": dmi_value("product_name"),
            "serial_number": dmi_value("product_serial"),
            "system_uuid": dmi_value("product_uuid"),
            "cpu": cpu_info(),
            "memory": memory_value,
            "disks": disks(),
            "filesystems": filesystems(),
            "network_interfaces": interfaces(),
        },
        "system": {
            "load_average": load,
            "cpu_percent": cpu_usage_percent(),
            "memory_percent": memory_value["percent"],
            "swap_percent": memory_value["swap_percent"],
            "process_count": max(0, len([name for name in os.listdir("/proc") if name.isdigit()])),
            "logged_in_users": command(["who"], 5).splitlines()[:100],
            "network": network_configuration(),
            "services": service_summary(),
            "agent_log": agent_log_tail(log_path),
        },
        "packages": package_summary(manager),
    }


class AgentClient:
    def __init__(self, config_path: Path, state_path: Path, log_path: Path = DEFAULT_LOG) -> None:
        self.config_path = config_path
        self.state_path = state_path
        self.log_path = log_path
        self.config = read_json(config_path, {})
        self.state = read_json(state_path, {})
        server = self.config.get("server", {})
        agent = self.config.get("agent", {})
        self.server_url = str(server.get("url", "")).rstrip("/")
        self.timeout = int(server.get("timeout_seconds", 15))
        self.verify_tls = bool(server.get("verify_tls", True))
        self.heartbeat_interval = int(agent.get("heartbeat_interval", 30))
        self.report_interval = int(agent.get("report_interval", 300))
        self.max_retries = int(agent.get("max_retries", 10))

    def _request(self, path: str, body: dict[str, Any], token: str) -> dict[str, Any]:
        if not self.server_url.startswith("https://"):
            raise RuntimeError("Hosts Manager server URL must use HTTPS")
        request = Request(
            f"{self.server_url}{path}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": f"hosts-manager-agent/{VERSION}"},
        )
        context = ssl.create_default_context() if self.verify_tls else ssl._create_unverified_context()
        with urlopen(request, timeout=self.timeout, context=context) as response:
            value = json.loads(response.read().decode())
        if not isinstance(value, dict):
            raise RuntimeError("invalid Hosts Manager response")
        return value

    def register(self) -> None:
        token = str(self.config.get("authentication", {}).get("enrollment_token", ""))
        if not token:
            raise RuntimeError("enrollment token is missing")
        installation_id = str(self.state.get("installation_id") or uuid.uuid4())
        report = collect_report(self.log_path)
        basic = report["basic"]
        addresses_value = basic.get("addresses") or []
        if not addresses_value:
            raise RuntimeError("no non-loopback address was detected")
        result = self._request("/api/modules/hosts-manager/enroll", {
            "hostname": basic["hostname"],
            "fqdn": basic["fqdn"],
            "address": addresses_value[0],
            "os": basic["distribution"],
            "architecture": basic["architecture"],
            "python": sys.executable,
            "original_hostname": basic["hostname"],
            "system_id": report["hardware"].get("system_uuid", ""),
            "system_version": basic["system_version"],
            "powershell": "",
            "installation_id": installation_id,
            "agent_version": VERSION,
        }, token)
        credentials = result.get("agent_credentials") or {}
        if not credentials.get("agent_id") or not credentials.get("token"):
            raise RuntimeError("server did not return agent credentials")
        self.state = {
            "installation_id": installation_id,
            "host_id": credentials["host_id"],
            "agent_id": credentials["agent_id"],
            "token": credentials["token"],
            "identity_hash": credentials.get("identity_hash", ""),
            "registered_at": time.time(),
        }
        write_private_json(self.state_path, self.state)
        authentication = dict(self.config.get("authentication", {}))
        authentication.pop("enrollment_token", None)
        self.config["authentication"] = authentication
        write_private_json(self.config_path, self.config)

    def send_heartbeat(self, status: str = "online", error: str = "") -> None:
        response = self._request("/api/modules/hosts-manager/agent/heartbeat", {
            "agent_id": self.state["agent_id"],
            "agent_version": VERSION,
            "uptime_seconds": uptime_seconds(),
            "current_time": time.time(),
            "status": status,
            "error": error,
        }, self.state["token"])
        if response.get("enforce_tls"):
            self.verify_tls = True
        self.apply_update_policy(response)

    def apply_update_policy(self, response: dict[str, Any]) -> None:
        policy = response.get("agent_update")
        if not isinstance(policy, dict) or not policy.get("enabled"):
            return
        expected = str(policy.get("sha256") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            logging.error("agent update policy has no valid SHA-256 checksum")
            return
        current_path = Path(__file__).resolve()
        try:
            if hashlib.sha256(current_path.read_bytes()).hexdigest() == expected:
                return
        except OSError:
            logging.exception("could not read the current agent for update comparison")
            return
        source_url = str(policy.get("url") or f"{self.server_url}/api/modules/hosts-manager/agent/source")
        if not source_url.startswith("https://"):
            logging.error("agent update URL does not use HTTPS")
            return
        request = Request(source_url, method="GET", headers={"User-Agent": f"hosts-manager-agent/{VERSION}"})
        context = ssl.create_default_context() if self.verify_tls else ssl._create_unverified_context()
        maximum = min(2 * 1024 * 1024, max(1024, int(policy.get("max_size") or 2 * 1024 * 1024)))
        with urlopen(request, timeout=self.timeout, context=context) as source:
            content = source.read(maximum + 1)
        if len(content) > maximum or hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError("agent update failed size or checksum verification")
        text = content.decode("utf-8")
        compile(text, str(current_path), "exec")
        temporary = current_path.with_suffix(".update")
        temporary.write_bytes(content)
        os.chmod(temporary, 0o755)
        temporary.replace(current_path)
        logging.info("verified agent update installed; restarting process")
        os.execv(sys.executable, [sys.executable, str(current_path), *sys.argv[1:]])

    def send_report(self) -> None:
        self._request(
            "/api/modules/hosts-manager/agent/report",
            {"agent_id": self.state["agent_id"], **collect_report(self.log_path)},
            self.state["token"],
        )

    def ensure_registered(self) -> None:
        if not self.state.get("agent_id") or not self.state.get("token"):
            self.register()

    def run(self, once: bool = False) -> None:
        self.ensure_registered()
        next_report = 0.0
        failures = 0
        pending_error = ""
        while True:
            try:
                self.send_heartbeat(
                    status="warning" if pending_error else "online",
                    error=pending_error,
                )
                pending_error = ""
                if time.monotonic() >= next_report:
                    self.send_report()
                    next_report = time.monotonic() + self.report_interval
                failures = 0
            except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
                failures += 1
                pending_error = f"{type(error).__name__}: communication attempt failed"
                logging.exception("agent communication failed")
                if once:
                    raise
                if self.max_retries and failures >= self.max_retries:
                    time.sleep(min(300, self.heartbeat_interval * 4))
                    failures = 0
                else:
                    time.sleep(min(60, 2 ** min(failures, 6)))
                continue
            if once:
                return
            time.sleep(self.heartbeat_interval)


def configure_logging(path: Path, level: str = "INFO") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=4)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[handler, logging.StreamHandler()],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Hosts Manager Linux agent")
    parser.add_argument("command", nargs="?", choices=("run", "once", "register", "report", "heartbeat", "version"), default="run")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    if args.command == "version":
        print(VERSION)
        return 0
    runtime_config = read_json(args.config, {})
    logging_config = runtime_config.get("logging", {})
    configured_log = str(logging_config.get("file", ""))
    log_path = Path(configured_log) if args.log == DEFAULT_LOG and configured_log else args.log
    configure_logging(log_path, str(logging_config.get("level", "INFO")))
    client = AgentClient(args.config, args.state, log_path)
    try:
        if args.command == "register":
            client.register()
        elif args.command == "report":
            client.ensure_registered()
            client.send_report()
        elif args.command == "heartbeat":
            client.ensure_registered()
            client.send_heartbeat()
        else:
            client.run(once=args.command == "once")
    except Exception:
        logging.exception("agent stopped with an error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
