"""Supported cross-module API for Hosts Manager."""

from __future__ import annotations

import json
from typing import Any

from .models import CredentialInput, EnrollmentTokenInput, GroupInput, HostInput
from .service import (
    HostCapabilityProvider,
    ManagedGroupConflictError,
    ManagedGroupProtectedError,
    registry,
)


def provider_hosts(provider: str, instance_id: str = "") -> list[dict[str, Any]]:
    """Return every host owned by a provider without the public list pagination cap."""
    service = registry()
    with service.connect() as connection:
        rows = connection.execute("SELECT id,variables_json FROM hosts ORDER BY name COLLATE NOCASE").fetchall()
    host_ids: list[str] = []
    for row in rows:
        try:
            variables = json.loads(str(row["variables_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(variables, dict) or variables.get("algen_provider") != provider:
            continue
        if instance_id and str(variables.get("algen_provider_instance_id") or "") != instance_id:
            continue
        host_ids.append(str(row["id"]))
    result: list[dict[str, Any]] = []
    for host_id in host_ids:
        host = service.host(host_id)
        if host:
            result.append(host)
    return result


def host_names() -> set[str]:
    """Return all canonical host names, normalized for uniqueness checks."""
    with registry().connect() as connection:
        rows = connection.execute("SELECT name FROM hosts").fetchall()
    return {str(row["name"]).casefold() for row in rows if row["name"]}


__all__ = [
    "CredentialInput", "EnrollmentTokenInput", "GroupInput", "HostCapabilityProvider",
    "HostInput", "ManagedGroupConflictError", "ManagedGroupProtectedError", "host_names",
    "provider_hosts", "registry",
]
