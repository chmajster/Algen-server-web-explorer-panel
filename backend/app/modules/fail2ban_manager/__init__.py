"""Safe Fail2Ban administration module."""

from .service import Fail2BanService, service

__all__ = ["Fail2BanService", "service"]
