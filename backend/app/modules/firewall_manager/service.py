from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import time
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
        target = destination_field.strip()
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
        source = _rich_value(raw, "address") or "any"
        destination_match = re.search(r'destination\s+address="([^"]+)"', raw)
        destination = destination_match.group(1) if destination_match else "any"
        family = _rich_value(raw, "family").replace("ipv", "ipv") or "any"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        rules.append(FirewallRule(id=f"firewalld:{digest}", backend=FirewallBackend.firewalld, action=action, protocol=protocol, port=port, source=source, destination=destination, family=family, raw=raw))
    return rules


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
        raw = json.dumps(expressions, ensure_ascii=False, separators=(",", ":"))
        verdict = "allow" if '"accept"' in raw else "reject" if '"reject"' in raw else "drop" if '"drop"' in raw else "unknown"
        rules.append(FirewallRule(
            id=f"nft:{family}:{table}:{chain}:{handle}", backend=FirewallBackend.nftables,
            action=verdict, direction="out" if chain.lower().startswith("out") else "in",
            family="ipv4" if family == "ip" else "ipv6" if family == "ip6" else "any",
            comment=str(item.get("comment") or "")[:120], editable=table == "webnas" and chain in {"input", "output"}, raw=raw,
        ))
    return rules


class FirewallService:
    def __init__(self, *, system: FirewallSystem | None = None, root: Path | None = None) -> None:
        self.system = system or FirewallSystem()
        self.root = root or Path(get_config().paths.data_dir) / "firewall-manager"
        self.backups_root = self.root / "backups"
        self.backups_root.mkdir(parents=True, exist_ok=True)

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
        family = "ipv6" if rule.family == "ipv6" else "ipv4"
        parts = [f'rule family="{family}"']
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
        return {"schema": 1, "created_at": time.time(), "backend": status["backend"], "active": status["active"], "rules": [item.model_dump(mode="json", exclude={"raw", "id", "backend", "editable"}) for item in self.rules()]}

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
        current = self.rules()
        backend = self.system.detect()[0]
        removable = [item for item in current if backend != FirewallBackend.nftables or item.editable]
        for item in reversed(removable):
            self.delete_rule(item.id)
        restored = 0
        try:
            for raw in payload["rules"][:2000]:
                self.add_rule(FirewallRuleInput.model_validate(raw))
                restored += 1
            if bool(payload.get("active")) != bool(self.status().get("active")):
                self.set_enabled(bool(payload.get("active")))
        except Exception:
            for item in current:
                if backend == FirewallBackend.nftables and not item.editable:
                    continue
                try:
                    self.add_rule(self._input_from_rule(item))
                except Exception:
                    pass
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
