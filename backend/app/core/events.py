from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)
EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    """Small in-process domain event bus for decoupled module notifications."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, event: str, handler: EventHandler) -> Callable[[], None]:
        with self._lock:
            if handler not in self._handlers[event]:
                self._handlers[event].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers.get(event, [])
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def publish(self, event: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            handlers = tuple(self._handlers.get(event, ()))
        message = dict(payload or {})
        for handler in handlers:
            try:
                handler(message)
            except Exception:  # noqa: BLE001 - one subscriber must not break a producer
                logger.exception("domain_event_handler_failed event=%s", event)


bus = EventBus()
