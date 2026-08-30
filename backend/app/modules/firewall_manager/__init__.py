"""Local Linux firewall management module."""

from .service import FirewallService, service

__all__ = ["FirewallService", "service"]
