from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.redaction import redact_text

from .protocol import BrokerRequest, BrokerResponse, Operation

_SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
_SAFE_ENV = {"PATH": _SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root"}
_MAX_OUTPUT = 256 * 1024
_MAX_CONFIG = 512 * 1024
_NTP_TARGETS = {
    "chrony_debian": Path("/etc/chrony/chrony.conf"),
    "chrony_rhel": Path("/etc/chrony.conf"),
    "chrony_debian_webnas": Path("/etc/chrony/conf.d/webnas.conf"),
    "chrony_rhel_webnas": Path("/etc/chrony.d/webnas.conf"),
    "timesyncd": Path("/etc/systemd/timesyncd.conf"),
    "ntpd": Path("/etc/ntp.conf"),
}
_NTP_UNITS = {"chrony", "chronyd", "systemd-timesyncd", "ntp", "ntpd"}
_SERVICE_ACTIONS = {"start", "stop", "restart", "reload", "enable", "disable"}
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")
_TABLE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_IP_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,128}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_TIMEZONE_RE = re.compile(r"^(?:UTC|[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+)$")


class InfrastructurePolicyError(ValueError):
    pass


def _tool(name: str) -> str:
    if "/" in name or name.startswith("."):
        raise InfrastructurePolicyError("executable paths are not accepted")
    resolved = shutil.which(name, path=_SAFE_PATH)
    if not resolved:
        raise InfrastructurePolicyError(f"required privileged tool is unavailable: {name}")
    candidate = Path(resolved).resolve(strict=False)
    if candidate.name != name or str(candidate.parent) not in {"/usr/sbin", "/usr/bin", "/sbin", "/bin"}:
        raise InfrastructurePolicyError("privileged tool resolved outside the fixed system path")
    return str(candidate)


def _run(argv: list[str], timeout: float = 60) -> tuple[int, str, str]:
    completed = subprocess.run(  # nosec B603 - binary and argv are reconstructed/validated below.
        argv, capture_output=True, text=True, timeout=timeout, check=False, shell=False, env=_SAFE_ENV
    )
    return completed.returncode, completed.stdout[-_MAX_OUTPUT:], completed.stderr[-_MAX_OUTPUT:]


def _response(request: BrokerRequest, code: int, stdout: str = "", stderr: str = "", error_code: str | None = None) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=code == 0,
        exit_code=code,
        stdout=redact_text(stdout, limit=_MAX_OUTPUT),
        stderr=redact_text(stderr, limit=_MAX_OUTPUT),
        error_code=error_code,
    )


