from __future__ import annotations

import importlib
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.modules.api.service import (
    contract_issues,
    contract_report,
    endpoint_catalog,
    filter_endpoints,
    summarize_contract,
)
from app.security import SessionUser


api_router = importlib.import_module("app.modules.api.router")


def _contract() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Fixture API", "version": "2.4.1"},
        "paths": {
            "/api/widgets": {
                "parameters": [{"name": "trace", "in": "header"}],
                "get": {
                    "tags": ["widgets"],
                    "summary": "List widgets",
                    "description": "Returns all visible widgets.",
                    "operationId": "listWidgets",
                    "parameters": [{"name": "page", "in": "query"}],
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "tags": ["widgets", "write"],
                    "summary": "Create widget",
                    "operationId": "createWidget",
                    "requestBody": {"required": True, "content": {"application/json": {}}},
                    "responses": {"201": {"description": "Created"}},
                },
            },
            "/api/widgets/{widget_id}": {
                "get": {
                    "tags": ["widgets"],
                    "summary": "Get widget",
                    "operationId": "getWidget",
                    "deprecated": True,
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Missing"}},
                }
            },
        },
    }


def _application(monkeypatch) -> FastAPI:
    app = FastAPI(title="Contract Test", version="9.9.9")

    @app.get("/api/alpha", tags=["alpha"], summary="Alpha")
    def alpha():
        return {"ok": True}

    @app.get("/api/widgets", tags=["widgets"], summary="List widgets")
    def list_widgets():
        return []

    @app.post("/api/widgets", tags=["widgets"], summary="Create widget")
    def create_widget():
        return {"id": "one"}

    @app.get("/api/legacy", tags=["legacy"], deprecated=True)
    def legacy():
        return {"legacy": True}

    app.include_router(api_router.router)
    app.dependency_overrides[api_router.current_user] = lambda: SessionUser("admin", "csrf")
    monkeypatch.setattr(api_router, "authorize", lambda _user, _permission: None)
    return app


def test_endpoint_catalog_flattens_operations_and_normalizes_metadata():
    items = endpoint_catalog(_contract())

    assert [(item["path"], item["method"]) for item in items] == [
        ("/api/widgets", "GET"),
        ("/api/widgets", "POST"),
        ("/api/widgets/{widget_id}", "GET"),
    ]
    assert items[0]["operation_id"] == "listWidgets"
    assert items[0]["parameter_count"] == 1
    assert items[0]["mutating"] is False
    assert items[1]["request_body_required"] is True
    assert items[1]["mutating"] is True
    assert items[2]["deprecated"] is True
    assert items[2]["response_codes"] == ["200", "404"]


def test_endpoint_catalog_ignores_path_item_metadata_and_unknown_methods():
    contract = _contract()
    contract["paths"]["/api/widgets"]["x-extension"] = {"operationId": "notAnOperation"}
    contract["paths"]["/api/widgets"]["servers"] = [{"url": "https://example.test"}]

    items = endpoint_catalog(contract)

    assert len(items) == 3
    assert all(item["operation_id"] != "notAnOperation" for item in items)


def test_filter_endpoints_combines_search_method_tag_and_deprecation():
    items = endpoint_catalog(_contract())

    assert [item["operation_id"] for item in filter_endpoints(items, search="visible widgets")] == ["listWidgets"]
    assert [item["operation_id"] for item in filter_endpoints(items, method="post")] == ["createWidget"]
    assert [item["operation_id"] for item in filter_endpoints(items, tag="WRITE")] == ["createWidget"]
    assert [item["operation_id"] for item in filter_endpoints(items, include_deprecated=False)] == [
        "listWidgets",
        "createWidget",
    ]


def test_summary_reports_methods_tags_read_write_and_deprecated_counts():
    summary = summarize_contract(_contract())

    assert summary == {
        "status": "ok",
        "title": "Fixture API",
        "version": "2.4.1",
        "openapi": "3.1.0",
        "path_count": 2,
        "endpoint_count": 3,
        "read_only_count": 2,
        "mutating_count": 1,
        "deprecated_count": 1,
        "method_counts": {"GET": 2, "POST": 1},
        "tag_counts": {"widgets": 3, "write": 1},
        "issue_count": 0,
        "error_count": 0,
        "warning_count": 0,
    }


def test_contract_diagnostics_detect_duplicate_operation_ids_as_error():
    contract = _contract()
    contract["paths"]["/api/widgets/{widget_id}"]["get"]["operationId"] = "listWidgets"

    issues = contract_issues(contract)

    duplicate = next(item for item in issues if item["code"] == "DUPLICATE_OPERATION_ID")
    assert duplicate["severity"] == "error"
    assert "listWidgets" in duplicate["message"]
    assert contract_report(contract)["summary"]["status"] == "error"


