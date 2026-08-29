from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")

FAST_CACHE_TTL_SECONDS = 1.0
MEDIUM_CACHE_TTL_SECONDS = 5.0
SLOW_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class CacheSnapshot(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Small process-local read-through cache with explicit invalidation."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._snapshot: CacheSnapshot[T] | None = None
        self._lock = threading.RLock()

    def get_or_load(self, loader: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            snapshot = self._snapshot
            if snapshot is not None and snapshot.expires_at > now:
                return snapshot.value
            value = loader()
            self._snapshot = CacheSnapshot(value=value, expires_at=now + self._ttl_seconds)
            return value

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = None
