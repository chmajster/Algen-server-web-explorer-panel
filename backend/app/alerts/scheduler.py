from __future__ import annotations

import logging
import threading
import time

from .service import service


logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10
_started = False
_lock = threading.Lock()


def scheduler_tick() -> dict[str, int]:
    return service().process_due_deliveries()


def _loop() -> None:
    while True:
        try:
            scheduler_tick()
        except Exception:  # noqa: BLE001 - delivery worker must survive one failed cycle
            logger.exception("alert_delivery_scheduler_tick_failed")
        time.sleep(POLL_INTERVAL_SECONDS)


def start_scheduler() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        threading.Thread(
            target=_loop,
            daemon=True,
            name="alert-delivery-scheduler",
        ).start()
