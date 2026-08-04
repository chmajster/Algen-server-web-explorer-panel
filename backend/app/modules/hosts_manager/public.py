"""Supported cross-module API for Hosts Manager."""

from .models import CredentialInput, EnrollmentTokenInput, GroupInput, HostInput
from .service import (
    HostCapabilityProvider,
    ManagedGroupConflictError,
    ManagedGroupProtectedError,
    registry,
)

__all__ = [
    "CredentialInput", "EnrollmentTokenInput", "GroupInput", "HostCapabilityProvider",
    "HostInput", "ManagedGroupConflictError", "ManagedGroupProtectedError", "registry",
]
