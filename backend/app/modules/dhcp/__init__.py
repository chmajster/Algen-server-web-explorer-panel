"""Native DHCP Manager domain."""

from .models import DhcpBackend, DhcpConfiguration, DhcpReservation, DhcpSubnet
from .broker import BrokerDhcpService
from . import service as _service_module

# Keep the historical import/factory contract while replacing only the host-mutation
# implementation. Using setattr avoids rebinding a statically-declared class symbol;
# the broker implementation is a strict DhcpService subclass and preserves the API.
setattr(_service_module, "DhcpService", BrokerDhcpService)

__all__ = ["DhcpBackend", "DhcpConfiguration", "DhcpReservation", "DhcpSubnet"]
