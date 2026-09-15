"""Proxmox Manager integration backed by the central Hosts Manager registry."""

from . import service as _service_module
from .secure_client import HardenedProxmoxApiClient

setattr(_service_module, "ProxmoxApiClient", HardenedProxmoxApiClient)

ProxmoxApiClient = HardenedProxmoxApiClient
ProxmoxApiError = _service_module.ProxmoxApiError
ProxmoxManagerService = _service_module.ProxmoxManagerService
service = _service_module.service

__all__ = ["ProxmoxApiClient", "ProxmoxApiError", "ProxmoxManagerService", "service"]
