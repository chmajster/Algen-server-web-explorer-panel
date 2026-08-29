from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence

from app.config import get_config
from app.core.redaction import redact_text

from .protocol import BrokerRequest, BrokerResponse, Operation


SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
SAFE_ENV = {
    "PATH": SAFE_PATH,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
    "HOME": "/root",
}
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$")
UNIT_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}(?:\.service)?$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.:@_~=-]{0,191}$")
UPDATE_UNIT_RE = re.compile(r"^webnas-self-update-[0-9]{1,20}\.service$")
PROTECTED_USERS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp",
    "proxy", "www-data", "backup", "nobody", "systemd-network", "systemd-resolve", "messagebus",
    "pve", "pvedaemon", "pveproxy", "webnas",
}
PROTECTED_GROUPS = {
    "root", "daemon", "sudo", "wheel", "shadow", "adm", "www-data", "backup", "pve", "pveadmin",
    "pveproxy", "pve-cluster", "webnas",
}
PROTECTED_UNITS = {
    "pveproxy.service", "pvedaemon.service", "pve-cluster.service", "corosync.service", "networking.service",
    "ssh.service", "sshd.service", "systemd-logind.service", "dbus.service", "systemd-journald.service",
}
FIXED_SYSTEM_UNITS = {
    "nginx.service", "smbd.service", "nmbd.service", "samba.service", "winbind.service",
    "kea-dhcp4-server.service", "kea-dhcp4.service", "isc-dhcp-server.service", "dhcpd.service",
}
SYSTEMD_ACTIONS = {
    "start", "stop", "restart", "reload", "enable", "disable", "is-active", "is-enabled", "show",
    "daemon-reload",
}
ACCOUNT_TOOLS = {"useradd", "usermod", "userdel", "groupadd", "groupmod", "groupdel", "gpasswd", "chpasswd", "chage"}
PACKAGE_TOOLS = {"apt-get", "dnf", "yum", "zypper", "pacman", "apk", "dpkg", "rpm"}
MANAGED_FILES = {
    "samba_main": Path("/etc/samba/smb.conf"),
    "samba_shares": Path("/etc/samba/algen-shares.conf"),
    "dhcp_kea": Path("/etc/kea/kea-dhcp4.conf"),
    "dhcp_isc": Path("/etc/dhcp/dhcpd.conf"),
    "dhcp_isc_interfaces": Path("/etc/default/isc-dhcp-server"),
}
MAX_OUTPUT = 256 * 1024
MAX_MANAGED_FILE = 2 * 1024 * 1024


class PolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], str | None, float], CommandResult]


def _resolve_tool(name: str) -> str:
    if "/" in name or name.startswith("."):
        raise PolicyError("executable paths are not accepted")
    resolved = shutil.which(name, path=SAFE_PATH)
    if not resolved:
        raise PolicyError(f"required privileged tool is unavailable: {name}")
    candidate = Path(resolved).resolve(strict=False)
    if candidate.name != name or str(candidate.parent) not in {"/usr/sbin", "/usr/bin", "/sbin", "/bin"}:
        raise PolicyError("privileged tool resolved outside the fixed system path")
    return str(candidate)


def _default_runner(argv: Sequence[str], input_text: str | None, timeout: float) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - argv is reconstructed from typed, allowlisted operations below.
        list(argv),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
        env=SAFE_ENV,
    )
    return CommandResult(completed.returncode, completed.stdout[-MAX_OUTPUT:], completed.stderr[-MAX_OUTPUT:])


def _text(payload: dict[str, Any], key: str, *, limit: int = 256, required: bool = True) -> str:
    value = payload.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(ch) < 32 and ch not in "\t\n" for ch in value):
        raise PolicyError(f"invalid {key}")
    return value


