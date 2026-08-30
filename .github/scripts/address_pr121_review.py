from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def must_replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, count))


# Privileged broker: service lifecycle for supported firewall backends must remain allowlisted.
policy = "backend/app/privileged_broker/policy.py"
text = read(policy)
if '"firewalld.service", "nftables.service"' not in text:
    must_replace(
        policy,
        '    "kea-dhcp4-server.service", "kea-dhcp4.service", "isc-dhcp-server.service", "dhcpd.service",\n',
        '    "kea-dhcp4-server.service", "kea-dhcp4.service", "isc-dhcp-server.service", "dhcpd.service",\n    "firewalld.service", "nftables.service",\n',
    )


# Firewall Manager hardening.
path = "backend/app/modules/firewall_manager/service.py"
text = read(path)
if "import threading\n" not in text:
    text = text.replace("import shutil\n", "import shutil\nimport threading\n", 1)
if "from collections.abc import Iterator\n" not in text:
    text = text.replace("from functools import lru_cache\n", "from collections.abc import Iterator\nfrom contextlib import contextmanager\nfrom functools import lru_cache\n", 1)
text = text.replace(
    "        target = destination_field.strip()\n",
    '        target = re.sub(r"\\s+\\(v6\\)$", "", destination_field.strip(), flags=re.IGNORECASE)\n',
    1,
)
text = text.replace(
    '        source = _rich_value(raw, "address") or "any"\n        destination_match = re.search(r\'destination\\s+address="([^\"]+)"\', raw)\n        destination = destination_match.group(1) if destination_match else "any"\n',
    '        source_match = re.search(r\'source\\s+address="([^\"]+)"\', raw)\n        source = source_match.group(1) if source_match else "any"\n        destination_match = re.search(r\'destination\\s+address="([^\"]+)"\', raw)\n        destination = destination_match.group(1) if destination_match else "any"\n',
    1,
)

start = text.index("def parse_nft_rules(content: str) -> list[FirewallRule]:\n")
end = text.index("\n\nclass FirewallService:", start)
new_nft = '''def _nft_scalar(value: Any) -> str:
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
'''
text = text[:start] + new_nft + text[end:]

init_anchor = '''        self.backups_root = self.root / "backups"
        self.backups_root.mkdir(parents=True, exist_ok=True)
'''
if "self._transaction_lock" not in text:
    text = text.replace(
        init_anchor,
        init_anchor + "        self._transaction_lock = threading.RLock()\n",
        1,
    )
transaction_anchor = "    def status(self) -> dict[str, Any]:\n"
if "def transaction(self)" not in text:
    text = text.replace(
        transaction_anchor,
        '''    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._transaction_lock:
            yield

''' + transaction_anchor,
        1,
    )

fw_start = text.index("    def _firewalld_rich(self, rule: FirewallRuleInput) -> str:\n")
fw_end = text.index("\n    def _ensure_nft(self) -> None:", fw_start)
new_fw = '''    def _firewalld_rich(self, rule: FirewallRuleInput) -> str:
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
'''
text = text[:fw_start] + new_fw + text[fw_end:]

old_export = '''    def export_configuration(self) -> dict[str, Any]:
        status = self.status()
        return {"schema": 1, "created_at": time.time(), "backend": status["backend"], "active": status["active"], "rules": [item.model_dump(mode="json", exclude={"raw", "id", "backend", "editable"}) for item in self.rules()]}
'''
new_export = '''    def export_configuration(self) -> dict[str, Any]:
        status = self.status()
        rules = self.rules()
        if status["backend"] == FirewallBackend.nftables.value:
            rules = [item for item in rules if item.editable]
        return {"schema": 1, "created_at": time.time(), "backend": status["backend"], "active": status["active"], "rules": [item.model_dump(mode="json", exclude={"raw", "id", "backend", "editable", "enabled"}) for item in rules]}
'''
if old_export not in text:
    raise SystemExit("firewall export anchor missing")
text = text.replace(old_export, new_export, 1)

