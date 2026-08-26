"""Supported cross-module provider integration helpers."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

_DNS_PROVIDERS = {"pihole", "adguard-home"}
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def upsert_dns_record(provider_id: str, hostname: str, address: str) -> dict[str, Any]:
    """Create or update one A-record through a controlled DNS provider capability."""
    if provider_id not in _DNS_PROVIDERS:
        raise ValueError("unsupported DNS provider")
    hostname = hostname.rstrip(".").lower()
    if not _HOSTNAME_RE.fullmatch(hostname):
        raise ValueError("invalid DNS hostname")
    parsed = ipaddress.ip_address(address)
    if parsed.version != 4 or parsed.is_multicast or parsed.is_unspecified:
        raise ValueError("a usable IPv4 address is required")
    from . import get_provider

    provider = get_provider(provider_id)
    operation = getattr(provider, "upsert_dns_record", None)
    if not callable(operation):
        raise RuntimeError("DNS provider does not support managed record updates")
    result = operation(hostname, str(parsed))
    if not isinstance(result, dict):
        raise RuntimeError("DNS provider returned an invalid record update result")
    return result


__all__ = ["upsert_dns_record"]
