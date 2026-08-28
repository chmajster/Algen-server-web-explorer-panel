from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import threading
import time

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
    """Return half of systemd's watchdog interval when systemd supervision is active."""

    raw = os.environ.get("WATCHDOG_USEC", "")
    try:
        watchdog_usec = int(raw)
    except ValueError:
        return None
    if watchdog_usec <= 0:
        return None
    return max(1.0, watchdog_usec / 2_000_000)


def _runtime_watchdog_timeout() -> float | None:
    """Enable self-recovery only for installed/supervised WebNAS processes."""

    if not (os.environ.get("WEBNAS_SLOT") or os.environ.get("NOTIFY_SOCKET")):
        return None
    raw = os.environ.get("WEBNAS_RUNTIME_WATCHDOG_SEC", "60")
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 60.0
    return max(15.0, timeout)


class RuntimeWatchdog:
    """Terminate a stuck backend so systemd can recover it with Restart=on-failure."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self._last_heartbeat = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def heartbeat(self) -> None:
        self._last_heartbeat = time.monotonic()

    def expired(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return current > self._last_heartbeat + self.timeout_seconds

    def start(self) -> None:
        if self._thread is not None:
            return
        self.heartbeat()
        self._thread = threading.Thread(target=self._run, name="webnas-runtime-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        check_interval = min(5.0, max(1.0, self.timeout_seconds / 4))
        while not self._stop.wait(check_interval):
            if not self.expired():
                continue
            message = (
                f"WebNAS runtime watchdog: no healthy event-loop heartbeat for "
                f"{self.timeout_seconds:.0f}s; terminating backend for systemd recovery.\n"
            )
            try:
                os.write(2, message.encode("utf-8"))
            except OSError:
                pass
            _systemd_notify("STATUS=WebNAS runtime watchdog timeout")
            os._exit(1)


class WebNasServer(uvicorn.Server):
    """Uvicorn server integrated with systemd and runtime-stall supervision."""

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        timeout = _runtime_watchdog_timeout()
        self.runtime_watchdog = RuntimeWatchdog(timeout) if timeout is not None else None

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if not self.should_exit:
            if self.runtime_watchdog is not None:
                self.runtime_watchdog.start()
            _systemd_notify("READY=1\nSTATUS=WebNAS backend ready")

    async def main_loop(self) -> None:
        systemd_interval = _watchdog_interval()
        heartbeat_interval = min(systemd_interval or 5.0, 5.0)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(heartbeat_interval, systemd_interval is not None))
        try:
            await super().main_loop()
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        if self.runtime_watchdog is not None:
            self.runtime_watchdog.stop()
        _systemd_notify("STOPPING=1\nSTATUS=WebNAS backend stopping")
        await super().shutdown(sockets=sockets)

    async def _heartbeat_loop(self, interval: float, notify_systemd: bool) -> None:
        while not self.should_exit:
            if self.runtime_watchdog is not None:
                self.runtime_watchdog.heartbeat()
            if notify_systemd:
                _systemd_notify("WATCHDOG=1")
            await asyncio.sleep(interval)


def main() -> None:
    cfg = get_config()
    config = uvicorn.Config(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        proxy_headers=False,
    )
    server = WebNasServer(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
