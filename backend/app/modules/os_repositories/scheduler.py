from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from ...package_center.service import repository as package_repository
from .jobs import manager
from .service import service

logger = logging.getLogger(__name__)
_started = False
_lock = threading.Lock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _field_matches(value: int, expression: str, minimum: int, maximum: int) -> bool:
    for part in expression.split(","):
        if part == "*":
            return True
        if part.startswith("*/") and part[2:].isdigit():
            return value % int(part[2:]) == 0
        if "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit() and int(start) <= value <= int(end):
                return True
        elif part.isdigit() and minimum <= int(part) <= maximum and int(part) == value:
            return True
    return False


def schedule_matches(expression: str, timestamp: float) -> bool:
    current = dt.datetime.fromtimestamp(timestamp, tz=dt.UTC)
    aliases = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@weekly": "0 0 * * 0"}
    fields = aliases.get(expression.strip(), expression.strip()).split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    cron_weekday = (current.weekday() + 1) % 7
    return (
        _field_matches(current.minute, minute, 0, 59)
        and _field_matches(current.hour, hour, 0, 23)
        and _field_matches(current.day, day, 1, 31)
        and _field_matches(current.month, month, 1, 12)
        and _field_matches(cron_weekday, weekday, 0, 6)
    )


def scheduler_tick(now: float | None = None) -> int:
    current = now or time.time()
    if "os-repositories" not in package_repository().installed():
        return 0
    queued = 0
    for repository in service().store.all("SELECT * FROM repositories WHERE active=1 AND kind='mirror' AND schedule<>''"):
        if not schedule_matches(repository["schedule"], current):
            continue
        if repository.get("last_sync_at") and int(float(repository["last_sync_at"]) // 60) == int(current // 60):
            continue
        try:
            manager().enqueue_sync(repository["id"], "scheduler")
            queued += 1
        except (KeyError, ValueError, RuntimeError):
            continue
    return queued


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            scheduler_tick()
        except Exception:  # noqa: BLE001 - scheduler survives one failed iteration.
            logger.exception("os_repositories_scheduler_tick_failed")
        _stop_event.wait(30)


def start_scheduler() -> None:
    global _started, _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            _stop_event.clear()
            _started = True
            return
        _stop_event.clear()
        thread = threading.Thread(target=_loop, daemon=True, name="os-repositories-scheduler")
        _thread = thread
        _started = True
        thread.start()
        logger.info("os_repositories_scheduler_started")


def stop_scheduler() -> None:
    global _started, _thread
    with _lock:
        thread = _thread
        if not _started and (thread is None or not thread.is_alive()):
            return
        _started = False
        _stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)
    with _lock:
        if _thread is thread and (thread is None or not thread.is_alive()):
            _thread = None
    logger.info("os_repositories_scheduler_stopped")


def scheduler_status() -> dict[str, str]:
    with _lock:
        running = bool(_started and _thread is not None and _thread.is_alive())
    return {
        "health_state": "healthy" if running else "degraded",
        "message": "scheduler running" if running else "scheduler stopped",
    }
