from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...config import get_config
from .models import FirewallBackend, FirewallRule, FirewallRuleInput
from .system import FirewallSystem


class FirewallError(RuntimeError):
    pass


class FirewallSafetyError(FirewallError):
    pass


def parse_ufw_rules(content: str) -> list[FirewallRule]:
    rules: list[FirewallRule] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        match = re.match(r"^\[\s*(\d+)]\s+(.+?)\s+(ALLOW|DENY|REJECT)(?:\s+(IN|OUT))?\s+(.+)$", line, re.IGNORECASE)
        if not match:
            continue
        number, destination_field, action, direction, source_field = match.groups()
        protocol = "any"
        port = ""
        target = re.sub(r"\s+\(v6\)$", "", destination_field.strip(), flags=re.IGNORECASE)
        target_match = re.match(r"^(\d+(?::\d+)?)(?:/(tcp|udp))?(?:\s+on\s+([A-Za-z0-9_.:@-]+))?$", target, re.IGNORECASE)
        interface = ""
        if target_match:
            port = target_match.group(1).replace(":", "-")
            protocol = (target_match.group(2) or "any").lower()
            interface = target_match.group(3) or ""
        source = source_field.split("#", 1)[0].strip() or "any"
        comment = source_field.split("#", 1)[1].strip() if "#" in source_field else ""
        if source.lower() in {"anywhere", "anywhere (v6)"}:
            source = "any"
        family = "ipv6" if "(v6)" in line.lower() else "any"
        rules.append(FirewallRule(
            id=f"ufw:{number}", backend=FirewallBackend.ufw,
            action={"allow": "allow", "deny": "drop", "reject": "reject"}[action.lower()],
            direction=(direction or "IN").lower(), protocol=protocol, port=port,
            source=source, destination="any", interface=interface, comment=comment,
            family=family, raw=raw_line,
        ))
    return rules


def _rich_value(raw: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}="([^"]+)"', raw)
    return match.group(1) if match else ""


def parse_firewalld_rules(content: str) -> list[FirewallRule]:
    rules: list[FirewallRule] = []
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw.startswith("rule "):
            continue
        action = "allow" if re.search(r"\baccept\b", raw) else "reject" if re.search(r"\breject\b", raw) else "drop"
        port = _rich_value(raw, "port")
        protocol = _rich_value(raw, "protocol") or "any"
        source_match = re.search(r'source\s+address="([^"]+)"', raw)
        source = source_match.group(1) if source_match else "any"
        destination_match = re.search(r'destination\s+address="([^"]+)"', raw)
        destination = destination_match.group(1) if destination_match else "any"
        family = _rich_value(raw, "family").replace("ipv", "ipv") or "any"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        rules.append(FirewallRule(id=f"firewalld:{digest}", backend=FirewallBackend.firewalld, action=action, protocol=protocol, port=port, source=source, destination=destination, family=family, raw=raw))
    return rules


def _nft_scalar(value: Any) -> str:
    if isinstance(value, (str, int)):
        return str(value)
    if isinstance(value, dict):
        prefix = value.get("prefix")
        if isinstance(prefix, dict) and isinstance(prefix.get("addr"), str) and isinstance(prefix.get("len"), int):
            return f"{prefix['addr']}/{prefix['len']}"
        range_value = value.get("range")
        if isinstance(range_value, list) and len(range_value) == 2 and all(isinstance(item, int) for item in range_value):
            return f"{range_value[0]}-{range_value[1]}"
    return ""


