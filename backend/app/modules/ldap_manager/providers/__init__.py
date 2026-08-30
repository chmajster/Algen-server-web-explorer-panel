from __future__ import annotations

from typing import Any

from .active_directory import ActiveDirectoryProvider
from .base import LdapDirectoryProvider, ProviderOperationError, UnsupportedDirectoryOperation
from .freeipa import FreeIpaProvider
from .generic import GenericLdapProvider
from .openldap import OpenLdapProvider


def provider_for(config: dict[str, Any]) -> LdapDirectoryProvider:
    directory_type = str(config.get("directory_type") or "generic")
    if directory_type == "active_directory":
        return ActiveDirectoryProvider(config)
    if directory_type == "freeipa":
        return FreeIpaProvider(config)
    if directory_type == "ldap":
        return OpenLdapProvider(config)
    return GenericLdapProvider(config)


__all__ = [
    "ActiveDirectoryProvider",
    "FreeIpaProvider",
    "GenericLdapProvider",
    "LdapDirectoryProvider",
    "OpenLdapProvider",
    "ProviderOperationError",
    "UnsupportedDirectoryOperation",
    "provider_for",
]
