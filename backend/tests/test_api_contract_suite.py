from __future__ import annotations

import importlib
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.modules.api.service import api_test_report, api_test_results
from app.security import SessionUser


api_router = importlib.import_module("app.modules.api.router")


def _healthy_contract() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Healthy API", "version": "1.0.0"},
        "paths": {
            "/api/widgets/{widget_id}": {
                "get": {
                    "tags": ["widgets"],
                    "summary": "Get widget",
                    "operationId": "getWidget",
                    "parameters": [
                        {
                            "name": "widget_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "verbose",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean"},
                        },
                    ],
                    "responses": {
                        "200": {"description": "Widget"},
                        "404": {"description": "Not found"},
                    },
                }
            },
            "/api/widgets": {
                "post": {
                    "tags": ["widgets"],
                    "summary": "Create widget",
                    "operationId": "createWidget",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"},
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            },
        },
    }


def _failed(report: dict[str, Any], check: str) -> list[dict[str, str]]:
    return [
        item
        for item in report["results"]
        if item["check"] == check and item["status"] == "failed"
    ]


def _application(monkeypatch) -> FastAPI:
    app = FastAPI(title="Runtime API", version="7.8.9")

    @app.get("/api/health", tags=["health"], summary="Health")
    def health():
        return {"ok": True}

    @app.get("/api/widgets/{widget_id}", tags=["widgets"], summary="Get widget")
    def widget(widget_id: str):
        return {"id": widget_id}

    app.include_router(api_router.router)
    app.dependency_overrides[api_router.current_user] = lambda: SessionUser("admin", "csrf")
    monkeypatch.setattr(api_router, "authorize", lambda _user, _permission: None)
    return app


def test_api_contract_suite_passes_a_well_formed_contract():
    report = api_test_report(_healthy_contract())

    assert report["summary"]["status"] == "ok"
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] == report["summary"]["total"]
    assert report["summary"]["score"] == 100.0


def test_api_contract_suite_detects_missing_top_level_metadata():
    contract = _healthy_contract()
    contract.pop("openapi")
    contract["info"] = {}

    report = api_test_report(contract)

    assert _failed(report, "openapi-version")[0]["severity"] == "error"
    assert _failed(report, "api-title")
    assert _failed(report, "api-version")
    assert report["summary"]["status"] == "error"


def test_api_contract_suite_detects_duplicate_operation_ids():
    contract = _healthy_contract()
    contract["paths"]["/api/widgets"]["post"]["operationId"] = "getWidget"

    report = api_test_report(contract)

    failure = _failed(report, "unique-operation-ids")[0]
    assert failure["severity"] == "error"
    assert "getWidget" in failure["message"]


def test_api_contract_suite_detects_path_parameter_contract_errors():
    contract = _healthy_contract()
    operation = contract["paths"]["/api/widgets/{widget_id}"]["get"]
    operation["parameters"] = [
        {
            "name": "widget_id",
            "in": "path",
            "required": False,
            "schema": {"type": "string"},
        },
        {
            "name": "ghost",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        },
    ]

    report = api_test_report(contract)

    required = _failed(report, "path-parameters-required")[0]
    template = _failed(report, "path-parameters-match-template")[0]
    assert required["severity"] == "error"
    assert "widget_id" in required["message"]
    assert "ghost" in template["message"]


def test_api_contract_suite_detects_missing_path_parameter_declaration():
    contract = _healthy_contract()
    contract["paths"]["/api/widgets/{widget_id}"]["get"]["parameters"] = []

    report = api_test_report(contract)

    failure = _failed(report, "path-parameters-declared")[0]
    assert failure["severity"] == "error"
    assert "widget_id" in failure["message"]


def test_api_contract_suite_detects_duplicate_parameters_at_same_scope():
    contract = _healthy_contract()
    parameters = contract["paths"]["/api/widgets/{widget_id}"]["get"]["parameters"]
    parameters.extend(
        [
            {"name": "page", "in": "query", "schema": {"type": "integer"}},
            {"name": "page", "in": "query", "schema": {"type": "integer"}},
        ]
    )

    report = api_test_report(contract)

    failure = _failed(report, "unique-parameters")[0]
    assert "query:page" in failure["message"]