def parse_nft_rules(content: str) -> list[FirewallRule]:
    try:
        payload = json.loads(content or "{}")
    except ValueError:
        return []
    values = payload.get("nftables", []) if isinstance(payload, dict) else []
    rules: list[FirewallRule] = []
    for entry in values if isinstance(values, list) else []:
        item = entry.get("rule") if isinstance(entry, dict) else None
        if not isinstance(item, dict):
            continue
        family = str(item.get("family") or "")
        table = str(item.get("table") or "")
        chain = str(item.get("chain") or "")
        handle = item.get("handle")
        if not isinstance(handle, int):
            continue
        expressions = item.get("expr", [])
        if not isinstance(expressions, list):
            expressions = []
        raw = json.dumps(expressions, ensure_ascii=False, separators=(",", ":"))
        action = "unknown"
        protocol = "any"
        port = ""
        source = "any"
        destination = "any"
        interface = ""
        lossless = True
        for expression in expressions:
            if not isinstance(expression, dict):
                lossless = False
                continue
            if "accept" in expression:
                action = "allow"
                continue
            if "drop" in expression:
                action = "drop"
                continue
            if "reject" in expression:
                action = "reject"
                continue
            if "counter" in expression:
                continue
            match = expression.get("match")
            if not isinstance(match, dict) or match.get("op", "==") != "==":
                lossless = False
                continue
            left = match.get("left")
            right = _nft_scalar(match.get("right"))
            if not isinstance(left, dict) or not right:
                lossless = False
                continue
            meta = left.get("meta")
            if isinstance(meta, dict):
                key = str(meta.get("key") or "")
                if key in {"iifname", "oifname"}:
                    interface = right
                    continue
                if key == "l4proto" and right in {"tcp", "udp"}:
                    protocol = right
                    continue
                lossless = False
                continue
            payload_left = left.get("payload")
            if isinstance(payload_left, dict):
                nft_protocol = str(payload_left.get("protocol") or "")
                field = str(payload_left.get("field") or "")
                if nft_protocol in {"ip", "ip6"} and field == "saddr":
                    source = right
                    continue
                if nft_protocol in {"ip", "ip6"} and field == "daddr":
                    destination = right
                    continue
                if nft_protocol in {"tcp", "udp"} and field == "dport":
                    protocol = nft_protocol
                    port = right.replace(":", "-")
                    continue
            lossless = False
        editable = (
            family == "inet"
            and table == "webnas"
            and chain in {"input", "output"}
            and action in {"allow", "drop", "reject"}
            and lossless
        )
        rules.append(FirewallRule(
            id=f"nft:{family}:{table}:{chain}:{handle}", backend=FirewallBackend.nftables,
            action=action, direction="out" if chain.lower().startswith("out") else "in",
            protocol=protocol, port=port, source=source, destination=destination,
            interface=interface,
            family="ipv4" if family == "ip" else "ipv6" if family == "ip6" else "any",
            comment=str(item.get("comment") or "")[:120], editable=editable, raw=raw,
        ))
    return rules


