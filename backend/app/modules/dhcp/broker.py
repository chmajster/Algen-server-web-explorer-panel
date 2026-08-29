from __future__ import annotations

import subprocess
from pathlib import Path

from ...privileged_broker.runtime import broker_required, managed_file_write, systemd_action
from .models import DhcpBackend
from .service import DhcpService
from .system import DhcpSystem


_MANAGED_TARGETS = {
    Path("/etc/kea/kea-dhcp4.conf"): "dhcp_kea",
    Path("/etc/dhcp/dhcpd.conf"): "dhcp_isc",
    Path("/etc/default/isc-dhcp-server"): "dhcp_isc_interfaces",
}


class BrokerDhcpSystem(DhcpSystem):
    def service_action(self, backend: DhcpBackend, action: str) -> subprocess.CompletedProcess[str]:
        if not broker_required():
            return super().service_action(backend, action)
        if action not in {"start", "stop", "restart", "reload", "enable", "disable"}:
            raise ValueError("unsupported DHCP service action")
        service = self.selected_service(backend)
        if not service:
            raise RuntimeError("DHCP systemd service is unavailable")
        return systemd_action(action, service, actor="dhcp-manager")


class BrokerDhcpService(DhcpService):
    def __init__(self, root: Path | None = None, *, system: DhcpSystem | None = None) -> None:
        super().__init__(root, system=system or BrokerDhcpSystem())

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, default_mode: int = 0o644) -> None:
        target = _MANAGED_TARGETS.get(path)
        if broker_required() and target is not None:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RuntimeError("DHCP managed configuration must be UTF-8 text") from error
            mode = (path.stat().st_mode & 0o777) if path.exists() else default_mode
            managed_file_write(target, text, actor="dhcp-manager", mode=mode)
            return
        DhcpService._atomic_write(path, content, default_mode=default_mode)