def test_api_contract_suite_allows_path_level_parameter_override():
    contract = _healthy_contract()
    operation = contract["paths"]["/api/widgets/{widget_id}"]["get"]
    path_parameter = operation["parameters"].pop(0)
    contract["paths"]["/api/widgets/{widget_id}"]["parameters"] = [path_parameter]
    operation["parameters"].append(
        {
            "name": "widget_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "minLength": 1},
        }
    )

    report = api_test_report(contract)

    assert not _failed(report, "unique-parameters")
    assert not _failed(report, "path-parameters-declared")
    assert not _failed(report, "path-parameters-required")


def test_api_contract_suite_detects_parameter_without_schema_or_content():
    contract = _healthy_contract()
    contract["paths"]["/api/widgets/{widget_id}"]["get"]["parameters"].append(
        {"name": "trace", "in": "header"}
    )

    report = api_test_report(contract)

    failure = _failed(report, "parameter-schema")[0]
    assert "header:trace" in failure["message"]


def test_api_contract_suite_detects_request_body_without_content():
    contract = _healthy_contract()
    contract["paths"]["/api/widgets"]["post"]["requestBody"] = {"required": True}

    report = api_test_report(contract)

    assert _failed(report, "request-body-content")


def test_api_contract_suite_detects_request_body_on_read_method():
    contract = _healthy_contract()
    contract["paths"]["/api/widgets/{widget_id}"]["get"]["requestBody"] = {
        "content": {"application/json": {}}
    }

    report = api_test_report(contract)

    failure = _failed(report, "read-without-request-body")[0]
    assert "GET" in failure["message"]


def test_api_contract_suite_detects_missing_and_undocumented_responses():
    contract = _healthy_contract()
    get_operation = contract["paths"]["/api/widgets/{widget_id}"]["get"]
    get_operation["responses"] = {}
    post_operation = contract["paths"]["/api/widgets"]["post"]
    post_operation["responses"] = {
        "201": {},
        "400": {"description": "Bad request"},
    }

    report = api_test_report(contract)

    assert _failed(report, "responses-declared")
    assert _failed(report, "success-response")
    description_failure = _failed(report, "response-descriptions")[0]
    assert "201" in description_failure["message"]


def test_api_contract_suite_accepts_ref_parameters_and_responses():
    contract = _healthy_contract()
    contract["paths"]["/api/widgets/{widget_id}"]["get"]["parameters"].append(
        {"$ref": "#/components/parameters/TraceId"}
    )
    contract["paths"]["/api/widgets/{widget_id}"]["get"]["responses"]["401"] = {
        "$ref": "#/components/responses/Unauthorized"
    }

    report = api_test_report(contract)

    assert not _failed(report, "parameter-schema")
    assert not _failed(report, "response-descriptions")


def test_api_contract_suite_detects_missing_docs_tags_namespace_and_operation_id():
    contract = _healthy_contract()
    operation = contract["paths"].pop("/api/widgets")["post"]
    contract["paths"]["/internal/widgets"] = {"post": operation}
    operation.pop("summary")
    operation.pop("tags")
    operation.pop("operationId")

    report = api_test_report(contract)

    assert _failed(report, "api-namespace")
    assert _failed(report, "operation-documentation")
    assert _failed(report, "operation-tags")
    assert _failed(report, "operation-id")


def test_api_contract_suite_handles_malformed_paths_without_crashing():
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "Broken API", "version": "1.0.0"},
        "paths": ["not", "an", "object"],
    }

    report = api_test_report(contract)

    assert _failed(report, "paths-object")[0]["severity"] == "error"
    assert _failed(report, "operations-present")[0]["severity"] == "error"
    assert report["summary"]["status"] == "error"


def test_api_test_results_are_deterministic():
    first = api_test_results(_healthy_contract())
    second = api_test_results(deepcopy(_healthy_contract()))

    assert first == second


def test_tests_route_reads_live_openapi_without_exposing_itself(monkeypatch):
    app = _application(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/modules/api/tests")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] > 0
    assert body["summary"]["failed"] == 0
    assert body["summary"]["score"] == 100.0
    assert "/api/modules/api/tests" not in app.openapi()["paths"]


def test_tests_route_enforces_modules_view_permission(monkeypatch):
    app = _application(monkeypatch)

    def denied(_user, _permission):
        raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(api_router, "authorize", denied)
    response = TestClient(app).get("/api/modules/api/tests")

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"


def test_contract_suite_never_performs_http_requests(monkeypatch):
    import socket

    def forbidden(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in contract tests")

    monkeypatch.setattr(socket, "create_connection", forbidden)

    report = api_test_report(_healthy_contract())

    assert report["summary"]["status"] == "ok"