backup_anchor = "    def create_backup(self, description: str = \"\") -> dict[str, Any]:\n"
if "def import_configuration" not in text:
    import_method = '''    def import_configuration(self, configuration: dict[str, Any]) -> dict[str, Any]:
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

'''
    text = text.replace(backup_anchor, import_method + backup_anchor, 1)

restore_start = text.index("    def restore_backup(self, backup_id: str) -> dict[str, Any]:\n")
restore_end = text.index("\n    def activity(self)", restore_start)
new_restore = '''    def restore_backup(self, backup_id: str) -> dict[str, Any]:
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
'''
text = text[:restore_start] + new_restore + text[restore_end:]
write(path, text)


# Firewall router: public endpoint, serialized transactions, import endpoint, exact JobHandler signature.
path = "backend/app/modules/firewall_manager/router.py"
text = read(path)
if "from ...config import get_config\n" not in text:
    text = text.replace("from ...auth import authenticate\n", "from ...auth import authenticate\nfrom ...config import get_config\n", 1)
text = text.replace(
    "from .models import FirewallActionRequest, FirewallBackupRequest, FirewallMutationRequest, FirewallRuleInput",
    "from .models import FirewallActionRequest, FirewallBackupRequest, FirewallImportRequest, FirewallMutationRequest, FirewallRuleInput",
    1,
)
old_context = '''def _request_context(request: Request) -> tuple[str, int]:
    client_ip = request.client.host if request.client else ""
    server = request.scope.get("server")
    port = int(server[1]) if isinstance(server, (list, tuple)) and len(server) > 1 and isinstance(server[1], int) else 0
    return client_ip, port
'''
new_context = '''def _request_context(request: Request) -> tuple[str, int]:
    client_ip = request.client.host if request.client else ""
    return client_ip, int(get_config().server.port)
'''
if old_context in text:
    text = text.replace(old_context, new_context, 1)
job_start = text.index("def _job(actor: str, operation: str, handler: Callable[[JobContext], dict[str, Any]]) -> dict[str, Any]:\n")
job_end = text.index("\n\n@router.get(\"/status\")", job_start)
new_job = '''def _job(actor: str, operation: str, handler: Callable[[JobContext], dict[str, Any]]) -> dict[str, Any]:
    def execute(context: JobContext, metadata: dict[str, Any]) -> dict[str, Any] | None:
        _ = metadata
        firewall = service()
        with firewall.transaction():
            firewall.record(actor, f"firewall.{operation}.started")
            context.update_progress(10, "Validate and snapshot firewall")
            rollback = firewall.create_backup(f"Automatic rollback before {operation}")
            try:
                context.update_progress(40, "Apply firewall change")
                result = handler(context)
                context.update_progress(80, "Verify firewall state")
                firewall.status()
                firewall.record(actor, f"firewall.{operation}", details={"rollback_backup": rollback["id"]})
                return {**result, "rollback_backup": rollback["id"]}
            except Exception as error:
                try:
                    firewall.restore_backup(rollback["id"])
                except Exception as rollback_error:
                    firewall.record(actor, f"firewall.{operation}", status=ActivityStatus.failure, summary=f"{type(error).__name__}; rollback={type(rollback_error).__name__}")
                    raise RuntimeError("firewall operation failed and automatic rollback could not be completed") from error
                firewall.record(actor, f"firewall.{operation}", status=ActivityStatus.failure, summary=type(error).__name__)
                raise
    job = jobs().submit_callable(job_type=f"firewall.{operation}", module="firewall-manager", created_by=actor, handler=execute, metadata={"operation": operation}, cancellable=False)
    return {"job": job.model_dump(mode="json")}
'''
text = text[:job_start] + new_job + text[job_end:]
import_anchor = '@router.get("/backups")\ndef backups(user: SessionUser = Depends(current_user)):\n'
if '@router.post("/import")' not in text:
    endpoint = '''@router.post("/import")
def import_config(payload: FirewallImportRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_RESTORE)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:import")
    _safe("import", request=request, acknowledge=payload.acknowledge_lockout)
    configuration = payload.configuration
    return _job(user.username, "import", lambda _context: service().import_configuration(configuration))


'''
    if import_anchor not in text:
        raise SystemExit("firewall import endpoint anchor missing")
    text = text.replace(import_anchor, endpoint + import_anchor, 1)
