from __future__ import annotations

import asyncio

from fastapi.routing import APIRoute

from app.bootstrap import _registry_router
from app.security import SessionUser


class _Registry:
    def __init__(self) -> None:
        self.manifests = {"demo": object()}
        self.catalog_calls = 0
        self.state = "active"
        self.diagnostic = None

    def public_catalog(self) -> list[dict]:
        self.catalog_calls += 1
        return [{"id": "demo", "state": self.state, "diagnostic": self.diagnostic}]

    async def health(self) -> list[dict]:
        self.state = "broken"
        self.diagnostic = "health check failed"
        return [{"id": "demo", "state": self.state, "diagnostic": self.diagnostic}]


def _endpoint(router, path: str):
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route.endpoint
    raise AssertionError(f"missing route: {path}")


def test_health_refresh_invalidates_cached_public_catalog() -> None:
    registry = _Registry()
    router = _registry_router(registry)
    catalog = _endpoint(router, "/api/v1/modules")
    health = _endpoint(router, "/api/v1/modules/health")
    user = SessionUser("alice", "csrf")

    first = catalog(user)
    second = catalog(user)
    assert registry.catalog_calls == 1
    assert first["data"][0]["state"] == "active"
    assert second["data"][0]["state"] == "active"

    asyncio.run(health(user))
    refreshed = catalog(user)

    assert registry.catalog_calls == 2
    assert refreshed["data"][0]["state"] == "broken"
    assert refreshed["data"][0]["diagnostic"] == "health check failed"
