"""Supported cross-module API for Secrets Manager."""

from __future__ import annotations

from typing import Any

from .service import SecretsManagerService, service


def secret_metadata(secret_id: str) -> dict[str, Any] | None:
    return service().secret(secret_id)


def verified_secret(secret_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
    return service().verified_secret(secret_id, module_id=module_id, purpose=purpose)


__all__ = ["SecretsManagerService", "secret_metadata", "service", "verified_secret"]
