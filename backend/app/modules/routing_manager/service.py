from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...config import get_config
from ...jobs.models import JobPriority
from ...jobs.service import JobContext, service as jobs
from ...privileged_broker.client import BrokerClient
from ...privileged_broker.protocol import Operation
from ...privileged_broker.runtime import broker_required
from .models import PolicyRuleInput, RouteInput


class RoutingUnavailable(RuntimeError):
    pass


def _valid_transaction_id(value: str) -> bool:
    return len(value) == 32 and all(char in "0123456789abcdef" for char in value)


class RoutingService:
    def __init__(self) -> None:
        self.transactions_dir = Path(get_config().paths.data_dir) / "routing-transactions"
        self.transactions_dir.mkdir(parents=True, exist_ok=True)
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()
        self.reconcile_transactions()

    @staticmethod
    def _run(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, shell=False)

    @staticmethod
    def _ip() -> str:
        binary = shutil.which("ip")
        if not binary:
            raise RoutingUnavailable("iproute2 is not installed")
        return binary

    def _mutate_ip(self, command: list[str], *, actor: str) -> subprocess.CompletedProcess[str]:
        if broker_required():
            response = BrokerClient().request(Operation.ROUTING, {"action": "ip", "args": command[1:]}, actor=actor)
            return subprocess.CompletedProcess(command, response.exit_code, response.stdout, response.stderr)
        return self._run(command, timeout=30)

    def _nmcli_mutate(self, action: str, connection: str, family: str, routes: str, *, actor: str) -> subprocess.CompletedProcess[str]:
        binary = shutil.which("nmcli")
        if not binary:
            raise RoutingUnavailable("nmcli is unavailable")
        broker_action = {"add": "nmcli_add_route", "remove": "nmcli_remove_route", "set": "nmcli_set_routes"}[action]
        if broker_required():
            response = BrokerClient().request(
                Operation.ROUTING,
                {"action": broker_action, "connection": connection, "family": family, "routes": routes},
                actor=actor,
            )
            return subprocess.CompletedProcess([binary, broker_action, connection], response.exit_code, response.stdout, response.stderr)
        property_name = f"{family}.routes"
        if action == "add": property_name = f"+{property_name}"
        elif action == "remove": property_name = f"-{property_name}"
        return self._run([binary, "connection", "modify", connection, property_name, routes], timeout=30)

    def backend(self) -> dict[str, Any]:
        systemctl = shutil.which("systemctl")
        def active(unit: str) -> bool:
            return bool(systemctl and self._run([systemctl, "is-active", "--quiet", unit], timeout=6).returncode == 0)
        if shutil.which("nmcli") and active("NetworkManager"):
            return {"name": "NetworkManager", "persistent_routes": True, "policy_routing": True}
        if active("systemd-networkd"):
            return {"name": "systemd-networkd", "persistent_routes": False, "policy_routing": True}
        if shutil.which("netplan"):
            return {"name": "netplan", "persistent_routes": False, "policy_routing": True}
        return {"name": "runtime-iproute2", "persistent_routes": False, "policy_routing": True}

    def routes(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        ip = self._ip()
        for family, flag in ((4, "-4"), (6, "-6")):
            result = self._run([ip, flag, "-j", "route", "show", "table", "all"], timeout=15)
            if result.returncode != 0:
                continue
            try:
                rows = json.loads(result.stdout)
            except json.JSONDecodeError:
                rows = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                items.append({
                    "family": family, "destination": row.get("dst", "default"), "gateway": row.get("gateway", ""),
                    "interface": row.get("dev", ""), "metric": row.get("metric"), "protocol": row.get("protocol", ""),
                    "scope": row.get("scope", ""), "source": row.get("prefsrc", row.get("src", "")),
                    "table": row.get("table", "main"), "type": row.get("type", "unicast"), "flags": row.get("flags", []),
                })
        return items

    def rules(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        ip = self._ip()
        for family, flag in ((4, "-4"), (6, "-6")):
            result = self._run([ip, flag, "-j", "rule", "show"], timeout=10)
            if result.returncode != 0:
                continue
            try:
                rows = json.loads(result.stdout)
            except json.JSONDecodeError:
                rows = []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    items.append({"family": family, **row})
        return items

    def tables(self) -> list[dict[str, Any]]:
        names = {"255": "local", "254": "main", "253": "default", "0": "unspec"}
        path = Path("/etc/iproute2/rt_tables")
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("#", 1)[0].strip().split()
                if len(parts) == 2 and parts[0].isdigit():
                    names[parts[0]] = parts[1]
        route_counts: dict[str, int] = {}
        rule_counts: dict[str, int] = {}
        for route in self.routes():
            key = str(route.get("table", "main")); route_counts[key] = route_counts.get(key, 0) + 1
        for rule in self.rules():
            key = str(rule.get("table", rule.get("lookup", "main"))); rule_counts[key] = rule_counts.get(key, 0) + 1
        return [
            {"id": int(table_id), "name": name, "routes": route_counts.get(name, route_counts.get(table_id, 0)), "rules": rule_counts.get(name, rule_counts.get(table_id, 0))}
            for table_id, name in sorted(names.items(), key=lambda item: int(item[0]))
        ]

    @staticmethod
    def _family(payload: RouteInput) -> int:
        if payload.destination != "default": return ipaddress.ip_network(payload.destination).version
        if payload.gateway: return ipaddress.ip_address(payload.gateway).version
        if payload.source: return ipaddress.ip_address(payload.source).version
        return 4

    def _route_args(self, action: str, payload: RouteInput) -> list[str]:
        args = [self._ip(), "-4" if self._family(payload) == 4 else "-6", "route", action, payload.destination]
        if payload.gateway: args += ["via", payload.gateway]
        if payload.interface: args += ["dev", payload.interface]
        if payload.source: args += ["src", payload.source]
        if payload.metric is not None: args += ["metric", str(payload.metric)]
        if payload.table != "main": args += ["table", payload.table]
        return args

    def _current_route_raw(self, payload: RouteInput) -> str:
        args = [self._ip(), "-4" if self._family(payload) == 4 else "-6", "route", "show", payload.destination]
        if payload.table != "main": args += ["table", payload.table]
        result = self._run(args, timeout=10)
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""

    def _warnings(self, payload: RouteInput) -> list[str]:
        warnings: list[str] = []
        existing = self.routes()
        if payload.destination == "default":
            warnings.append("Changing the default route can disconnect WebNAS")
            defaults = [route for route in existing if route["family"] == self._family(payload) and route["destination"] == "default"]
            if defaults:
                warnings.append(f"{len(defaults)} existing default route(s) detected")
        elif payload.destination != "default":
            candidate = ipaddress.ip_network(payload.destination)
            overlaps = []
            for route in existing:
                destination = route.get("destination")
                if route.get("family") != candidate.version or not destination or destination == "default": continue
                try:
                    current = ipaddress.ip_network(str(destination), strict=False)
                except ValueError:
                    continue
                if current.overlaps(candidate) and str(current) != str(candidate): overlaps.append(str(current))
            if overlaps: warnings.append(f"Overlapping routes detected: {', '.join(overlaps[:5])}")
        if payload.persistent and not self.backend()["persistent_routes"]:
            warnings.append(f"Persistent routes are not supported by detected backend {self.backend()['name']}")
        if payload.gateway and payload.interface:
            lookup = self._run([self._ip(), "route", "get", payload.gateway, "oif", payload.interface], timeout=8)
            if lookup.returncode != 0: warnings.append("Gateway is not currently reachable through the selected interface")
        return warnings

    def preview(self, action: str, payload: RouteInput) -> dict[str, Any]:
        if action not in {"replace", "delete"}: raise ValueError("route action must be replace or delete")
        before = self._current_route_raw(payload); command = self._route_args(action, payload)
        if action == "replace":
            inverse = [self._ip(), "-4" if self._family(payload) == 4 else "-6", "route", "replace", *shlex.split(before)] if before else self._route_args("delete", payload)
        else:
            if not before: raise ValueError("route does not exist")
            inverse = [self._ip(), "-4" if self._family(payload) == 4 else "-6", "route", "replace", *shlex.split(before)]
        return {"action": action, "before": before, "after": " ".join(command[3:]), "command": command, "inverse": inverse,
                "requires_confirmation": True, "rollback_seconds": payload.rollback_seconds, "backend": self.backend(), "warnings": self._warnings(payload)}

    def diagnostics(self, target: str) -> dict[str, Any]:
        try: address = str(ipaddress.ip_address(target))
        except ValueError as error: raise ValueError("diagnostic target must be an IP address") from error
        flag = "-6" if ":" in address else "-4"; ip = self._ip()
        lookup = self._run([ip, flag, "route", "get", address], timeout=10)
        ping_binary = shutil.which("ping6" if flag == "-6" else "ping") or shutil.which("ping")
        ping = self._run([ping_binary, "-c", "1", "-W", "2", address], timeout=5) if ping_binary else None
        traceroute_binary = shutil.which("traceroute")
        trace = self._run([traceroute_binary, "-n", "-m", "8", "-w", "1", address], timeout=15) if traceroute_binary else None
        return {"target": address, "route_ok": lookup.returncode == 0, "route": lookup.stdout.strip()[:2000],
                "ping_available": bool(ping_binary), "ping_ok": bool(ping and ping.returncode == 0), "ping": (ping.stdout if ping else "")[:2000],
                "traceroute_available": bool(traceroute_binary), "traceroute": (trace.stdout if trace else "")[:5000]}

    def _persistent_networkmanager(self, action: str, payload: RouteInput, *, actor: str) -> dict[str, Any]:
        if not payload.persistent: return {"persistent": False}
        backend = self.backend()
        if backend["name"] != "NetworkManager": raise RoutingUnavailable(f"Persistent routes are unsupported for {backend['name']}")
        if not payload.interface: raise ValueError("persistent NetworkManager route requires an interface")
        nmcli = shutil.which("nmcli")
        if not nmcli: raise RoutingUnavailable("nmcli is unavailable")
        connection = self._run([nmcli, "-g", "GENERAL.CONNECTION", "device", "show", payload.interface], timeout=10).stdout.strip()
        if not connection or connection == "--": raise RoutingUnavailable("No active NetworkManager connection for interface")
        family = "ipv4" if self._family(payload) == 4 else "ipv6"
        snapshot = self._run([nmcli, "-g", f"{family}.routes", "connection", "show", connection], timeout=10)
        if snapshot.returncode != 0: raise RuntimeError((snapshot.stderr or "Unable to snapshot NetworkManager routes")[:500])
        spec = payload.destination
        if payload.gateway: spec += f" {payload.gateway}"
        if payload.metric is not None: spec += f" {payload.metric}"
        mutation = self._nmcli_mutate("add" if action == "replace" else "remove", connection, family, spec, actor=actor)
        if mutation.returncode != 0: raise RuntimeError((mutation.stderr or mutation.stdout or "nmcli route update failed")[:500])
        return {"persistent": True, "backend": "NetworkManager", "connection": connection, "family": family, "route": spec, "snapshot": snapshot.stdout.rstrip("\n")}

    def _restore_persistent(self, persistent: dict[str, Any], *, actor: str) -> None:
        if not persistent.get("persistent"): return
        result = self._nmcli_mutate("set", str(persistent["connection"]), str(persistent["family"]), str(persistent.get("snapshot") or ""), actor=actor)
        if result.returncode != 0: raise RuntimeError((result.stderr or result.stdout or "persistent route rollback failed")[:500])

    def _transaction_path(self, transaction_id: str) -> Path:
        return self.transactions_dir / f"{transaction_id}.json"

    def _write_transaction(self, data: dict[str, Any]) -> None:
        path = self._transaction_path(data["id"]); temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8"); os.replace(temp, path); path.chmod(0o600)

    def _read_transaction(self, transaction_id: str) -> dict[str, Any]:
        if not _valid_transaction_id(transaction_id): raise ValueError("invalid transaction id")
        path = self._transaction_path(transaction_id)
        if not path.exists(): raise LookupError("transaction not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def apply_job(self, context: JobContext, metadata: dict[str, Any]) -> dict[str, Any]:
        action = str(metadata["action"]); payload = RouteInput.model_validate(metadata["payload"]); actor = str(metadata.get("actor") or "webnas")
        plan = self.preview(action, payload); transaction_id = uuid4().hex
        context.set_progress(15, "Snapshot captured", current_step="snapshot")
        result = self._mutate_ip(plan["command"], actor=actor)
        if result.returncode != 0: raise RuntimeError((result.stderr or result.stdout or "route operation failed")[:500])
        persistent: dict[str, Any] = {"persistent": False}
        try:
            persistent = self._persistent_networkmanager(action, payload, actor=actor)
            context.set_progress(55, "Route applied", current_step="verify")
            probe = payload.gateway or ("2606:4700:4700::1111" if self._family(payload) == 6 else "1.1.1.1")
            verify = self._run([self._ip(), "-6" if self._family(payload) == 6 else "-4", "route", "get", probe], timeout=10)
            if verify.returncode != 0: raise RuntimeError("route verification failed")
        except Exception:
            self._mutate_ip(plan["inverse"], actor=actor)
            try: self._restore_persistent(persistent, actor=actor)
            except Exception: pass
            raise
        expires_at = time.time() + payload.rollback_seconds
        transaction = {"id": transaction_id, "actor": actor, "action": action, "created_at": time.time(), "expires_at": expires_at,
            "status": "pending_confirmation", "command": plan["command"], "inverse": plan["inverse"], "payload": payload.model_dump(mode="json"),
            "persistent": persistent, "verification": verify.stdout.strip()[:2000]}
        self._write_transaction(transaction); self._schedule_rollback(transaction)
        context.set_progress(100, "Route applied; confirmation required", current_step="confirm")
        return {"transaction_id": transaction_id, "expires_at": expires_at, "status": transaction["status"], "verification": transaction["verification"], **persistent}

    def enqueue(self, action: str, payload: RouteInput, actor: str):
        self.preview(action, payload)
        return jobs().submit_callable(job_type=f"routing.{action}", module="routing-manager", created_by=actor, handler=self.apply_job,
            metadata={"action": action, "payload": payload.model_dump(mode="json"), "actor": actor}, retryable=False, cancellable=False,
            priority=JobPriority.critical if payload.destination == "default" else JobPriority.high, timeout=120, name=f"Routing {action}", total_steps=3)

    def _schedule_rollback(self, transaction: dict[str, Any]) -> None:
        delay = max(0.0, float(transaction["expires_at"]) - time.time())
        timer = threading.Timer(delay, lambda: self.rollback(str(transaction["id"]), automatic=True)); timer.daemon = True
        with self._lock:
            old = self._timers.pop(str(transaction["id"]), None)
            if old: old.cancel()
            self._timers[str(transaction["id"])] = timer
        timer.start()

    def confirm(self, transaction_id: str) -> dict[str, Any]:
        transaction = self._read_transaction(transaction_id)
        if transaction["status"] != "pending_confirmation": raise ValueError("transaction is not waiting for confirmation")
        transaction["status"] = "confirmed"; transaction["confirmed_at"] = time.time(); self._write_transaction(transaction)
        with self._lock: timer = self._timers.pop(transaction_id, None)
        if timer: timer.cancel()
        return transaction

    def rollback(self, transaction_id: str, *, automatic: bool = False) -> dict[str, Any]:
        transaction = self._read_transaction(transaction_id)
        if transaction["status"] not in {"pending_confirmation", "rollback_failed"}: return transaction
        actor = str(transaction.get("actor") or "webnas")
        errors: list[str] = []
        runtime_result = self._mutate_ip(list(transaction["inverse"]), actor=actor)
        if runtime_result.returncode != 0: errors.append((runtime_result.stderr or runtime_result.stdout or "runtime rollback failed")[:500])
        try: self._restore_persistent(dict(transaction.get("persistent") or {}), actor=actor)
        except Exception as error: errors.append(str(error)[:500])
        transaction["status"] = "rolled_back" if not errors else "rollback_failed"; transaction["rolled_back_at"] = time.time(); transaction["automatic"] = automatic; transaction["rollback_error"] = "; ".join(errors)
        self._write_transaction(transaction)
        return transaction

    def transaction(self, transaction_id: str) -> dict[str, Any]: return self._read_transaction(transaction_id)

    def reconcile_transactions(self) -> None:
        for path in self.transactions_dir.glob("*.json"):
            try: transaction = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): continue
            if transaction.get("status") != "pending_confirmation": continue
            if float(transaction.get("expires_at") or 0) <= time.time():
                try: self.rollback(str(transaction["id"]), automatic=True)
                except Exception: pass
            else: self._schedule_rollback(transaction)

    def policy_rule(self, action: str, payload: PolicyRuleInput, *, actor: str) -> dict[str, Any]:
        if action not in {"add", "delete"}: raise ValueError("rule action must be add or delete")
        args = [self._ip(), "-4" if payload.family == 4 else "-6", "rule", action]
        if payload.priority is not None: args += ["priority", str(payload.priority)]
        if payload.source != "all": args += ["from", payload.source]
        if payload.destination != "all": args += ["to", payload.destination]
        if payload.fwmark: args += ["fwmark", payload.fwmark]
        if payload.input_interface: args += ["iif", payload.input_interface]
        if payload.output_interface: args += ["oif", payload.output_interface]
        args += ["table", payload.table]
        result = self._mutate_ip(args, actor=actor)
        if result.returncode != 0: raise RuntimeError((result.stderr or result.stdout or "policy rule operation failed")[:500])
        return {"ok": True, "action": action}


_instance: RoutingService | None = None


def service() -> RoutingService:
    global _instance
    if _instance is None: _instance = RoutingService()
    return _instance
