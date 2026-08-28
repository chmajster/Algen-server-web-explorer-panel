from __future__ import annotations

import asyncio
import contextlib
import os
import socket

import uvicorn

from .config import get_config
from .main import app


def _systemd_notify(message: str) -> None:
    """Send a best-effort sd_notify datagram without adding a runtime dependency."""

    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    address = f"\0{notify_socket[1:]}" if notify_socket.startswith("@") else notify_socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.connect(address)
            client.sendall(message.encode("utf-8"))
    except OSError:
        # A missing/stale notify socket must never prevent WebNAS from starting.
        return


def _watchdog_interval() -> float | None:
    """Return half of systemd's watchdog interval, as recommended by sd_notify."""

    raw = os.environ.get("WATCHDOG_USEC", "")
    try:
        watchdog_usec = int(raw)
    except ValueError:
        return None
    if watchdog_usec <= 0:
        return None
    return max(1.0, watchdog_usec / 2_000_000)


class WebNasServer(uvicorn.Server):
    """Uvicorn server integrated with systemd readiness and watchdog supervision."""

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if not self.should_exit:
            _systemd_notify("READY=1\nSTATUS=WebNAS backend ready")

    async def main_loop(self) -> None:
        interval = _watchdog_interval()
        watchdog_task = asyncio.create_task(self._watchdog(interval)) if interval is not None else None
        try:
            await super().main_loop()
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog_task

    async def shutdown(self, sockets=None) -> None:
        _systemd_notify("STOPPING=1\nSTATUS=WebNAS backend stopping")
        await super().shutdown(sockets=sockets)

    async def _watchdog(self, interval: float) -> None:
        while not self.should_exit:
            # Readiness is intentionally local-only. If startup/module-registry
            # state becomes unhealthy while the event loop is still alive,
            # withholding WATCHDOG=1 lets systemd recover the backend.
            if bool(getattr(app.state, "ready", False)):
                _systemd_notify("WATCHDOG=1")
            await asyncio.sleep(interval)


def main() -> None:
    cfg = get_config()
    host = os.environ.get("WEBNAS_BIND_HOST", cfg.server.host)
    port = int(os.environ.get("WEBNAS_BIND_PORT", cfg.server.port))
    behind_gateway = "WEBNAS_BIND_PORT" in os.environ
    options: dict[str, object] = {"host": host, "port": port}
    if cfg.server.use_https and not behind_gateway:
        options.update({"ssl_certfile": cfg.server.tls_cert, "ssl_keyfile": cfg.server.tls_key})
    server = WebNasServer(uvicorn.Config(app, **options))
    server.run()


if __name__ == "__main__":
    main()
