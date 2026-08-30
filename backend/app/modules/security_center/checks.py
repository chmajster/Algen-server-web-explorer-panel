from __future__ import annotations

import hashlib
import pwd
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from ..providers import LinuxUpdatesProvider
from ...transport import read_transport_settings
from ..firewall_manager import service as firewall_service
from .models import SecurityFinding, Severity


def _fingerprint(check_id: str, resource: str) -> str:
    return hashlib.sha256(f"{check_id}\0{resource}".encode()).hexdigest()[:24]


def finding(check_id: str, severity: Severity, title: str, description: str, resource: str, source: str, recommendation: str, category: str, evidence: dict[str, object] | None = None) -> SecurityFinding:
    return SecurityFinding(id=_fingerprint(check_id, resource), check_id=check_id, severity=severity, title=title, description=description, affected_resource=resource, detection_source=source, recommendation=recommendation, timestamp=time.time(), category=category, evidence=evidence or {})


def _sshd_effective() -> dict[str, str]:
    executable = shutil.which("sshd")
    if executable:
        try:
            result = subprocess.run([executable, "-T"], capture_output=True, text=True, timeout=8, check=False, shell=False)  # nosec B603
        except (OSError, subprocess.SubprocessError):
            result = None
        if result and result.returncode == 0:
            values: dict[str, str] = {}
            for line in result.stdout.splitlines():
                key, separator, value = line.partition(" ")
                if separator and key:
                    values[key.lower()] = value.strip().lower()
            return values
    try:
        lines = Path("/etc/ssh/sshd_config").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    values = {}
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or line.lower().startswith("match "):
            continue
        key, separator, value = line.partition(" ")
        if separator:
            values[key.lower()] = value.strip().lower()
    return values


def firewall_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    state = firewall_service().status()
    rules = firewall_service().rules()
    findings: list[SecurityFinding] = []
    if not state.get("active"):
        findings.append(finding("firewall.disabled", Severity.critical, "Firewall is disabled", "The local host firewall is not active.", "local-firewall", "Firewall Manager", "Enable the firewall after reviewing an access-safe ruleset.", "firewall"))
    elif not rules:
        findings.append(finding("firewall.no_rules", Severity.high, "No active firewall rules", "The firewall backend is active but no normalized filtering rules were detected.", "local-firewall", "Firewall Manager", "Define an explicit least-privilege inbound policy.", "firewall"))
    return findings, {"backend": state.get("backend"), "active": bool(state.get("active")), "rules": len(rules)}


def ssh_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    config = _sshd_effective()
    findings: list[SecurityFinding] = []
    root = config.get("permitrootlogin", "unknown")
    passwords = config.get("passwordauthentication", "unknown")
    empty = config.get("permitemptypasswords", "unknown")
    if root not in {"no", "prohibit-password", "forced-commands-only"}:
        findings.append(finding("ssh.root_login", Severity.high, "SSH root login is permitted", f"Effective PermitRootLogin is {root}.", "sshd", "SSH configuration", "Set PermitRootLogin to no or prohibit-password.", "authentication", {"permit_root_login": root}))
    if passwords == "yes":
        findings.append(finding("ssh.password_auth", Severity.medium, "SSH password authentication is enabled", "SSH accepts password-based authentication.", "sshd", "SSH configuration", "Prefer public-key authentication and disable PasswordAuthentication after validating key access.", "authentication"))
    if empty == "yes":
        findings.append(finding("ssh.empty_password", Severity.critical, "SSH permits empty passwords", "PermitEmptyPasswords is enabled.", "sshd", "SSH configuration", "Disable PermitEmptyPasswords immediately.", "authentication"))
    return findings, {"permit_root_login": root, "password_authentication": passwords, "permit_empty_passwords": empty}


def update_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    try:
        status = LinuxUpdatesProvider("linux-updates").get_status()
        metrics = dict(status.metrics)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return [finding("updates.unavailable", Severity.info, "Update status unavailable", "Security Center could not read the Linux Updates provider.", "linux-updates", "Linux Updates", "Open Linux Updates and verify repository/package-manager health.", "updates", {"error": type(error).__name__})], {}
    security = int(metrics.get("security_updates") or 0)
    updates = int(metrics.get("updates") or 0)
    findings = []
    if security:
        findings.append(finding("updates.security", Severity.high, "Security updates are available", f"{security} security update(s) are available.", "linux-updates", "Linux Updates", "Review and apply security updates through Linux Updates.", "updates", {"security_updates": security}))
    elif updates:
        findings.append(finding("updates.available", Severity.low, "Package updates are available", f"{updates} package update(s) are available.", "linux-updates", "Linux Updates", "Review pending updates.", "updates", {"updates": updates}))
    if metrics.get("reboot_required"):
        findings.append(finding("updates.reboot", Severity.medium, "Reboot is required", "The host reports a pending reboot after package changes.", "local-host", "Linux Updates", "Schedule a controlled reboot.", "updates"))
    return findings, metrics


