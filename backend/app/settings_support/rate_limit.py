from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException

from ..config import get_config


class AdminRateLimiter:
    """Bound administrative operations per client/user key."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        cfg = get_config()
        now = time.time()
        window = self._attempts[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= cfg.security.rate_limit_admin_per_minute:
            raise HTTPException(429, "Too many administrative operations")
        window.append(now)