def test_contract_diagnostics_detect_common_contract_smells():
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "Broken", "version": "1"},
        "paths": {
            "/internal/check": {
                "get": {
                    "requestBody": {"required": False},
                    "responses": {"500": {"description": "Failure"}},
                }
            }
        },
    }

    issues = contract_issues(contract)
    codes = {item["code"] for item in issues}

    assert codes == {
        "MISSING_OPERATION_ID",
        "NON_API_PATH",
        "MISSING_TAG",
        "MISSING_SUCCESS_RESPONSE",
        "READ_REQUEST_BODY",
    }
    summary = summarize_contract(contract)
    assert summary["status"] == "warning"
    assert summary["warning_count"] == 5
    assert summary["error_count"] == 0


def test_contract_report_keeps_summary_and_issue_list_consistent():
    contract = _contract()
    contract["paths"]["/api/widgets"]["get"].pop("tags")

    report = contract_report(contract)

    assert report["summary"]["issue_count"] == len(report["issues"])
    assert report["summary"]["warning_count"] == 1
    assert report["issues"][0]["code"] == "MISSING_TAG"


def test_summary_route_reads_the_live_application_schema(monkeypatch):
    app = _application(monkeypatch)

    response = TestClient(app).get("/api/modules/api/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Contract Test"
    assert body["version"] == "9.9.9"
    assert body["endpoint_count"] == 4
    assert body["method_counts"] == {"GET": 3, "POST": 1}
    assert body["mutating_count"] == 1


def test_api_explorer_routes_are_not_added_to_public_openapi(monkeypatch):
    app = _application(monkeypatch)

    paths = app.openapi()["paths"]

    assert "/api/modules/api/summary" not in paths
    assert "/api/modules/api/endpoints" not in paths
    assert "/api/modules/api/contract" not in paths


def test_endpoints_route_supports_search_method_tag_and_deprecated_filter(monkeypatch):
    client = TestClient(_application(monkeypatch))

    widgets = client.get("/api/modules/api/endpoints", params={"search": "widget", "method": "GET", "tag": "widgets"})
    without_deprecated = client.get("/api/modules/api/endpoints", params={"include_deprecated": "false"})

    assert widgets.status_code == 200
    assert widgets.json()["total"] == 1
    assert widgets.json()["items"][0]["path"] == "/api/widgets"
    assert widgets.json()["items"][0]["method"] == "GET"
    assert without_deprecated.status_code == 200
    assert all(not item["deprecated"] for item in without_deprecated.json()["items"])
    assert without_deprecated.json()["total"] == 3


def test_endpoints_route_paginates_after_filtering(monkeypatch):
    client = TestClient(_application(monkeypatch))

    response = client.get("/api/modules/api/endpoints", params={"offset": 1, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["offset"] == 1
    assert body["limit"] == 2
    assert len(body["items"]) == 2


def test_endpoints_route_rejects_unknown_http_method(monkeypatch):
    client = TestClient(_application(monkeypatch))

    response = client.get("/api/modules/api/endpoints", params={"method": "BREW"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "API_METHOD_UNSUPPORTED"
    assert "GET" in response.json()["detail"]["allowed"]


def test_contract_route_returns_live_diagnostics(monkeypatch):
    client = TestClient(_application(monkeypatch))

    response = client.get("/api/modules/api/contract")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["endpoint_count"] == 4
    assert body["summary"]["deprecated_count"] == 1
    assert body["summary"]["status"] == "ok"
    assert body["issues"] == []


def test_all_routes_enforce_modules_view_permission(monkeypatch):
    app = _application(monkeypatch)

    def denied(_user, _permission):
        raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(api_router, "authorize", denied)
    client = TestClient(app)

    for path in (
        "/api/modules/api/summary",
        "/api/modules/api/endpoints",
        "/api/modules/api/contract",
    ):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"] == "forbidden"


def test_query_validation_bounds_are_enforced_before_handler(monkeypatch):
    client = TestClient(_application(monkeypatch))

    assert client.get("/api/modules/api/endpoints", params={"offset": -1}).status_code == 422
    assert client.get("/api/modules/api/endpoints", params={"limit": 0}).status_code == 422
    assert client.get("/api/modules/api/endpoints", params={"limit": 501}).status_code == 422
    assert client.get("/api/modules/api/endpoints", params={"search": "x" * 301}).status_code == 422