def network_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    ports = firewall_service().listening_ports()
    findings: list[SecurityFinding] = []
    public = [item for item in ports if item.get("address") in {"0.0.0.0", "::", "*"}]
    unmatched = [item for item in public if not item.get("firewall_rule")]
    for item in unmatched[:20]:
        resource = f"{item.get('protocol')}:{item.get('port')}"
        findings.append(finding("network.public_unmatched", Severity.medium, "Public listening port lacks an explicit firewall match", f"{resource} listens on all interfaces and was not matched to a normalized firewall rule.", resource, "Firewall Manager / Networking", "Confirm the service is required and restrict its source networks or listening address.", "network", {"address": str(item.get("address")), "process": str(item.get("process"))[:200]}))
    return findings, {"listening_ports": len(ports), "public_ports": len(public), "unmatched_public_ports": len(unmatched)}


def transport_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    settings = read_transport_settings()
    findings: list[SecurityFinding] = []
    if not settings.use_https:
        findings.append(finding("tls.disabled", Severity.high, "WebNAS HTTPS is disabled", "The WebNAS gateway is configured for HTTP.", "webnas", "HTTPS settings", "Configure a trusted TLS certificate and enable HTTPS.", "tls"))
    return findings, {"https": settings.use_https, "certificate": str(settings.tls_cert or "")}


def user_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    findings: list[SecurityFinding] = []
    try:
        users = pwd.getpwall()
    except OSError:
        users = []
    uid0 = [item.pw_name for item in users if item.pw_uid == 0]
    if len(uid0) > 1:
        findings.append(finding("users.uid0", Severity.critical, "Multiple UID 0 accounts", "More than one local account has UID 0.", "local-users", "Users & Groups / NSS", "Review UID 0 accounts and retain only explicitly required root identities.", "users", {"count": len(uid0), "users": uid0[:20]}))
    return findings, {"accounts": len(users), "uid0_accounts": len(uid0)}


def permission_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    findings: list[SecurityFinding] = []
    paths = [Path("/etc/webnas/webnas.conf"), Path("/var/lib/webnas/settings/transport.json")]
    exposed: list[str] = []
    for path in paths:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            continue
        if mode & 0o022:
            exposed.append(str(path))
    if exposed:
        findings.append(finding("system.config_permissions", Severity.high, "WebNAS configuration is writable by group or others", "Sensitive WebNAS configuration paths have overly broad write permissions.", ", ".join(exposed), "Filesystem permissions", "Restrict configuration files to the WebNAS service account/root as appropriate.", "system", {"paths": exposed}))
    return findings, {"checked_paths": len(paths), "unsafe_paths": len(exposed)}


def failed_login_checks() -> tuple[list[SecurityFinding], dict[str, Any]]:
    executable = shutil.which("journalctl")
    if not executable:
        return [], {"failed_logins": None}
    try:
        result = subprocess.run([executable, "--since", "24 hours ago", "--no-pager", "-n", "2000", "-u", "ssh.service", "-u", "sshd.service"], capture_output=True, text=True, timeout=10, check=False, shell=False)  # nosec B603
    except (OSError, subprocess.SubprocessError):
        return [], {"failed_logins": None}
    count = sum(1 for line in result.stdout.splitlines() if re.search(r"failed password|authentication failure|invalid user", line, re.IGNORECASE))
    findings: list[SecurityFinding] = []
    if count >= 20:
        severity = Severity.high if count >= 100 else Severity.medium
        findings.append(finding("auth.failed_logins", severity, "Elevated failed-login volume", f"{count} failed SSH authentication events were found in the last 24 hours.", "sshd", "systemd journal", "Review authentication logs, source addresses and brute-force controls.", "authentication", {"count": count}))
    return findings, {"failed_logins": count}


def run_checks() -> tuple[list[SecurityFinding], dict[str, dict[str, Any]]]:
    findings: list[SecurityFinding] = []
    metrics: dict[str, dict[str, Any]] = {}
    for name, check in (("firewall", firewall_checks), ("authentication", ssh_checks), ("updates", update_checks), ("network", network_checks), ("tls", transport_checks), ("users", user_checks), ("permissions", permission_checks), ("failed_logins", failed_login_checks)):
        values, details = check()
        findings.extend(values)
        metrics[name] = details
    return findings, metrics
