from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Iterable

from ..firewall_manager import service as firewall_service
from .models import ComplianceControl, ComplianceSeverity, ComplianceStatus


BENCHMARK_ID = "cis-linux-level1"
PROFILE = "level1"
CATEGORIES = ("ssh", "sudo", "filesystem", "kernel", "pam", "firewall")


def benchmark_metadata() -> dict[str, object]:
    return {
        "id": BENCHMARK_ID,
        "name": "CIS-aligned Linux Level 1",
        "profile": PROFILE,
        "categories": list(CATEGORIES),
        "scope": "Selected automatable host controls mapped to common CIS Linux Level 1 guidance.",
        "disclaimer": "This is a CIS-aligned assessment, not an official CIS certification. Exact control numbering and applicability vary by distribution and benchmark version.",
    }


def _control(
    control_id: str,
    benchmark_ref: str,
    category: str,
    title: str,
    status: ComplianceStatus,
    severity: ComplianceSeverity,
    expected: str,
    actual: str,
    rationale: str,
    remediation: str,
    evidence: dict[str, object] | None = None,
) -> ComplianceControl:
    return ComplianceControl(
        id=control_id,
        benchmark_id=BENCHMARK_ID,
        benchmark_ref=benchmark_ref,
        profile=PROFILE,
        category=category,
        title=title,
        status=status,
        severity=severity,
        expected=expected,
        actual=actual,
        rationale=rationale,
        remediation=remediation,
        evidence=evidence or {},
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_sshd_config(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("match "):
            break
        key, separator, value = line.partition(" ")
        if separator:
            values[key.lower()] = value.strip().lower()
    return values


def _sshd_effective() -> dict[str, str]:
    executable = shutil.which("sshd")
    if executable:
        try:
            result = subprocess.run(
                [executable, "-T"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                shell=False,
            )  # nosec B603
        except (OSError, subprocess.SubprocessError):
            result = None
        if result and result.returncode == 0:
            values: dict[str, str] = {}
            for line in result.stdout.splitlines():
                key, separator, value = line.partition(" ")
                if separator:
                    values[key.lower()] = value.strip().lower()
            return values
    text = _read_text(Path("/etc/ssh/sshd_config"))
    return parse_sshd_config(text or "")


def _simple_value_control(
    control_id: str,
    benchmark_ref: str,
    category: str,
    title: str,
    actual: str | None,
    allowed: set[str],
    severity: ComplianceSeverity,
    expected: str,
    rationale: str,
    remediation: str,
) -> ComplianceControl:
    if actual is None or actual == "":
        status = ComplianceStatus.manual
        actual_text = "not detected"
    else:
        status = ComplianceStatus.passed if actual.lower() in allowed else ComplianceStatus.failed
        actual_text = actual
    return _control(control_id, benchmark_ref, category, title, status, severity, expected, actual_text, rationale, remediation)


def ssh_controls() -> list[ComplianceControl]:
    values = _sshd_effective()
    controls = [
        _simple_value_control(
            "ssh.root-login",
            "CIS Linux L1: SSH root login",
            "ssh",
            "Disable unrestricted SSH root login",
            values.get("permitrootlogin"),
            {"no", "prohibit-password", "forced-commands-only"},
            ComplianceSeverity.high,
            "PermitRootLogin no (or a restricted equivalent)",
            "Direct privileged logins reduce attribution and increase impact of credential compromise.",
            "Set PermitRootLogin to no or a documented restricted mode, validate sshd_config and reload sshd.",
        ),
        _simple_value_control(
            "ssh.empty-passwords",
            "CIS Linux L1: SSH empty passwords",
            "ssh",
            "Disable SSH empty passwords",
            values.get("permitemptypasswords"),
            {"no"},
            ComplianceSeverity.critical,
            "PermitEmptyPasswords no",
            "Empty-password authentication permits trivial account compromise.",
            "Set PermitEmptyPasswords no, validate sshd_config and reload sshd.",
        ),
        _simple_value_control(
            "ssh.x11-forwarding",
            "CIS Linux L1: SSH X11 forwarding",
            "ssh",
            "Disable SSH X11 forwarding",
            values.get("x11forwarding"),
            {"no"},
            ComplianceSeverity.medium,
            "X11Forwarding no",
            "Unneeded X11 forwarding expands the remote attack surface.",
            "Set X11Forwarding no where graphical forwarding is not explicitly required.",
        ),
    ]
    raw_tries = values.get("maxauthtries")
    try:
        max_tries = int(raw_tries or "")
    except ValueError:
        max_tries = None
    status = ComplianceStatus.manual if max_tries is None else ComplianceStatus.passed if max_tries <= 4 else ComplianceStatus.failed
    controls.append(
        _control(
            "ssh.max-auth-tries",
            "CIS Linux L1: SSH MaxAuthTries",
            "ssh",
            "Limit SSH authentication attempts",
            status,
            ComplianceSeverity.medium,
            "MaxAuthTries <= 4",
            raw_tries or "not detected",
            "A low retry limit reduces password-guessing opportunities per connection.",
            "Set MaxAuthTries to 4 or lower after validating operational requirements.",
        )
    )
    return controls


def _sudoers_text() -> tuple[str, list[str]]:
    paths = [Path("/etc/sudoers")]
    directory = Path("/etc/sudoers.d")
    try:
        paths.extend(sorted(path for path in directory.iterdir() if path.is_file() and not path.name.endswith("~")))
    except OSError:
        pass
    values: list[str] = []
    readable: list[str] = []
    for path in paths:
        text = _read_text(path)
        if text is not None:
            values.append(text)
            readable.append(str(path))
    return "\n".join(values), readable


def sudo_controls() -> list[ComplianceControl]:
    text, paths = _sudoers_text()
    if not paths:
        return [
            _control(
                "sudo.policy-readable",
                "CIS Linux L1: sudo configuration",
                "sudo",
                "Read sudo policy",
                ComplianceStatus.error,
                ComplianceSeverity.medium,
                "At least one readable sudoers policy file",
                "no readable sudoers policy",
                "The compliance engine cannot assess sudo hardening without configuration visibility.",
                "Verify sudo installation and permissions on /etc/sudoers and /etc/sudoers.d.",
            )
        ]
    active = "\n".join(line.split("#", 1)[0].strip() for line in text.splitlines())
    use_pty = bool(re.search(r"(?im)^\s*Defaults(?:\s+[^\n]*)?\buse_pty\b", active))
    logfile = bool(re.search(r"(?im)^\s*Defaults(?:\s+[^\n]*)?\blogfile\s*=", active))
    nopasswd = len(re.findall(r"(?im)^[^#\n]*\bNOPASSWD\s*:", text))
    return [
        _control(
            "sudo.use-pty",
            "CIS Linux L1: sudo use_pty",
            "sudo",
            "Run sudo commands in a pseudo-terminal",
            ComplianceStatus.passed if use_pty else ComplianceStatus.failed,
            ComplianceSeverity.medium,
            "Defaults use_pty",
            "configured" if use_pty else "not detected",
            "A pseudo-terminal improves command isolation and auditability.",
            "Add a validated Defaults use_pty entry through visudo.",
            {"files": paths},
        ),
        _control(
            "sudo.logfile",
            "CIS Linux L1: sudo logfile",
            "sudo",
            "Configure a dedicated sudo log file",
            ComplianceStatus.passed if logfile else ComplianceStatus.failed,
            ComplianceSeverity.low,
            "Defaults logfile=<absolute path>",
            "configured" if logfile else "not detected",
            "Dedicated sudo logging supports traceability of privileged command use.",
            "Configure an approved sudo logfile with visudo and protect the target log path.",
            {"files": paths},
        ),
        _control(
            "sudo.nopasswd-review",
            "CIS-aligned policy: sudo NOPASSWD review",
            "sudo",
            "Review passwordless sudo grants",
            ComplianceStatus.manual if nopasswd else ComplianceStatus.passed,
            ComplianceSeverity.medium,
            "No undocumented NOPASSWD grants",
            f"{nopasswd} NOPASSWD grant(s) detected",
            "Passwordless elevation can be valid for automation but must be narrowly scoped and documented.",
            "Review each NOPASSWD grant for command, user/group and automation scope; remove broad or unused grants.",
            {"nopasswd_grants": nopasswd},
        ),
    ]


def _mount_options(mountpoint: str) -> set[str] | None:
    text = _read_text(Path("/proc/self/mounts"))
    if text is None:
        return None
    best: tuple[int, set[str]] | None = None
    for raw in text.splitlines():
        fields = raw.split()
        if len(fields) < 4:
            continue
        mounted = fields[1].replace("\\040", " ")
        if mounted != mountpoint:
            continue
        options = set(fields[3].split(","))
        candidate = (len(mounted), options)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best[1] if best else set()


def _mount_control(mountpoint: str, control_id: str) -> ComplianceControl:
    options = _mount_options(mountpoint)
    required = {"nodev", "nosuid", "noexec"}
    if options is None:
        status = ComplianceStatus.error
        actual = "mount table unavailable"
    elif not options:
        status = ComplianceStatus.manual
        actual = "no dedicated mount detected"
    else:
        missing = sorted(required - options)
        status = ComplianceStatus.passed if not missing else ComplianceStatus.failed
        actual = f"options={','.join(sorted(options))}; missing={','.join(missing) or 'none'}"
    return _control(
        control_id,
        f"CIS Linux L1: {mountpoint} mount options",
        "filesystem",
        f"Harden {mountpoint} mount options",
        status,
        ComplianceSeverity.medium,
        "nodev,nosuid,noexec on the dedicated mount",
        actual,
        "Restrictive mount flags reduce execution and device abuse in shared temporary filesystems.",
        f"Use a distribution-appropriate dedicated {mountpoint} mount with nodev,nosuid,noexec when applicable.",
    )


def _file_mode_control(path: str, control_id: str, maximum_mode: int, severity: ComplianceSeverity) -> ComplianceControl:
    target = Path(path)
    try:
        details = target.stat()
    except OSError:
        return _control(
            control_id,
            f"CIS Linux L1: {path} ownership and permissions",
            "filesystem",
            f"Protect {path}",
            ComplianceStatus.error,
            severity,
            f"root-owned and mode no broader than {maximum_mode:04o}",
            "stat failed",
            "Authentication databases and account metadata require restrictive ownership and modes.",
            f"Restore distribution-approved root ownership and permissions on {path}.",
        )
    mode = stat.S_IMODE(details.st_mode)
    owner_ok = details.st_uid == 0
    mode_ok = mode & ~maximum_mode == 0
    return _control(
        control_id,
        f"CIS Linux L1: {path} ownership and permissions",
        "filesystem",
        f"Protect {path}",
        ComplianceStatus.passed if owner_ok and mode_ok else ComplianceStatus.failed,
        severity,
        f"root-owned and mode no broader than {maximum_mode:04o}",
        f"uid={details.st_uid}, mode={mode:04o}",
        "Authentication databases and account metadata require restrictive ownership and modes.",
        f"Restore distribution-approved root ownership and permissions on {path}.",
        {"uid": details.st_uid, "gid": details.st_gid, "mode": f"{mode:04o}"},
    )


def filesystem_controls() -> list[ComplianceControl]:
    return [
        _mount_control("/tmp", "filesystem.tmp-options"),
        _mount_control("/dev/shm", "filesystem.dev-shm-options"),
        _file_mode_control("/etc/passwd", "filesystem.passwd-mode", 0o644, ComplianceSeverity.high),
        _file_mode_control("/etc/shadow", "filesystem.shadow-mode", 0o640, ComplianceSeverity.critical),
    ]


def _sysctl_value(name: str) -> str | None:
    path = Path("/proc/sys") / Path(name.replace(".", "/"))
    text = _read_text(path)
    return text.strip() if text is not None else None


def kernel_controls() -> list[ComplianceControl]:
    settings = [
        ("kernel.randomize_va_space", "2", ComplianceSeverity.high, "Enable full ASLR"),
        ("fs.protected_hardlinks", "1", ComplianceSeverity.medium, "Protect hard links"),
        ("fs.protected_symlinks", "1", ComplianceSeverity.medium, "Protect symbolic links"),
        ("net.ipv4.conf.all.accept_redirects", "0", ComplianceSeverity.medium, "Reject IPv4 ICMP redirects"),
        ("net.ipv4.conf.default.accept_redirects", "0", ComplianceSeverity.medium, "Reject default IPv4 ICMP redirects"),
        ("net.ipv4.conf.all.send_redirects", "0", ComplianceSeverity.medium, "Disable IPv4 redirect sending"),
    ]
    controls: list[ComplianceControl] = []
    for name, expected_value, severity, title in settings:
        actual = _sysctl_value(name)
        status = ComplianceStatus.manual if actual is None else ComplianceStatus.passed if actual == expected_value else ComplianceStatus.failed
        controls.append(
            _control(
                f"kernel.{name}",
                f"CIS Linux L1: sysctl {name}",
                "kernel",
                title,
                status,
                severity,
                f"{name}={expected_value}",
                actual or "not available",
                "Kernel hardening settings reduce common local and network attack primitives.",
                f"Set {name}={expected_value} through the distribution sysctl configuration and apply it in a controlled change.",
            )
        )
    return controls


def _pam_text() -> tuple[str, list[str]]:
    candidates = [
        Path("/etc/pam.d/common-auth"),
        Path("/etc/pam.d/common-password"),
        Path("/etc/pam.d/system-auth"),
        Path("/etc/pam.d/password-auth"),
    ]
    values: list[str] = []
    readable: list[str] = []
    for path in candidates:
        text = _read_text(path)
        if text is not None:
            values.append(text)
            readable.append(str(path))
    return "\n".join(values), readable


def _login_defs_encrypt_method() -> str | None:
    text = _read_text(Path("/etc/login.defs"))
    if text is None:
        return None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].upper() == "ENCRYPT_METHOD":
            return parts[1].lower()
    return None


def pam_controls() -> list[ComplianceControl]:
    text, paths = _pam_text()
    if not paths:
        quality_status = ComplianceStatus.error
        lockout_status = ComplianceStatus.error
    else:
        quality_status = ComplianceStatus.passed if re.search(r"\bpam_(?:pwquality|cracklib)\.so\b", text) else ComplianceStatus.failed
        lockout_status = ComplianceStatus.passed if re.search(r"\bpam_(?:faillock|tally2)\.so\b", text) else ComplianceStatus.failed
    encrypt = _login_defs_encrypt_method()
    hash_status = ComplianceStatus.manual if encrypt is None else ComplianceStatus.passed if encrypt in {"yescrypt", "sha512"} else ComplianceStatus.failed
    return [
        _control(
            "pam.password-quality",
            "CIS Linux L1: PAM password quality",
            "pam",
            "Enforce PAM password quality",
            quality_status,
            ComplianceSeverity.high,
            "pam_pwquality.so or an approved equivalent",
            "configured" if quality_status == ComplianceStatus.passed else "not detected",
            "Password-quality controls reduce weak local credentials.",
            "Configure the distribution-supported password quality PAM module and policy.",
            {"files": paths},
        ),
        _control(
            "pam.failed-login-lockout",
            "CIS Linux L1: PAM failed-login lockout",
            "pam",
            "Configure failed-login lockout",
            lockout_status,
            ComplianceSeverity.high,
            "pam_faillock.so or an approved equivalent",
            "configured" if lockout_status == ComplianceStatus.passed else "not detected",
            "Login throttling and lockout reduce online password guessing against local accounts.",
            "Configure the distribution-supported faillock policy and verify recovery procedures for administrators.",
            {"files": paths},
        ),
        _control(
            "pam.password-hash",
            "CIS Linux L1: strong password hashing",
            "pam",
            "Use a strong local password hash",
            hash_status,
            ComplianceSeverity.medium,
            "ENCRYPT_METHOD yescrypt or SHA512",
            encrypt or "not detected",
            "Modern password hashes improve resistance to offline credential cracking.",
            "Set the distribution-supported strong password hashing method and validate PAM/login.defs consistency.",
        ),
    ]


def firewall_controls() -> list[ComplianceControl]:
    try:
        state = firewall_service().status()
        rules = firewall_service().rules()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return [
            _control(
                "firewall.state",
                "CIS Linux L1: host firewall",
                "firewall",
                "Keep a host firewall active",
                ComplianceStatus.error,
                ComplianceSeverity.critical,
                "Supported host firewall active",
                type(error).__name__,
                "A local firewall provides a final host-level network policy boundary.",
                "Open Firewall Manager, verify the backend and review an access-safe ruleset.",
            )
        ]
    active = bool(state.get("active"))
    backend = str(state.get("backend") or "unknown")
    return [
        _control(
            "firewall.state",
            "CIS Linux L1: host firewall enabled",
            "firewall",
            "Keep a host firewall active",
            ComplianceStatus.passed if active else ComplianceStatus.failed,
            ComplianceSeverity.critical,
            "Supported host firewall active",
            f"backend={backend}, active={active}",
            "A local firewall provides a final host-level network policy boundary.",
            "Enable the supported firewall only after reviewing an access-safe policy in Firewall Manager.",
            {"backend": backend, "active": active},
        ),
        _control(
            "firewall.ruleset",
            "CIS-aligned policy: explicit host ruleset",
            "firewall",
            "Maintain an explicit host firewall ruleset",
            ComplianceStatus.passed if active and bool(rules) else ComplianceStatus.failed,
            ComplianceSeverity.high,
            "Active firewall with at least one normalized rule",
            f"{len(rules)} normalized rule(s)",
            "An enabled backend without an intentional ruleset may not enforce the expected least-privilege policy.",
            "Review inbound exposure and define the required host rules in Firewall Manager.",
            {"rules": len(rules)},
        ),
    ]


def run_checks(categories: Iterable[str] | None = None) -> list[ComplianceControl]:
    requested = set(categories or CATEGORIES)
    checks = {
        "ssh": ssh_controls,
        "sudo": sudo_controls,
        "filesystem": filesystem_controls,
        "kernel": kernel_controls,
        "pam": pam_controls,
        "firewall": firewall_controls,
    }
    controls: list[ComplianceControl] = []
    for category in CATEGORIES:
        if category in requested:
            controls.extend(checks[category]())
    return controls
