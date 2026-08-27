from __future__ import annotations

import asyncio
import json
import sqlite3

from starlette.requests import Request

from app.core.errors import unhandled_error_handler


def _request(path: str = "/api/modules/hosts-manager/credentials") -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"secret=must-not-be-copied",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("webnas.local", 5000),
    }
    return Request(scope)


def test_unhandled_backend_error_returns_safe_diagnostics_without_exception_message():
    response = asyncio.run(unhandled_error_handler(_request(), RuntimeError("password=super-secret")))
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


def test_duplicate_credential_name_returns_actionable_conflict_without_raw_sqlite_message():
    error = sqlite3.IntegrityError("UNIQUE constraint failed: credentials.name")
    response = asyncio.run(unhandled_error_handler(_request(), error))
    payload = json.loads(response.body)
    detail = payload["detail"]

    assert response.status_code == 409
    assert detail["code"] == "CREDENTIAL_NAME_CONFLICT"
    assert detail["field"] == "name"
    assert detail["stage"] == "database"
    assert detail["reason"] == "duplicate_credential_name"
    assert detail["constraint"] == "unique"
    assert "już istnieje" in detail["message"]
    assert "zapisane poświadczenie" in detail["hint"]
    assert detail["request_id"]
    assert response.headers["x-request-id"] == detail["request_id"]

    serialized = json.dumps(payload)
    assert "credentials.name" not in serialized
    assert "UNIQUE constraint failed" not in serialized


def test_generic_unique_constraint_is_reported_as_conflict_without_schema_details():
    error = sqlite3.IntegrityError("UNIQUE constraint failed: hosts.name")
    response = asyncio.run(unhandled_error_handler(_request("/api/modules/hosts-manager/hosts"), error))
    payload = json.loads(response.body)
    detail = payload["detail"]

    assert response.status_code == 409
    assert detail["code"] == "DATABASE_UNIQUE_CONFLICT"
    assert detail["stage"] == "database"
    assert detail["reason"] == "unique_constraint"
    assert detail["constraint"] == "unique"
    assert "hosts.name" not in json.dumps(payload)
