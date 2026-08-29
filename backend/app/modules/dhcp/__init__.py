"""Native DHCP Manager domain."""

from .models import DhcpBackend, DhcpConfiguration, DhcpReservation, DhcpSubnet
from .broker import BrokerDhcpService
from . import service as _service_module

# Keep the historical import/factory contract while replacing only the host-mutation
# implementation. The subclass is behavior-compatible unless broker mode is required.
_service_module.DhcpService = BrokerDhcpService

__all__ = ["DhcpBackend", "DhcpConfiguration", "DhcpReservation", "DhcpSubnet"]