write(path, text)


# Security Center: GET never starts expensive scans; resolved-but-detected findings reopen.
path = "backend/app/modules/security_center/service.py"
text = read(path)
text = text.replace(
    '            if configured in {FindingStatus.acknowledged.value, FindingStatus.resolved.value}:\n                item.status = FindingStatus(configured)\n',
    '            if configured == FindingStatus.acknowledged.value:\n                item.status = FindingStatus.acknowledged\n',
    1,
)
old_snapshot = '''    def _snapshot(self) -> tuple[list[SecurityFinding], dict[str, dict[str, Any]], float | None]:
        with self._lock:
            timestamp = self._last_scan["timestamp"]
        if timestamp is None:
            self.scan()
        with self._lock:
            return list(self._last_scan["findings"]), dict(self._last_scan["metrics"]), self._last_scan["timestamp"]
'''
new_snapshot = '''    def _snapshot(self) -> tuple[list[SecurityFinding], dict[str, dict[str, Any]], float | None]:
        with self._lock:
            return list(self._last_scan["findings"]), dict(self._last_scan["metrics"]), self._last_scan["timestamp"]
'''
if old_snapshot in text:
    text = text.replace(old_snapshot, new_snapshot, 1)
summary_marker = '        severity = {level.value: sum(1 for item in active if item.severity == level) for level in Severity}\n'
if 'if timestamp is None:' not in text[text.index("    def summary"):]:
    text = text.replace(
        summary_marker,
        summary_marker + '        if timestamp is None:\n            return {"score": None, "severity": severity, "areas": {}, "metrics": {}, "findings": 0, "last_scan": None}\n',
        1,
    )
write(path, text)


# Network Tools: correct PTR lookup and enforce TLS >= 1.2.
path = "backend/app/modules/network_tools/service.py"
text = read(path)
if "import ipaddress\n" not in text:
    text = text.replace("import json\n", "import ipaddress\nimport json\n", 1)
old_dns = '        args += [payload.hostname, payload.record_type]\n'
new_dns = '''        try:
            ptr_address = str(ipaddress.ip_address(payload.hostname)) if payload.record_type == "PTR" else None
        except ValueError:
            ptr_address = None
        args += ["-x", ptr_address] if ptr_address else [payload.hostname, payload.record_type]
'''
if old_dns in text:
    text = text.replace(old_dns, new_dns, 1)
old_tls = "            context = ssl.create_default_context()\n            wrapped = context.wrap_socket(raw, server_hostname=hostname)\n"
new_tls = "            context = ssl.create_default_context()\n            context.minimum_version = ssl.TLSVersion.TLSv1_2\n            wrapped = context.wrap_socket(raw, server_hostname=hostname)\n"
if old_tls in text:
    text = text.replace(old_tls, new_tls, 1)
write(path, text)


# Package manifests must not advertise hooks that do not exist.
for manifest in (
    "backend/app/modules/firewall-manager/manifest.yaml",
    "backend/app/modules/network-tools/manifest.yaml",
    "backend/app/modules/security-center/manifest.yaml",
):
    text = read(manifest)
    text = text.replace("  healthcheck: true\n", "  healthcheck: false\n", 1)
    text = text.replace("healthcheck: health.py\n", "", 1)
    write(manifest, text)


# API typing for unscanned Security Center state.
path = "frontend/src/modules/security-center/api/client.ts"
text = read(path)
text = text.replace("export type Summary = { score: number;", "export type Summary = { score: number | null;", 1)
write(path, text)


