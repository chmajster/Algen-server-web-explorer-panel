from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from app.core.errors import unhandled_error_handler


def test_unhandled_backend_error_returns_safe_diagnostics_without_exception_message():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/modules/hosts-manager/credentials",
        "raw_path": b"/api/modules/hosts-manager/credentials",
        "query_string": b"secret=must-not-be-copied",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("webnas.local", 5000),
    }
    request = Request(scope)
    response = asyncio.run(unhandled_error_handler(request, RuntimeError("password=super-secret")))
    payload = json.loads(response.body)
    detail = payload["detail"]

    assert response.status_code == 500
    assert detail["code"] == "INTERNAL_SERVER_ERROR"
    assert detail["stage"] == "backend"
    assert detail["endpoint"] == "/api/modules/hosts-manager/credentials"
    assert detail["reason"] == "RuntimeError"
    assert detail["request_id"]
    assert response.headers["x-request-id"] == detail["request_id"]
    assert detail["request_id"] in detail["hint"]

    serialized = json.dumps(payload)
    assert "super-secret" not in serialized
    assert "must-not-be-copied" not in serialized
