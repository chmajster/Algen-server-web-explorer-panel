from __future__ import annotations

import re
import threading
from collections.abc import Callable

EVENT_NAME = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+$")

# Only events with publishers wired in this change are advertised by default.
# Additional modules can register real event types dynamically at runtime.
_DEFAULT_EVENTS = {
    "fail2ban.ip_banned",
    "fail2ban.ip_unbanned",
    "fail2ban.jail_changed",
    "fail2ban.service_changed",
    "secret.created",
    "secret.updated",
    "secret.deleted",
}
_events = set(_DEFAULT_EVENTS)
_listeners: list[Callable[[str], None]] = []
_lock = threading.RLock()


def register_event_type(event: str) -> str:
    event = event.strip().lower()
    if not EVENT_NAME.fullmatch(event):
        raise ValueError("invalid webhook event name")
    with _lock:
        added = event not in _events
        _events.add(event)
        listeners = tuple(_listeners) if added else ()
    for listener in listeners:
        listener(event)
    return event


def event_types() -> list[str]:
    with _lock:
        return sorted(_events)


def on_event_registered(listener: Callable[[str], None]) -> Callable[[], None]:
    with _lock:
        if listener not in _listeners:
            _listeners.append(listener)

    def unsubscribe() -> None:
        with _lock:
            if listener in _listeners:
                _listeners.remove(listener)

    return unsubscribe
