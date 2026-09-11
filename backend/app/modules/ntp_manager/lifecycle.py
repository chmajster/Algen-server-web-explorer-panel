from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .service import service

logger = logging.getLogger(__name__)
_history_task: asyncio.Task[None] | None = None


async def _history_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(service().record_history)
        except Exception:  # noqa: BLE001 - telemetry must never break the module runtime.
            logger.exception("NTP history sampling failed")
        await asyncio.sleep(300)


def startup() -> None:
    global _history_task
    if _history_task is None or _history_task.done():
        _history_task = asyncio.create_task(_history_loop(), name="ntp-history-sampler")


async def shutdown() -> None:
    global _history_task
    task = _history_task
    _history_task = None
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