def _atomic_write(target: Path, content: str) -> None:
    if len(content.encode("utf-8")) > _MAX_CONFIG or "\x00" in content:
        raise InfrastructurePolicyError("invalid NTP configuration content")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_raw = tempfile.mkstemp(prefix=f".{target.name}.webnas-", dir=target.parent)
    temporary = Path(temporary_raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _firewall_status() -> dict[str, Any]:
    if shutil.which("firewall-cmd", path=_SAFE_PATH):
        state, _stdout, _stderr = _run([_tool("firewall-cmd"), "--state"], 10)
        if state == 0:
            code, stdout, _stderr = _run([_tool("firewall-cmd"), "--query-port=123/udp"], 10)
            return {"backend": "firewalld", "status": "open" if code == 0 and stdout.strip() == "yes" else "blocked", "managed_by_webnas": False}
    if shutil.which("ufw", path=_SAFE_PATH):
        code, stdout, _stderr = _run([_tool("ufw"), "status"], 10)
        if code == 0:
            open_port = any("123/udp" in line and "ALLOW" in line for line in stdout.splitlines())
            return {"backend": "ufw", "status": "open" if open_port else "blocked", "managed_by_webnas": "WebNAS NTP" in stdout}
    if shutil.which("nft", path=_SAFE_PATH):
        code, stdout, _stderr = _run([_tool("nft"), "list", "ruleset"], 15)
        if code == 0:
            open_port = bool(re.search(r"udp\s+dport\s+123\b.*\baccept\b", stdout))
            return {"backend": "nftables", "status": "open" if open_port else "blocked", "managed_by_webnas": "webnas-ntp" in stdout}
    return {"backend": "none", "status": "unknown", "managed_by_webnas": False}


def _ntp(request: BrokerRequest) -> BrokerResponse:
    payload = request.payload
    action = payload.get("action")
    if action == "write_config":
        if set(payload) != {"action", "target", "content"}:
            raise InfrastructurePolicyError("unsupported NTP write parameters")
        target = _NTP_TARGETS.get(str(payload.get("target") or ""))
        content = payload.get("content")
        if target is None or not isinstance(content, str):
            raise InfrastructurePolicyError("invalid NTP managed file")
        _atomic_write(target, content)
        return _response(request, 0)
    if action == "service":
        if set(payload) != {"action", "service_action", "unit"}:
            raise InfrastructurePolicyError("unsupported NTP service parameters")
        service_action, unit = str(payload.get("service_action") or ""), str(payload.get("unit") or "")
        if service_action not in _SERVICE_ACTIONS or unit not in _NTP_UNITS:
            raise InfrastructurePolicyError("NTP service action is not allowlisted")
        code, stdout, stderr = _run([_tool("systemctl"), service_action, unit], 120)
        return _response(request, code, stdout, stderr, "NTP_SERVICE_FAILED" if code else None)
    if action == "resync":
        backend = str(payload.get("backend") or "")
        if set(payload) != {"action", "backend", "unit"}:
            raise InfrastructurePolicyError("unsupported NTP resync parameters")
        unit = str(payload.get("unit") or "")
        if backend == "chrony":
            code, stdout, stderr = _run([_tool("chronyc"), "makestep"], 60)
        elif backend in {"systemd-timesyncd", "ntpd"} and unit in _NTP_UNITS:
            code, stdout, stderr = _run([_tool("systemctl"), "restart", unit], 120)
        else:
            raise InfrastructurePolicyError("NTP resync backend is not allowlisted")
        return _response(request, code, stdout, stderr, "NTP_RESYNC_FAILED" if code else None)
    if action == "timezone":
        if set(payload) != {"action", "timezone"}:
            raise InfrastructurePolicyError("unsupported NTP timezone parameters")
        timezone = str(payload.get("timezone") or "")
        if not _TIMEZONE_RE.fullmatch(timezone) or ".." in timezone:
            raise InfrastructurePolicyError("invalid timezone")
        zone_root = Path("/usr/share/zoneinfo").resolve(strict=False)
        zone_path = (zone_root / timezone).resolve(strict=False)
        if timezone != "UTC" and (not zone_path.is_relative_to(zone_root) or not zone_path.is_file()):
            raise InfrastructurePolicyError("timezone is not installed")
        code, stdout, stderr = _run([_tool("timedatectl"), "set-timezone", timezone], 30)
        return _response(request, code, stdout, stderr, "NTP_TIMEZONE_FAILED" if code else None)
    if action == "firewall_status":
        if set(payload) != {"action"}:
            raise InfrastructurePolicyError("unsupported NTP firewall status parameters")
        return _response(request, 0, json.dumps(_firewall_status(), separators=(",", ":")))
    if action == "firewall_open":
        if set(payload) != {"action"}:
            raise InfrastructurePolicyError("unsupported NTP firewall parameters")
        status = _firewall_status()
        if status["status"] == "open":
            return _response(request, 0, json.dumps(status, separators=(",", ":")))
        if status["backend"] == "firewalld":
            code, stdout, stderr = _run([_tool("firewall-cmd"), "--permanent", "--add-port=123/udp"], 30)
            if code == 0:
                code, reload_out, reload_err = _run([_tool("firewall-cmd"), "--reload"], 30)
                stdout += reload_out
                stderr += reload_err
            return _response(request, code, stdout, stderr, "NTP_FIREWALL_FAILED" if code else None)
        if status["backend"] == "ufw":
            code, stdout, stderr = _run([_tool("ufw"), "allow", "123/udp", "comment", "WebNAS NTP"], 30)
            return _response(request, code, stdout, stderr, "NTP_FIREWALL_FAILED" if code else None)
        if status["backend"] == "nftables":
            return _response(
                request,
                2,
                stderr="nftables ruleset is unmanaged; WebNAS will not modify an unknown chain automatically",
                error_code="NTP_FIREWALL_MANUAL_REQUIRED",
            )
        return _response(request, 2, stderr="no supported firewall backend detected", error_code="NTP_FIREWALL_UNAVAILABLE")
    raise InfrastructurePolicyError("unsupported NTP operation")


def _validate_ip_args(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not 4 <= len(raw) <= 40 or any(not isinstance(item, str) for item in raw):
        raise InfrastructurePolicyError("invalid iproute2 arguments")
    args = list(raw)
    if args[0] not in {"-4", "-6"} or args[1] not in {"route", "rule"}:
        raise InfrastructurePolicyError("unsupported iproute2 family/object")
    if args[1] == "route" and args[2] not in {"replace", "delete"}:
        raise InfrastructurePolicyError("unsupported route mutation")
    if args[1] == "rule" and args[2] not in {"add", "delete"}:
        raise InfrastructurePolicyError("unsupported policy rule mutation")
    for token in args[3:]:
        if token.startswith("-") or not _SAFE_IP_TOKEN_RE.fullmatch(token):
            raise InfrastructurePolicyError("unsafe iproute2 token")
    return args


def _routing(request: BrokerRequest) -> BrokerResponse:
    payload = request.payload
    action = payload.get("action")
    if action == "ip":
        if set(payload) != {"action", "args"}:
            raise InfrastructurePolicyError("unsupported routing parameters")
        args = _validate_ip_args(payload.get("args"))
        code, stdout, stderr = _run([_tool("ip"), *args], 60)
        return _response(request, code, stdout, stderr, "ROUTING_COMMAND_FAILED" if code else None)
    if action in {"nmcli_add_route", "nmcli_remove_route", "nmcli_set_routes"}:
        allowed = {"action", "connection", "family", "routes"}
        if set(payload) != allowed:
            raise InfrastructurePolicyError("unsupported NetworkManager parameters")
        connection, family, routes = payload.get("connection"), payload.get("family"), payload.get("routes")
        if not isinstance(connection, str) or not connection or len(connection) > 256 or "\x00" in connection:
            raise InfrastructurePolicyError("invalid NetworkManager connection")
        if family not in {"ipv4", "ipv6"} or not isinstance(routes, str) or len(routes) > 8192 or "\x00" in routes:
            raise InfrastructurePolicyError("invalid NetworkManager route data")
        property_name = f"{family}.routes"
        if action == "nmcli_add_route":
            property_name = f"+{property_name}"
        elif action == "nmcli_remove_route":
            property_name = f"-{property_name}"
        code, stdout, stderr = _run([_tool("nmcli"), "connection", "modify", connection, property_name, routes], 60)
        return _response(request, code, stdout, stderr, "NETWORKMANAGER_ROUTE_FAILED" if code else None)
    raise InfrastructurePolicyError("unsupported routing operation")


def _session(request: BrokerRequest) -> BrokerResponse:
    payload = request.payload
    if set(payload) != {"action", "session_id"} or payload.get("action") != "terminate":
        raise InfrastructurePolicyError("unsupported session operation")
    session_id = str(payload.get("session_id") or "")
    if not _SESSION_RE.fullmatch(session_id):
        raise InfrastructurePolicyError("invalid login session id")
    code, stdout, stderr = _run([_tool("loginctl"), "terminate-session", session_id], 30)
    return _response(request, code, stdout, stderr, "SESSION_TERMINATE_FAILED" if code else None)


def dispatch_infrastructure(request: BrokerRequest) -> BrokerResponse:
    try:
        if request.operation == Operation.NTP:
            return _ntp(request)
        if request.operation == Operation.ROUTING:
            return _routing(request)
        if request.operation == Operation.SESSION:
            return _session(request)
        raise InfrastructurePolicyError("unsupported infrastructure operation")
    except InfrastructurePolicyError as error:
        return _response(request, 126, stderr=str(error), error_code="POLICY_DENIED")
    except subprocess.TimeoutExpired:
        return _response(request, 124, stderr="privileged operation timed out", error_code="TIMEOUT")
    except OSError as error:
        return _response(request, 126, stderr=type(error).__name__, error_code="OS_ERROR")
