from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.platform_api import frontend_cache_policy, router as platform_router


def _client() -> TestClient:
    app = FastAPI()
    app.middleware("http")(frontend_cache_policy)

    @app.get("/api/example")
    def api_example():
        return {"ok": True}

    @app.get("/page")
    def page():
        return {"ok": True}

    return TestClient(app)


def test_security_headers_are_added_to_api_responses():
    response = _client().get("/api/example")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["cache-control"] == "no-store"


def test_frontend_response_keeps_revalidation_policy_and_security_headers():
    response = _client().get("/page")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_health_websocket_sends_initial_and_requested_heartbeats():
    app = FastAPI()
    app.include_router(platform_router)

    with TestClient(app) as client:
        with client.websocket_connect("/api/health/ws") as websocket:
            initial = websocket.receive_json()
            websocket.send_text("ping")
            heartbeat = websocket.receive_json()

    assert initial["type"] == "heartbeat"
    assert initial["status"] == "ok"
    assert initial["service"] == "webnas"
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["status"] == "ok"
