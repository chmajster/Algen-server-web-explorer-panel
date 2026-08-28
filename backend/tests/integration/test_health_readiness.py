from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.bootstrap import create_app
from app.platform_api import router as platform_router


class FakeRegistry:
    manifests: dict[str, object] = {}

    def install_routers(self, app: FastAPI) -> None:
        app.include_router(platform_router)

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def health(self) -> list[dict[str, str]]:
        return []

    def public_catalog(self) -> list[object]:
        return []


@pytest.mark.integration
def test_liveness_and_readiness_follow_application_lifespan() -> None:
    app = create_app(registry=FakeRegistry(), mount_frontend=False)  # type: ignore[arg-type]
    assert app.state.ready is False

    with TestClient(app) as client:
        live = client.get("/api/health/live")
        ready = client.get("/api/health/ready")
        legacy = client.get("/api/health")

        assert live.status_code == 200
        assert live.json()["check"] == "liveness"
        assert ready.status_code == 200
        assert ready.json()["status"] == "ok"
        assert legacy.status_code == 200

    assert app.state.ready is False