# Regression tests for the security-sensitive review findings.
path = "backend/tests/test_firewall_manager.py"
text = read(path)
if "test_ufw_parser_preserves_ipv6_port" not in text:
    text += '''

def test_ufw_parser_preserves_ipv6_port() -> None:
    rules = parse_ufw_rules("Status: active\\n[ 2] 22/tcp (v6) ALLOW IN Anywhere (v6)\\n")
    assert len(rules) == 1
    assert rules[0].port == "22"
    assert rules[0].protocol == "tcp"
    assert rules[0].family == "ipv6"


def test_firewalld_parser_does_not_treat_destination_as_source() -> None:
    rules = parse_firewalld_rules('rule family="ipv4" destination address="10.0.0.0/8" drop\\n')
    assert rules[0].source == "any"
    assert rules[0].destination == "10.0.0.0/8"


def test_firewalld_family_any_is_not_forced_to_ipv4(tmp_path: Path) -> None:
    service = FirewallService(root=tmp_path)
    rich = service._firewalld_rich(FirewallRuleInput(action="drop", protocol="tcp", port="22", family="any"))
    assert 'family=' not in rich


def test_nft_parser_preserves_supported_match_predicates() -> None:
    payload = '{"nftables":[{"rule":{"family":"inet","table":"webnas","chain":"input","handle":5,"expr":[{"match":{"op":"==","left":{"payload":{"protocol":"tcp","field":"dport"}},"right":22}},{"accept":null}]}}]}'
    rule = parse_nft_rules(payload)[0]
    assert rule.editable is True
    assert rule.protocol == "tcp"
    assert rule.port == "22"


def test_nft_parser_marks_unknown_webnas_expression_read_only() -> None:
    payload = '{"nftables":[{"rule":{"family":"inet","table":"webnas","chain":"input","handle":6,"expr":[{"match":{"op":"==","left":{"ct":{"key":"state"}},"right":"established"}},{"accept":null}]}}]}'
    assert parse_nft_rules(payload)[0].editable is False
'''
write(path, text)

path = "backend/tests/test_security_center.py"
text = read(path)
if "import app.modules.security_center.service as security_service_module" not in text:
    text = text.replace("from pathlib import Path\n", "from pathlib import Path\n\nimport app.modules.security_center.service as security_service_module\n", 1)
if "test_unscanned_summary_does_not_run_checks" not in text:
    text += '''

def test_unscanned_summary_does_not_run_checks(tmp_path: Path, monkeypatch) -> None:
    repository = SecurityStateRepository(tmp_path / "security.sqlite3")
    service = SecurityCenterService(repository)
    monkeypatch.setattr(security_service_module, "run_checks", lambda: (_ for _ in ()).throw(AssertionError("scan must not run")))
    summary = service.summary()
    assert summary["score"] is None
    assert summary["last_scan"] is None


def test_resolved_finding_reopens_when_detected_again(tmp_path: Path, monkeypatch) -> None:
    repository = SecurityStateRepository(tmp_path / "security.sqlite3")
    repository.set_state("a", FindingStatus.resolved, "admin")
    service = SecurityCenterService(repository)
    monkeypatch.setattr(security_service_module, "run_checks", lambda: ([_finding(Severity.critical)], {}))
    service.scan()
    assert service.findings()[0].status == FindingStatus.open
'''
write(path, text)

path = "backend/tests/test_network_tools.py"
text = read(path)
if "test_ptr_address_uses_dig_reverse_mode" not in text:
    text += '''

def test_ptr_address_uses_dig_reverse_mode(monkeypatch) -> None:
    observed: list[str] = []

    class Result:
        returncode = 0
        stdout = "host.example.\\n"
        stderr = ""

    monkeypatch.setattr("app.modules.network_tools.service.shutil.which", lambda _name: "/usr/bin/dig")
    def fake_run(args, **_kwargs):
        observed.extend(args)
        return Result()
    monkeypatch.setattr("app.modules.network_tools.service.subprocess.run", fake_run)
    result = NetworkToolsService.dns_lookup(DnsLookupRequest(hostname="192.0.2.10", record_type="PTR"))
    assert result["success"] is True
    assert observed[-2:] == ["-x", "192.0.2.10"]
'''
write(path, text)
