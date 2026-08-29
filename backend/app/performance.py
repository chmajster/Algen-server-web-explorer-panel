from __future__ import annotations

import time

from fastapi import Request, Response

from .audit import logger


EXACT_PATHS = {
    "/api/files/list",
    "/api/system/resources",
}
PREFIX_PATHS = (
    "/api/modules/hosts-manager/",
)


def tracked_endpoint(path: str) -> bool:
    return path in EXACT_PATHS or any(path.startswith(prefix) for prefix in PREFIX_PATHS)


async def performance_timing(request: Request, call_next) -> Response:
    path = request.url.path
    if not tracked_endpoint(path):
        return await call_next(request)

    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "performance_timing endpoint=%s duration_ms=%.2f status=%s",
            path,
            duration_ms,
            status,
        )