def _name(value: str, kind: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise PolicyError(f"invalid {kind} name")
    protected = PROTECTED_USERS if kind == "user" else PROTECTED_GROUPS
    if value in protected or value.startswith("pve"):
        raise PolicyError(f"protected {kind} cannot be modified")
    return value


def _unit_allowed(unit: str) -> str:
    if not UNIT_RE.fullmatch(unit):
        raise PolicyError("invalid systemd unit")
    normalized = unit if unit.endswith(".service") else f"{unit}.service"
    if normalized in PROTECTED_UNITS or normalized.startswith("pve"):
        raise PolicyError("protected systemd unit")
    configured: set[str] = set()
    try:
        cfg = get_config()
        configured.update(str(value) for value in getattr(cfg.systemd, "allowed_services", []) or [])
        configured.update(str(value) for value in getattr(cfg, "systemd_allowed_services", []) or [])
    except Exception:  # noqa: BLE001 - missing config must narrow, not widen, the policy.
        configured = set()
    configured = {value if value.endswith(".service") else f"{value}.service" for value in configured if UNIT_RE.fullmatch(value)}
    if normalized in FIXED_SYSTEM_UNITS or normalized in configured or normalized == "webnas.service":
        return normalized
    if normalized.startswith("webnas-backend-") or UPDATE_UNIT_RE.fullmatch(normalized):
        return normalized
    raise PolicyError("systemd unit is not allowlisted")


def _safe_absolute_path(raw: str, *, roots: Sequence[Path]) -> Path:
    if not raw.startswith("/") or "\x00" in raw:
        raise PolicyError("path must be absolute")
    pure = PurePosixPath(raw)
    if ".." in pure.parts:
        raise PolicyError("path traversal is not allowed")
    candidate = Path(pure.as_posix()).resolve(strict=False)
    for root in roots:
        resolved_root = root.resolve(strict=False)
        if candidate == resolved_root or candidate.is_relative_to(resolved_root):
            return candidate
    raise PolicyError("path is outside privileged broker roots")


def _systemd(payload: dict[str, Any], runner: Runner) -> CommandResult:
    action = _text(payload, "action", limit=32)
    if action not in SYSTEMD_ACTIONS:
        raise PolicyError("unsupported systemd action")
    executable = _resolve_tool("systemctl")
    if action == "daemon-reload":
        if set(payload) != {"action"}:
            raise PolicyError("daemon-reload does not accept a unit")
        return runner([executable, "daemon-reload"], None, 60)
    unit = _unit_allowed(_text(payload, "unit", limit=128))
    if set(payload) - {"action", "unit", "properties"}:
        raise PolicyError("unsupported systemd parameters")
    if action == "show":
        properties = payload.get("properties") or []
        if not isinstance(properties, list) or len(properties) > 24 or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", item) for item in properties):
            raise PolicyError("invalid systemd properties")
        argv = [executable, "show", unit]
        if properties:
            argv.append(f"--property={','.join(properties)}")
        return runner(argv, None, 15)
    return runner([executable, action, unit], None, 120)


def _account(payload: dict[str, Any], runner: Runner) -> CommandResult:
    tool = _text(payload, "tool", limit=16)
    if tool not in ACCOUNT_TOOLS:
        raise PolicyError("unsupported account operation")
    args = payload.get("args") or []
    if not isinstance(args, list) or len(args) > 32 or any(not isinstance(item, str) or len(item) > 512 or "\x00" in item for item in args):
        raise PolicyError("invalid account arguments")
    stdin = payload.get("stdin")
    if stdin is not None and (not isinstance(stdin, str) or len(stdin) > 8192):
        raise PolicyError("invalid account stdin")
    if tool == "chpasswd":
        if args or not isinstance(stdin, str) or len(stdin.splitlines()) != 1 or ":" not in stdin:
            raise PolicyError("chpasswd requires one typed credential record")
        username, _password = stdin.rstrip("\n").split(":", 1)
        _name(username, "user")
    else:
        if stdin is not None:
            raise PolicyError("stdin is not accepted for this account operation")
        tokens = [item for item in args if item and not item.startswith("-")]
        if not tokens:
            raise PolicyError("account target is required")
        # Validate every token that syntactically represents a user/group. Options and
        # shell/gecos values are accepted only after the API has applied its stricter model.
        target = tokens[-1]
        if tool.startswith("group"):
            _name(target, "group")
        elif tool in {"useradd", "usermod", "userdel", "chage"}:
            _name(target, "user")
        elif tool == "gpasswd":
            if len(tokens) < 2:
                raise PolicyError("gpasswd requires user and group")
            _name(tokens[-2], "user")
            _name(tokens[-1], "group")
    forbidden = {"--root", "-R", "--prefix", "-P"}
    if any(item in forbidden for item in args):
        raise PolicyError("account root/prefix override is forbidden")
    return runner([_resolve_tool(tool), *args], stdin, 60)


def _ownership(payload: dict[str, Any], runner: Runner) -> CommandResult:
    action = _text(payload, "action", limit=16)
    fixed_roots = [Path("/home"), Path("/mnt/webnas")]
    roots = list(fixed_roots)
    try:
        cfg = get_config()
        roots.extend([Path(cfg.paths.data_dir), Path(cfg.paths.log_dir)])
    except Exception:  # noqa: BLE001 - an unavailable config must fail closed to fixed roots.
        roots = fixed_roots
    path = _safe_absolute_path(_text(payload, "path", limit=4096), roots=roots)
    if action == "mkdir":
        mode = payload.get("mode", 0o750)
        if not isinstance(mode, int) or mode < 0o700 or mode > 0o775:
            raise PolicyError("invalid directory mode")
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        return CommandResult(0, "", "")
    if action == "chown":
        owner = str(payload.get("owner") or "")
        group = str(payload.get("group") or "")
        if not owner and not group:
            raise PolicyError("owner or group is required")
        if owner:
            _name(owner, "user")
        if group:
            _name(group, "group")
        spec = f"{owner}:{group}" if group else owner
        return runner([_resolve_tool("chown"), spec, str(path)], None, 60)
    raise PolicyError("unsupported ownership action")


def _managed_file(payload: dict[str, Any]) -> CommandResult:
    target_key = _text(payload, "target", limit=64)
    target = MANAGED_FILES.get(target_key)
    if target is None:
        raise PolicyError("unknown managed file target")
    content = payload.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_MANAGED_FILE or "\x00" in content:
        raise PolicyError("invalid managed file content")
    mode = payload.get("mode", 0o600)
    if not isinstance(mode, int) or mode not in {0o600, 0o640, 0o644}:
        raise PolicyError("invalid managed file mode")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_raw = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return CommandResult(0, "", "")


def _power(payload: dict[str, Any], runner: Runner) -> CommandResult:
    action = _text(payload, "action", limit=16)
    if action not in {"poweroff", "reboot"} or set(payload) != {"action"}:
        raise PolicyError("unsupported power operation")
    return runner([_resolve_tool("systemctl"), action], None, 30)


def _package(payload: dict[str, Any], runner: Runner) -> CommandResult:
    tool = _text(payload, "tool", limit=16)
    if tool not in PACKAGE_TOOLS:
        raise PolicyError("unsupported package manager")
    args = payload.get("args") or []
    if not isinstance(args, list) or len(args) > 256 or any(not isinstance(item, str) or len(item) > 4096 or "\x00" in item for item in args):
        raise PolicyError("invalid package arguments")
    joined = " ".join(args)
    if any(token in joined for token in (";", "&&", "||", "`", "$(", "\n", "\r")):
        raise PolicyError("shell syntax is forbidden")
    subcommands = {
        "apt-get": {"update", "install", "remove", "purge"},
        "dnf": {"install", "reinstall", "remove"},
        "yum": {"install", "reinstall", "remove"},
        "zypper": {"install", "remove"},
        "pacman": {"-S", "-R"},
        "apk": {"add", "del", "fix"},
        "dpkg": {"--install"},
        "rpm": {"-Uvh"},
    }[tool]
    if not any(item in subcommands for item in args):
        raise PolicyError("unsupported package operation")
    for item in args:
        if item.startswith("-"):
            continue
        if item in subcommands:
            continue
        if item.startswith("Dir::Etc::"):
            if not item.startswith(("Dir::Etc::sourcelist=", "Dir::Etc::sourceparts=")) or "/run/webnas-package-center/" not in item:
                raise PolicyError("unsafe apt source override")
            continue
        if item.startswith("/"):
            _safe_absolute_path(item, roots=[Path("/run/webnas-package-center"), Path("/var/lib/webnas")])
            continue
        if not PACKAGE_RE.fullmatch(item):
            raise PolicyError("invalid package token")
    return runner([_resolve_tool(tool), *args], None, float(payload.get("timeout") or 1800))


def dispatch(request: BrokerRequest, *, runner: Runner | None = None) -> BrokerResponse:
    selected_runner = runner or _default_runner
    try:
        if request.operation == Operation.SYSTEMD:
            result = _systemd(request.payload, selected_runner)
        elif request.operation == Operation.ACCOUNT:
            result = _account(request.payload, selected_runner)
        elif request.operation == Operation.OWNERSHIP:
            result = _ownership(request.payload, selected_runner)
        elif request.operation == Operation.MANAGED_FILE:
            result = _managed_file(request.payload)
        elif request.operation == Operation.POWER:
            result = _power(request.payload, selected_runner)
        elif request.operation == Operation.PACKAGE:
            result = _package(request.payload, selected_runner)
        else:
            raise PolicyError("operation is not enabled")
    except PolicyError as error:
        return BrokerResponse(request_id=request.request_id, ok=False, exit_code=126, error_code="POLICY_DENIED", stderr=redact_text(error, limit=2000))
    except (OSError, subprocess.SubprocessError) as error:
        return BrokerResponse(request_id=request.request_id, ok=False, exit_code=127, error_code="EXECUTION_FAILED", stderr=redact_text(error, limit=2000))
    return BrokerResponse(
        request_id=request.request_id,
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        stdout=redact_text(result.stdout, limit=MAX_OUTPUT),
        stderr=redact_text(result.stderr, limit=MAX_OUTPUT),
        error_code=None if result.exit_code == 0 else "COMMAND_FAILED",
    )
