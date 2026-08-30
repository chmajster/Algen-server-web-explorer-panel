from __future__ import annotations

import ipaddress
import socket
import ssl
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ldap3 import NONE, Connection, Server, Tls


@dataclass(frozen=True, slots=True)
class LdapEndpoint:
    host: str
    port: int
    priority: int = 10
    source: str = "configured"

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"


_round_robin_lock = threading.Lock()
_round_robin_offset = 0


def normalize_host(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value if "://" in value else f"//{value}")
    if parsed.scheme and parsed.scheme not in {"ldap", "ldaps"}:
        raise ValueError("LDAP server URI must use ldap:// or ldaps://")
    host = parsed.hostname or ""
    if not host or "\x00" in host:
        raise ValueError("LDAP server hostname is invalid")
    return host.rstrip(".")


def assert_safe_ldap_target(host: str) -> None:
    """Block targets that are never valid directory endpoints.

    Private RFC1918, loopback and ULA destinations remain valid because LDAP is
    commonly an internal service. Link-local metadata ranges, multicast and
    unspecified addresses are rejected to reduce SSRF impact.
    """

    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ValueError("LDAP target address is not permitted")
    if str(address) in {"169.254.169.254", "100.100.100.200"}:
        raise ValueError("LDAP target address is not permitted")


def _srv_endpoints(domain: str, default_port: int) -> list[LdapEndpoint]:
    domain = domain.strip().rstrip(".")
    if not domain:
        return []
    name = domain if domain.startswith("_ldap.") or domain.startswith("_ldaps.") else f"_ldap._tcp.{domain}"
    try:
        import dns.resolver  # type: ignore[import-not-found]

        answers = dns.resolver.resolve(name, "SRV", lifetime=3.0)
    except Exception:
        return []
    result: list[LdapEndpoint] = []
    for answer in answers:
        try:
            target = str(answer.target).rstrip(".")
            priority = int(answer.priority)
            port = int(answer.port or default_port)
            if target:
                result.append(LdapEndpoint(target, port, priority, "dns-srv"))
        except (AttributeError, TypeError, ValueError):
            continue
    return result


def endpoints(settings: dict[str, Any]) -> list[LdapEndpoint]:
    result: list[LdapEndpoint] = []
    for item in settings.get("servers") or []:
        if not bool(item.get("enabled", True)):
            continue
        host = normalize_host(str(item.get("host") or ""))
        assert_safe_ldap_target(host)
        result.append(
            LdapEndpoint(
                host=host,
                port=int(item.get("port") or 389),
                priority=int(item.get("priority") or 10),
            )
        )
    result.extend(_srv_endpoints(str(settings.get("dns_srv_domain") or ""), 636 if settings.get("security_mode") == "ldaps" else 389))
    deduplicated: dict[tuple[str, int], LdapEndpoint] = {}
    for item in result:
        deduplicated.setdefault((item.host.casefold(), item.port), item)
    ordered = sorted(deduplicated.values(), key=lambda item: (item.priority, item.host.casefold(), item.port))
    if settings.get("failover_strategy") != "round_robin" or len(ordered) < 2:
        return ordered
    global _round_robin_offset
    with _round_robin_lock:
        offset = _round_robin_offset % len(ordered)
        _round_robin_offset += 1
    return ordered[offset:] + ordered[:offset]


def resolve_host(endpoint: LdapEndpoint) -> list[str]:
    addresses: list[str] = []
    for item in socket.getaddrinfo(endpoint.host, endpoint.port, type=socket.SOCK_STREAM):
        address = str(item[4][0]).split("%", 1)[0]
        if address not in addresses:
            assert_safe_ldap_target(address)
            addresses.append(address)
    return addresses


def tls_config(settings: dict[str, Any]) -> Tls:
    return Tls(
        validate=ssl.CERT_REQUIRED if bool(settings.get("verify_tls", True)) else ssl.CERT_NONE,
        ca_certs_data=str(settings.get("ca_certificate") or "") or None,
    )


def connect(
    settings: dict[str, Any],
    endpoint: LdapEndpoint,
    *,
    user: str,
    password: str,
    get_info: Any = NONE,
) -> Connection:
    server = Server(
        endpoint.host,
        port=endpoint.port,
        use_ssl=settings.get("security_mode") == "ldaps",
        tls=tls_config(settings),
        connect_timeout=float(settings.get("connect_timeout") or 5.0),
        get_info=get_info,
    )
    connection = Connection(
        server,
        user=user,
        password=password,
        receive_timeout=float(settings.get("operation_timeout") or 10.0),
        raise_exceptions=True,
    )
    connection.open()
    if settings.get("security_mode") == "starttls":
        connection.start_tls()
    connection.bind()
    return connection