class FirewallService:
    def __init__(self, *, system: FirewallSystem | None = None, root: Path | None = None) -> None:
        self.system = system or FirewallSystem()
        self.root = root or Path(get_config().paths.data_dir) / "firewall-manager"
        self.backups_root = self.root / "backups"
        self.backups_root.mkdir(parents=True, exist_ok=True)
        self._transaction_lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._transaction_lock:
            yield

    def status(self) -> dict[str, Any]:
        backend, available = self.system.detect()
        active = False
        detail = ""
        if backend == FirewallBackend.ufw:
            result = self.system.run(backend, ["status", "verbose"])
            active = "Status: active" in result.stdout
            detail = result.stdout[:16_384]
        elif backend == FirewallBackend.firewalld:
            result = self.system.run(backend, ["--state"])
            active = result.returncode == 0 and result.stdout.strip() == "running"
            detail = result.stdout.strip() or result.stderr.strip()
        elif backend == FirewallBackend.nftables:
            result = self.system.run(backend, ["-j", "list", "ruleset"])
            active = result.returncode == 0 and bool(parse_nft_rules(result.stdout))
            detail = "nftables ruleset available" if result.returncode == 0 else result.stderr.strip()
        return {"backend": backend.value, "available_backends": [item.value for item in available], "active": active, "detail": detail, "rules": len(self.rules(backend=backend)) if backend != FirewallBackend.unavailable else 0}

    def rules(self, *, backend: FirewallBackend | None = None) -> list[FirewallRule]:
        selected = backend or self.system.detect()[0]
        if selected == FirewallBackend.ufw:
            result = self.system.run(selected, ["status", "numbered"])
            return parse_ufw_rules(result.stdout)
        if selected == FirewallBackend.firewalld:
            result = self.system.run(selected, ["--zone=public", "--list-rich-rules"])
            return parse_firewalld_rules(result.stdout)
        if selected == FirewallBackend.nftables:
            result = self.system.run(selected, ["-j", "list", "ruleset"])
            return parse_nft_rules(result.stdout)
        return []

    def listening_ports(self) -> list[dict[str, Any]]:
        executable = shutil.which("ss")
        if not executable:
            return []
        import subprocess
        try:
            result = subprocess.run([executable, "-H", "-lntup"], capture_output=True, text=True, timeout=8, check=False, shell=False)  # nosec B603
        except (OSError, subprocess.SubprocessError):
            return []
        rows: list[dict[str, Any]] = []
        for line in result.stdout.splitlines()[:1000]:
            parts = line.split(None, 6)
            if len(parts) < 6:
                continue
            proto, state, _recv, _send, local, peer = parts[:6]
            process = parts[6] if len(parts) > 6 else ""
            host, _, raw_port = local.rpartition(":")
            if not raw_port.isdigit():
                continue
            rows.append({"protocol": proto, "state": state, "address": host.strip("[]") or "*", "port": int(raw_port), "peer": peer, "process": process[:300], "firewall_rule": self._matching_port_rule(int(raw_port), proto)})
        return rows

    def _matching_port_rule(self, port: int, protocol: str) -> str | None:
        for rule in self.rules():
            if rule.protocol not in {"any", protocol.replace("6", "").replace("4", "")}:
                continue
            if not rule.port:
                continue
            start, _, end = rule.port.partition("-")
            try:
                if int(start) <= port <= int(end or start):
                    return rule.id
            except ValueError:
                continue
        return None

    @staticmethod
    def _port_for_backend(value: str, backend: FirewallBackend) -> str:
        return value.replace("-", ":") if backend == FirewallBackend.ufw else value

    def _ufw_args(self, rule: FirewallRuleInput) -> list[str]:
        args = [{"allow": "allow", "drop": "deny", "reject": "reject"}[rule.action], rule.direction]
        if rule.interface:
            args += ["on", rule.interface]
        if rule.protocol != "any":
            args += ["proto", rule.protocol]
        args += ["from", "any" if rule.source == "any" else rule.source, "to", "any" if rule.destination == "any" else rule.destination]
        if rule.port:
            args += ["port", self._port_for_backend(rule.port, FirewallBackend.ufw)]
        if rule.comment:
            args += ["comment", rule.comment]
        return args

    def _firewalld_rich(self, rule: FirewallRuleInput) -> str:
        address_families: set[str] = set()
        for value in (rule.source, rule.destination):
            if value == "any":
                continue
            version = ipaddress.ip_network(value, strict=False).version
            address_families.add("ipv6" if version == 6 else "ipv4")
        if len(address_families) > 1:
            raise FirewallError("firewalld rule cannot mix IPv4 and IPv6 addresses")
        inferred = next(iter(address_families), "")
        if rule.family != "any" and inferred and rule.family != inferred:
            raise FirewallError("firewalld rule family does not match its addresses")
        effective_family = rule.family if rule.family != "any" else inferred
        parts = ["rule"]
        if effective_family:
            parts[0] += f' family="{effective_family}"'
        if rule.source != "any":
            parts.append(f'source address="{rule.source}"')
        if rule.destination != "any":
            parts.append(f'destination address="{rule.destination}"')
        if rule.port:
            parts.append(f'port port="{rule.port}" protocol="{rule.protocol}"')
        parts.append({"allow": "accept", "drop": "drop", "reject": "reject"}[rule.action])
        return " ".join(parts)

    def _ensure_nft(self) -> None:
        checks = [
            ["add", "table", "inet", "webnas"],
            ["add", "chain", "inet", "webnas", "input", "{", "type", "filter", "hook", "input", "priority", "0", ";", "policy", "accept", ";", "}"],
            ["add", "chain", "inet", "webnas", "output", "{", "type", "filter", "hook", "output", "priority", "0", ";", "policy", "accept", ";", "}"],
        ]
        for args in checks:
            self.system.run(FirewallBackend.nftables, args)

    def _nft_args(self, rule: FirewallRuleInput) -> list[str]:
        chain = "input" if rule.direction == "in" else "output"
        args = ["add", "rule", "inet", "webnas", chain]
        if rule.interface:
            args += ["iifname" if rule.direction == "in" else "oifname", rule.interface]
        if rule.source != "any":
            args += ["ip6" if ":" in rule.source else "ip", "saddr", rule.source]
        if rule.destination != "any":
            args += ["ip6" if ":" in rule.destination else "ip", "daddr", rule.destination]
        if rule.protocol != "any":
            args += [rule.protocol]
            if rule.port:
                args += ["dport", rule.port.replace("-", "-")]
        args += [{"allow": "accept", "drop": "drop", "reject": "reject"}[rule.action]]
        if rule.comment:
            args += ["comment", rule.comment]
        return args

    def add_rule(self, rule: FirewallRuleInput) -> dict[str, Any]:
        backend = self.system.detect()[0]
        if backend == FirewallBackend.ufw:
            result = self.system.run(backend, self._ufw_args(rule))
        elif backend == FirewallBackend.firewalld:
            if rule.interface:
                raise FirewallError("firewalld interface-specific rules are not supported; assign the interface to a zone first")
            rich = self._firewalld_rich(rule)
            result = self.system.run(backend, ["--permanent", "--zone=public", f"--add-rich-rule={rich}"])
            if result.returncode == 0:
                self.system.run(backend, ["--reload"])
        elif backend == FirewallBackend.nftables:
            self._ensure_nft()
            result = self.system.run(backend, self._nft_args(rule))
        else:
            raise FirewallError("no supported firewall backend is available")
        if result.returncode != 0:
            raise FirewallError(result.stderr.strip() or result.stdout.strip() or "firewall command failed")
        return {"backend": backend.value, "rule": rule.model_dump(mode="json")}

    def _find(self, rule_id: str) -> FirewallRule:
        item = next((item for item in self.rules() if item.id == rule_id), None)
        if not item:
            raise FirewallError("firewall rule was not found")
        return item

    def delete_rule(self, rule_id: str) -> dict[str, Any]:
        rule = self._find(rule_id)
        if rule.backend == FirewallBackend.ufw:
            number = rule.id.split(":", 1)[1]
            result = self.system.run(rule.backend, ["--force", "delete", number])
        elif rule.backend == FirewallBackend.firewalld:
            result = self.system.run(rule.backend, ["--permanent", "--zone=public", f"--remove-rich-rule={rule.raw}"])
            if result.returncode == 0:
                self.system.run(rule.backend, ["--reload"])
        elif rule.backend == FirewallBackend.nftables:
            if not rule.editable:
                raise FirewallError("only rules in the WebNAS nftables table can be modified")
            _, family, table, chain, handle = rule.id.split(":", 4)
            result = self.system.run(rule.backend, ["delete", "rule", family, table, chain, "handle", handle])
        else:
            raise FirewallError("unsupported firewall backend")
        if result.returncode != 0:
            raise FirewallError(result.stderr.strip() or result.stdout.strip() or "could not remove firewall rule")
        return {"deleted": rule_id}

    @staticmethod
    def _input_from_rule(rule: FirewallRule) -> FirewallRuleInput:
        return FirewallRuleInput.model_validate(
            {
                "action": rule.action if rule.action in {"allow", "drop", "reject"} else "drop",
                "direction": rule.direction if rule.direction in {"in", "out"} else "in",
                "protocol": rule.protocol if rule.protocol in {"any", "tcp", "udp"} else "any",
                "port": rule.port,
                "source": rule.source,
                "destination": rule.destination,
                "interface": rule.interface,
                "comment": rule.comment,
                "family": rule.family if rule.family in {"any", "ipv4", "ipv6"} else "any",
            }
        )

    def edit_rule(self, rule_id: str, replacement: FirewallRuleInput) -> dict[str, Any]:
        previous = self._find(rule_id)
        self.delete_rule(rule_id)
        try:
            return self.add_rule(replacement)
        except Exception:
            previous_input = self._input_from_rule(previous)
            self.add_rule(previous_input)
            raise

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        backend = self.system.detect()[0]
        if backend == FirewallBackend.ufw:
            result = self.system.run(backend, ["--force", "enable"] if enabled else ["disable"])
        elif backend == FirewallBackend.firewalld:
            result = self.system.service("firewalld.service", "start" if enabled else "stop")
        elif backend == FirewallBackend.nftables:
            result = self.system.service("nftables.service", "start" if enabled else "stop")
        else:
            raise FirewallError("no supported firewall backend is available")
        if result.returncode != 0:
            raise FirewallError(result.stderr.strip() or result.stdout.strip() or "firewall state change failed")
        return self.status()

    def reload(self) -> dict[str, Any]:
        backend = self.system.detect()[0]
        if backend == FirewallBackend.ufw:
            result = self.system.run(backend, ["reload"])
        elif backend == FirewallBackend.firewalld:
            result = self.system.run(backend, ["--reload"])
        elif backend == FirewallBackend.nftables:
            result = self.system.service("nftables.service", "reload")
        else:
            raise FirewallError("no supported firewall backend is available")
        if result.returncode != 0:
            raise FirewallError(result.stderr.strip() or result.stdout.strip() or "firewall reload failed")
        return self.status()

    @staticmethod
    def _rule_hits_port(rule: FirewallRule | FirewallRuleInput, port: int) -> bool:
        if not rule.port:
            return True
        start, _, end = rule.port.partition("-")
        try:
            return int(start) <= port <= int(end or start)
        except ValueError:
            return False

    def lockout_warnings(self, *, operation: str, rule_id: str = "", rule: FirewallRuleInput | None = None, client_ip: str = "", webnas_port: int = 0) -> list[str]:
        warnings: list[str] = []
        target: FirewallRule | FirewallRuleInput | None = rule
        if rule_id:
            try:
                target = self._find(rule_id)
            except FirewallError:
                target = None
        if operation in {"disable", "enable", "restore", "import"}:
            warnings.append("Changing the global firewall state can interrupt administrative access")
        if target is not None:
            if self._rule_hits_port(target, 22):
                warnings.append("The change affects SSH access")
            if webnas_port and self._rule_hits_port(target, webnas_port):
                warnings.append("The change affects the current WebNAS port")
            if client_ip and target.source != "any":
                try:
                    if ipaddress.ip_address(client_ip) in ipaddress.ip_network(target.source, strict=False):
                        warnings.append("The change affects the current administrator IP address")
                except ValueError:
                    pass
            if getattr(target, "action", "") in {"drop", "reject"}:
                warnings.append("The rule blocks traffic")
        return list(dict.fromkeys(warnings))

    def plan(self, operation: str, *, rule_id: str = "", rule: FirewallRuleInput | None = None, client_ip: str = "", webnas_port: int = 0) -> dict[str, Any]:
        warnings = self.lockout_warnings(operation=operation, rule_id=rule_id, rule=rule, client_ip=client_ip, webnas_port=webnas_port)
        return {"operation": operation, "backend": self.system.detect()[0].value, "rule_id": rule_id, "candidate": rule.model_dump(mode="json") if rule else None, "warnings": warnings, "high_risk": bool(warnings), "steps": ["validate", "plan/diff", "backup", "apply", "verify", "rollback on failure"]}

    def export_configuration(self) -> dict[str, Any]:
        status = self.status()
        rules = self.rules()
        if status["backend"] == FirewallBackend.nftables.value:
            rules = [item for item in rules if item.editable]
        return {"schema": 1, "created_at": time.time(), "backend": status["backend"], "active": status["active"], "rules": [item.model_dump(mode="json", exclude={"raw", "id", "backend", "editable", "enabled"}) for item in rules]}

    def import_configuration(self, configuration: dict[str, Any]) -> dict[str, Any]:
        if set(configuration) - {"schema", "created_at", "backend", "active", "rules", "id", "description"}:
            raise FirewallError("firewall import contains unsupported fields")
        if configuration.get("schema") != 1 or not isinstance(configuration.get("rules"), list):
            raise FirewallError("firewall import schema is invalid")
        raw_rules = configuration["rules"]
        if len(raw_rules) > 2000:
            raise FirewallError("firewall import exceeds the 2000-rule limit")
        try:
            candidate = [FirewallRuleInput.model_validate(raw_rule) for raw_rule in raw_rules]
        except ValueError as error:
            raise FirewallError("firewall import contains an invalid rule") from error
        active = configuration.get("active")
        if active is not None and not isinstance(active, bool):
            raise FirewallError("firewall import active state must be boolean")
        backend = self.system.detect()[0]
        current = self.rules(backend=backend)
        removable = [item for item in current if backend != FirewallBackend.nftables or item.editable]
        for item in reversed(removable):
            self.delete_rule(item.id)
        for candidate_rule in candidate:
            self.add_rule(candidate_rule)
        if active is not None and bool(self.status().get("active")) != active:
            self.set_enabled(active)
        return {"backend": backend.value, "imported_rules": len(candidate), "active": self.status().get("active")}

    def create_backup(self, description: str = "") -> dict[str, Any]:
        identifier = f"fw-{int(time.time() * 1000)}"
        payload = {**self.export_configuration(), "id": identifier, "description": description[:200]}
        path = self.backups_root / f"{identifier}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        path.chmod(0o600)
        return {"id": identifier, "description": payload["description"], "created_at": payload["created_at"], "backend": payload["backend"], "rules": len(payload["rules"])}

    def list_backups(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.backups_root.glob("fw-*.json"), reverse=True)[:200]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            items.append({"id": str(payload.get("id") or path.stem), "description": str(payload.get("description") or ""), "created_at": float(payload.get("created_at") or 0), "backend": str(payload.get("backend") or ""), "rules": len(payload.get("rules") or [])})
        return items

    def _load_backup(self, backup_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"fw-\d{10,16}", backup_id):
            raise FirewallError("invalid backup id")
        path = self.backups_root / f"{backup_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise FirewallError("firewall backup is unavailable") from error
        if payload.get("schema") != 1 or not isinstance(payload.get("rules"), list):
            raise FirewallError("firewall backup is invalid")
        return payload

    def restore_backup(self, backup_id: str) -> dict[str, Any]:
        payload = self._load_backup(backup_id)
        try:
            candidate = [FirewallRuleInput.model_validate(raw) for raw in payload["rules"][:2000]]
        except ValueError as error:
            raise FirewallError("firewall backup contains an invalid rule") from error
        current = self.rules()
        backend = self.system.detect()[0]
        removable = [item for item in current if backend != FirewallBackend.nftables or item.editable]
        for item in reversed(removable):
            self.delete_rule(item.id)
        restored = 0
        try:
            for rule in candidate:
                self.add_rule(rule)
                restored += 1
            if bool(payload.get("active")) != bool(self.status().get("active")):
                self.set_enabled(bool(payload.get("active")))
        except Exception as error:
            rollback_failed = False
            for item in current:
                if backend == FirewallBackend.nftables and not item.editable:
                    continue
                try:
                    self.add_rule(self._input_from_rule(item))
                except Exception:
                    rollback_failed = True
            if rollback_failed:
                raise FirewallError("firewall backup restore failed and rollback could not be completed") from error
            raise
        return {"backup_id": backup_id, "restored_rules": restored, "backend": backend.value}

    def activity(self) -> list[dict[str, Any]]:
        from ...activity import repository
        items, _ = repository().list(category=ActivityCategory.module, search="firewall", page_size=100)
        return [item.model_dump(mode="json") for item in items]

    @staticmethod
    def record(actor: str, action: str, *, status: ActivityStatus = ActivityStatus.success, summary: str = "", details: dict[str, Any] | None = None) -> None:
        record_activity(ActivityCategory.module, action, actor, target="firewall-manager", status=status, summary=summary, details=details or {}, source="firewall-manager")


@lru_cache
def service() -> FirewallService:
    return FirewallService()
