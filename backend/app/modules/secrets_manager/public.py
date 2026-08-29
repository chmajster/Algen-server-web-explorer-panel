"""Supported cross-module API for Secrets Manager."""

from __future__ import annotations

from typing import Any

from .service import SecretsManagerService, service


def secret_metadata(secret_id: str) -> dict[str, Any] | None:
    return service().secret(secret_id)


def shared_secret_metadata(module_id: str) -> list[dict[str, Any]]:
    """Return metadata only for active secrets explicitly shared with a module."""
    return [
        item
        for item in service().secrets()
        if module_id in item.get("shared_with", [])
    ]


def verified_secret(secret_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
    return service().verified_secret(secret_id, module_id=module_id, purpose=purpose)


__all__ = [
    "SecretsManagerService",
    "secret_metadata",
    "service",
    "shared_secret_metadata",
    "verified_secret",
]
