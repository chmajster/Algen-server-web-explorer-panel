"""Proxmox Manager integration backed by the central Hosts Manager registry."""

from .service import ProxmoxApiClient, ProxmoxApiError, ProxmoxManagerService, service

__all__ = ["ProxmoxApiClient", "ProxmoxApiError", "ProxmoxManagerService", "service"]
