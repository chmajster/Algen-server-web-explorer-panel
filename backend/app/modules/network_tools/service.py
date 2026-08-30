from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import ssl
import subprocess
import threading
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ...activity import ActivityCategory, record_activity
from ...network_diagnostics import dns_configuration, network_overview, routing_snapshot, test_connectivity
from ..firewall_manager import service as firewall_service
from .models import DnsLookupRequest, HttpTestRequest


MAX_OUTPUT = 256 * 1024
_MAX_CONCURRENT = 4
_RATE_WINDOW = 60.0
_RATE_LIMIT = 30


class NetworkToolError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class NetworkToolsService:
    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(_MAX_CONCURRENT)
        self._rate_lock = threading.Lock()
        self._rates: dict[str, list[float]] = {}

    def admit(self, actor: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            previous = [item for item in self._rates.get(actor, []) if now - item < _RATE_WINDOW]
            if len(previous) >= _RATE_LIMIT:
                raise NetworkToolError("network diagnostic rate limit exceeded")
            previous.append(now)
            self._rates[actor] = previous

    def execute(self, actor: str, action: str, callback):  # type: ignore[no-untyped-def]
        self.admit(actor)
        if not self._slots.acquire(timeout=1):
            raise NetworkToolError("too many concurrent network diagnostics")
        try:
            result = callback()
            record_activity(ActivityCategory.module, "network.diagnostic.executed", actor, target=action, details={"tool": action}, source="network-tools")
            return result
        finally:
            self._slots.release()

    @staticmethod
    def connectivity(kind: str, target: str, port: int | None = None) -> dict[str, Any]:
        return test_connectivity(kind, target, port)

    @staticmethod
    def dns_lookup(payload: DnsLookupRequest) -> dict[str, Any]:
        tool = shutil.which("dig")
        started = time.perf_counter()
        if not tool:
            if payload.record_type in {"A", "AAAA"}:
                family = socket.AF_INET if payload.record_type == "A" else socket.AF_INET6
                try:
                    values = sorted({str(item[4][0]) for item in socket.getaddrinfo(payload.hostname, None, family, socket.SOCK_STREAM)})
                except socket.gaierror:
                    values = []
                return {"hostname": payload.hostname, "record_type": payload.record_type, "server": payload.server or None, "answers": values, "success": bool(values), "latency_ms": round((time.perf_counter() - started) * 1000, 2), "backend": "socket"}
            raise NetworkToolError("dig is required for this DNS record type")
        args = [tool, "+time=3", "+tries=1", "+short"]
        if payload.server:
            args.append(f"@{payload.server}")
        try:
            ptr_address = str(ipaddress.ip_address(payload.hostname)) if payload.record_type == "PTR" else None
        except ValueError:
            ptr_address = None
        args += ["-x", ptr_address] if ptr_address else [payload.hostname, payload.record_type]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False, shell=False)  # nosec B603
        except (OSError, subprocess.SubprocessError) as error:
            raise NetworkToolError(type(error).__name__) from error
        answers = [line.strip()[:2048] for line in result.stdout.splitlines() if line.strip()][:200]
        return {"hostname": payload.hostname, "record_type": payload.record_type, "server": payload.server or None, "answers": answers, "success": result.returncode == 0 and bool(answers), "latency_ms": round((time.perf_counter() - started) * 1000, 2), "backend": "dig", "error": (result.stderr or "")[:1000] if result.returncode else None}

    @staticmethod
    def reverse_dns(address: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            hostname, aliases, addresses = socket.gethostbyaddr(address)
            return {"address": address, "success": True, "hostname": hostname, "aliases": aliases[:20], "addresses": addresses[:20], "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        except (OSError, socket.herror):
            return {"address": address, "success": False, "hostname": None, "aliases": [], "addresses": [], "latency_ms": round((time.perf_counter() - started) * 1000, 2)}

    @staticmethod
    def route_lookup(target: str) -> dict[str, Any]:
        tool = shutil.which("ip")
        if not tool:
            raise NetworkToolError("iproute2 is unavailable")
        try:
            result = subprocess.run([tool, "-j", "route", "get", target], capture_output=True, text=True, timeout=5, check=False, shell=False)  # nosec B603
        except (OSError, subprocess.SubprocessError) as error:
            raise NetworkToolError(type(error).__name__) from error
        if result.returncode:
            raise NetworkToolError((result.stderr or "route lookup failed")[:1000])
        try:
            values = json.loads(result.stdout or "[]")
        except ValueError as error:
            raise NetworkToolError("invalid iproute2 response") from error
        return {"target": target, "routes": values[:20] if isinstance(values, list) else []}

    @staticmethod
    def neighbors() -> dict[str, Any]:
        tool = shutil.which("ip")
        if not tool:
            return {"items": [], "warning": "iproute2 is unavailable"}
        try:
            result = subprocess.run([tool, "-j", "neigh", "show"], capture_output=True, text=True, timeout=5, check=False, shell=False)  # nosec B603
        except (OSError, subprocess.SubprocessError):
            return {"items": [], "warning": "neighbor table unavailable"}
        try:
            values = json.loads(result.stdout or "[]")
        except ValueError:
            values = []
        return {"items": values[:1000] if isinstance(values, list) else [], "warning": None}

    @staticmethod
    def connections() -> dict[str, Any]:
        tool = shutil.which("ss")
        if not tool:
            return {"items": [], "warning": "ss is unavailable"}
        try:
            result = subprocess.run([tool, "-H", "-tunap"], capture_output=True, text=True, timeout=8, check=False, shell=False)  # nosec B603
        except (OSError, subprocess.SubprocessError):
            return {"items": [], "warning": "connection table unavailable"}
        items: list[dict[str, str]] = []
        for line in result.stdout.splitlines()[:2000]:
            parts = line.split(None, 6)
            if len(parts) < 6:
                continue
            items.append({"protocol": parts[0], "state": parts[1], "local": parts[4][:256], "peer": parts[5][:256], "process": parts[6][:300] if len(parts) > 6 else ""})
        return {"items": items, "warning": None, "truncated": len(result.stdout.splitlines()) > 2000}

    @staticmethod
    def _resolve(hostname: str, port: int) -> tuple[list[str], float]:
        started = time.perf_counter()
        try:
            addresses = list(dict.fromkeys(str(item[4][0]) for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)))[:16]
        except socket.gaierror:
            addresses = []
        return addresses, round((time.perf_counter() - started) * 1000, 2)

    @staticmethod
    def _tcp_tls(hostname: str, port: int, use_tls: bool) -> tuple[bool, float | None, float | None, dict[str, Any] | None, str | None]:
        started = time.perf_counter()
        try:
            raw = socket.create_connection((hostname, port), timeout=5)
        except OSError as error:
            return False, round((time.perf_counter() - started) * 1000, 2), None, None, type(error).__name__
        tcp_ms = round((time.perf_counter() - started) * 1000, 2)
        if not use_tls:
            raw.close()
            return True, tcp_ms, None, None, None
        tls_started = time.perf_counter()
        try:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            wrapped = context.wrap_socket(raw, server_hostname=hostname)
            certificate = wrapped.getpeercert() or {}
            tls_ms = round((time.perf_counter() - tls_started) * 1000, 2)
            summary = {"subject": certificate.get("subject"), "issuer": certificate.get("issuer"), "not_before": certificate.get("notBefore"), "not_after": certificate.get("notAfter"), "serial_number": certificate.get("serialNumber")}
            wrapped.close()
            return True, tcp_ms, tls_ms, summary, None
        except (OSError, ssl.SSLError) as error:
            raw.close()
            return False, tcp_ms, round((time.perf_counter() - tls_started) * 1000, 2), None, type(error).__name__

    @staticmethod
    def http_test(payload: HttpTestRequest) -> dict[str, Any]:
        current = payload.url
        redirects: list[dict[str, Any]] = []
        opener = build_opener(NoRedirect())
        total_started = time.perf_counter()
        first = urlparse(current)
        port = first.port or (443 if first.scheme == "https" else 80)
        addresses, dns_ms = NetworkToolsService._resolve(first.hostname or "", port)
        connected, tcp_ms, tls_ms, certificate, connect_error = NetworkToolsService._tcp_tls(first.hostname or "", port, first.scheme == "https")
        status: int | None = None
        error: str | None = connect_error
        if connected:
            for _ in range(6):
                try:
                    response = opener.open(Request(current, method="HEAD", headers={"User-Agent": "WebNAS-Network-Tools/1"}), timeout=7)
                    status = response.status
                    response.close()
                    break
                except Exception as http_error:  # urllib represents 3xx and HTTP errors as exceptions with code/headers.
                    code = getattr(http_error, "code", None)
                    headers = getattr(http_error, "headers", None)
                    location = headers.get("Location") if headers is not None else None
                    if isinstance(code, int) and 300 <= code < 400 and location:
                        next_url = urljoin(current, str(location))
                        parsed = urlparse(next_url)
                        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                            error = "invalid redirect target"
                            break
                        redirects.append({"status": code, "url": current, "location": next_url})
                        current = next_url
                        continue
                    if isinstance(code, int):
                        status = code
                        error = None
                    else:
                        error = type(http_error).__name__
                    break
        return {"url": payload.url, "resolved_ip": addresses[0] if addresses else None, "resolved_ips": addresses, "dns_resolution_ms": dns_ms, "tcp_connected": connected, "tcp_connect_ms": tcp_ms, "tls_handshake_ms": tls_ms, "certificate": certificate, "http_status": status, "response_time_ms": round((time.perf_counter() - total_started) * 1000, 2), "redirect_chain": redirects, "final_url": current, "error": error}

    @staticmethod
    def overview() -> dict[str, Any]:
        return {"interfaces": network_overview(), "dns": dns_configuration(), "routes": routing_snapshot(), "neighbors": NetworkToolsService.neighbors(), "listening_ports": firewall_service().listening_ports()}


@lru_cache
def service() -> NetworkToolsService:
    return NetworkToolsService()
