"""Central encrypted secret store for WebNAS."""

from .service import SecretsManagerService, service

__all__ = ["SecretsManagerService", "service"]
