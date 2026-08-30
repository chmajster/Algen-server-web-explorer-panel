from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn, parse_dn


ATTRIBUTE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.-]{0,127}$")
PROTECTED_ATTRIBUTES = {
    "userpassword",
    "unicodepwd",
    "pwdlastset",
    "lockouttime",
    "useraccountcontrol",
    "memberof",
    "objectguid",
    "objectsid",
    "entryuuid",
    "ipauniqueid",
}


def normalize_host(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value if "://" in value else f"//{value}")
    if parsed.scheme and parsed.scheme not in {"ldap", "ldaps"}:
        raise ValueError("LDAP server URI must use ldap:// or ldaps://")
    host = parsed.hostname or ""
    if not host or "\x00" in host:
        raise ValueError("Invalid LDAP server hostname")
    return host.rstrip(".")


def assert_safe_target(host: str) -> None:
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ValueError("LDAP target address is not permitted")
    if str(address) in {"169.254.169.254", "100.100.100.200"}:
        raise ValueError("LDAP target address is not permitted")


def validate_dn(dn: str) -> str:
    value = dn.strip()
    if not value or "\x00" in value:
        raise ValueError("LDAP DN is invalid")
    try:
        parse_dn(value, escape=True, strip=True)
    except Exception as error:
        raise ValueError("LDAP DN is invalid") from error
    return value


def validate_attribute(name: str) -> str:
    value = name.strip()
    if not ATTRIBUTE_RE.fullmatch(value):
        raise ValueError("LDAP attribute name is invalid")
    return value


def sanitize_attributes(attributes: dict[str, Any], *, allow_protected: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_name, value in attributes.items():
        name = validate_attribute(str(raw_name))
        if not allow_protected and name.casefold() in PROTECTED_ATTRIBUTES:
            raise ValueError(f"LDAP attribute {name} must be changed through a dedicated operation")
        if isinstance(value, dict):
            raise ValueError(f"Nested values are not allowed for LDAP attribute {name}")
        if isinstance(value, list) and len(value) > 10000:
            raise ValueError(f"Too many values for LDAP attribute {name}")
        result[name] = value
    return result


def escaped_filter_value(value: str) -> str:
    return escape_filter_chars(value)


def rdn(attribute: str, value: str) -> str:
    return f"{validate_attribute(attribute)}={escape_rdn(value)}"
