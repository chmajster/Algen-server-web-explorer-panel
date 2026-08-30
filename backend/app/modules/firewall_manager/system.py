from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ...privileged_broker.client import BrokerClient
from ...privileged_broker.protocol import Operation
from ...privileged_broker.runtime import broker_required, systemd_action
from .models import FirewallBackend

MAX_OUTPUT = 1024 * 1024
_TOOL = {FirewallBackend.ufw: "ufw", FirewallBackend.firewalld: "firewall-cmd", FirewallBackend.nftables: "nft"}


class FirewallSystem:
    def run(self, backend: FirewallBackend, args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        if backend not in _TOOL:
            return subprocess.CompletedProcess([], 127, "", "firewall backend unavailable")
        if broker_required():
            response = BrokerClient().request(Operation.FIREWALL, {"backend": backend.value, "args": args, "timeout": timeout}, actor="firewall-manager")
            return subprocess.CompletedProcess([_TOOL[backend], *args], response.exit_code, response.stdout[:MAX_OUTPUT], response.stderr[:MAX_OUTPUT])
        executable = shutil.which(_TOOL[backend])
        if not executable:
            return subprocess.CompletedProcess([_TOOL[backend], *args], 127, "", "tool unavailable")
        try:
            result = subprocess.run(  # nosec B603 - executable and argv are selected server-side.
                [executable, *args], capture_output=True, text=True, timeout=timeout, check=False, shell=False,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
        except (OSError, subprocess.SubprocessError) as error:
            return subprocess.CompletedProcess([executable, *args], 1, "", type(error).__name__)
        return subprocess.CompletedProcess(result.args, result.returncode, result.stdout[:MAX_OUTPUT], result.stderr[:MAX_OUTPUT])

    def service(self, unit: str, action: str) -> subprocess.CompletedProcess[str]:
        if action not in {"start", "stop", "restart", "reload", "enable", "disable", "is-active", "is-enabled"}:
            raise ValueError("unsupported service action")
        if broker_required() and action in {"start", "stop", "restart", "reload", "enable", "disable"}:
            return systemd_action(action, unit, actor="firewall-manager")
        executable = shutil.which("systemctl")
        if not executable:
            return subprocess.CompletedProcess(["systemctl", action, unit], 127, "", "systemctl unavailable")
        return subprocess.run([executable, action, unit], capture_output=True, text=True, timeout=15, check=False, shell=False)  # nosec B603

    def detect(self) -> tuple[FirewallBackend, list[FirewallBackend]]:
        available: list[FirewallBackend] = []
        ufw = self.run(FirewallBackend.ufw, ["status"], timeout=5)
        if ufw.returncode in {0, 1} and "Status:" in ufw.stdout:
            available.append(FirewallBackend.ufw)
            if "Status: active" in ufw.stdout:
                return FirewallBackend.ufw, available
        firewalld = self.run(FirewallBackend.firewalld, ["--state"], timeout=5)
        if firewalld.returncode == 0 or "not running" in firewalld.stderr.lower():
            available.append(FirewallBackend.firewalld)
            if firewalld.stdout.strip() == "running":
                return FirewallBackend.firewalld, available
        nft = self.run(FirewallBackend.nftables, ["-j", "list", "ruleset"], timeout=5)
        if nft.returncode == 0:
            available.append(FirewallBackend.nftables)
            try:
                payload: Any = json.loads(nft.stdout or "{}")
            except ValueError:
                payload = {}
            if payload.get("nftables"):
                return FirewallBackend.nftables, available
        if FirewallBackend.ufw in available:
            return FirewallBackend.ufw, available
        if FirewallBackend.firewalld in available:
            return FirewallBackend.firewalld, available
        if FirewallBackend.nftables in available:
            return FirewallBackend.nftables, available
        return FirewallBackend.unavailable, available

    @staticmethod
    def read_text(path: Path, limit: int = 1024 * 1024) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:limit]
        except OSError:
            return ""
