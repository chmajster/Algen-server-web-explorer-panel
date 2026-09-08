from __future__ import annotations

from collections import Counter
from typing import Any


HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
PATH_ITEM_METADATA = {"parameters", "$ref", "summary", "description", "servers"}


def _operations(contract: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    values: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in contract.get("paths", {}).items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for raw_method, operation in path_item.items():
            method = str(raw_method).upper()
            if raw_method in PATH_ITEM_METADATA or method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            values.append((path, method, operation))
    return sorted(values, key=lambda item: (item[0], HTTP_METHODS.index(item[1])))


def endpoint_catalog(contract: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path, method, operation in _operations(contract):
        responses = operation.get("responses", {})
        response_codes = sorted(str(code) for code in responses) if isinstance(responses, dict) else []
        parameters = operation.get("parameters", [])
        result.append(
            {
                "path": path,
                "method": method,
                "tags": [str(tag) for tag in operation.get("tags", []) if str(tag).strip()],
                "summary": str(operation.get("summary") or ""),
                "description": str(operation.get("description") or ""),
                "operation_id": str(operation.get("operationId") or ""),
                "deprecated": bool(operation.get("deprecated", False)),
                "mutating": method not in READ_METHODS,
                "request_body_required": bool(
                    isinstance(operation.get("requestBody"), dict)
                    and operation["requestBody"].get("required", False)
                ),
                "parameter_count": len(parameters) if isinstance(parameters, list) else 0,
                "response_codes": response_codes,
            }
        )
    return result


def filter_endpoints(
    endpoints: list[dict[str, Any]],
    *,
    search: str = "",
    method: str = "",
    tag: str = "",
    include_deprecated: bool = True,
) -> list[dict[str, Any]]:
    query = search.strip().casefold()
    expected_method = method.strip().upper()
    expected_tag = tag.strip().casefold()

    def matches(item: dict[str, Any]) -> bool:
        if expected_method and item["method"] != expected_method:
            return False
        if expected_tag and expected_tag not in {value.casefold() for value in item["tags"]}:
            return False
        if not include_deprecated and item["deprecated"]:
            return False
        if not query:
            return True
        searchable = " ".join(
            [
                item["path"],
                item["method"],
                item["summary"],
                item["description"],
                item["operation_id"],
                *item["tags"],
            ]
        ).casefold()
        return query in searchable

    return [item for item in endpoints if matches(item)]


def contract_issues(contract: dict[str, Any]) -> list[dict[str, str]]:
    operations = _operations(contract)
    operation_ids: Counter[str] = Counter(
        str(operation.get("operationId"))
        for _, _, operation in operations
        if str(operation.get("operationId") or "").strip()
    )
    issues: list[dict[str, str]] = []

    for operation_id, count in sorted(operation_ids.items()):
        if count > 1:
            issues.append(
                {
                    "severity": "error",
                    "code": "DUPLICATE_OPERATION_ID",
                    "path": "",
                    "method": "",
                    "message": f"operationId '{operation_id}' is used {count} times",
                }
            )

    for path, method, operation in operations:
        operation_id = str(operation.get("operationId") or "").strip()
        tags = operation.get("tags", [])
        responses = operation.get("responses", {})
        response_codes = [str(code) for code in responses] if isinstance(responses, dict) else []

        if not operation_id:
            issues.append(
                {
                    "severity": "warning",
                    "code": "MISSING_OPERATION_ID",
                    "path": path,
                    "method": method,
                    "message": "Operation does not declare operationId",
                }
            )
        if not path.startswith("/api/"):
            issues.append(
                {
                    "severity": "warning",
                    "code": "NON_API_PATH",
                    "path": path,
                    "method": method,
                    "message": "Application operation is outside the /api/ namespace",
                }
            )
        if not isinstance(tags, list) or not tags:
            issues.append(
                {
                    "severity": "warning",
                    "code": "MISSING_TAG",
                    "path": path,
                    "method": method,
                    "message": "Operation has no OpenAPI tag",
                }
            )
        if response_codes and not any(code.startswith("2") for code in response_codes):
            issues.append(
                {
                    "severity": "warning",
                    "code": "MISSING_SUCCESS_RESPONSE",
                    "path": path,
                    "method": method,
                    "message": "Operation declares no 2xx response",
                }
            )
        if method in READ_METHODS and "requestBody" in operation:
            issues.append(
                {
                    "severity": "warning",
                    "code": "READ_REQUEST_BODY",
                    "path": path,
                    "method": method,
                    "message": f"{method} operation declares a request body",
                }
            )

    return sorted(
        issues,
        key=lambda item: (
            0 if item["severity"] == "error" else 1,
            item["code"],
            item["path"],
            item["method"],
        ),
    )


def summarize_contract(contract: dict[str, Any]) -> dict[str, Any]:
    endpoints = endpoint_catalog(contract)
    issues = contract_issues(contract)
    methods = Counter(item["method"] for item in endpoints)
    tags = Counter(tag for item in endpoints for tag in item["tags"])
    errors = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    status = "error" if errors else "warning" if warnings else "ok"
    return {
        "status": status,
        "title": str(contract.get("info", {}).get("title") or ""),
        "version": str(contract.get("info", {}).get("version") or ""),
        "openapi": str(contract.get("openapi") or ""),
        "path_count": len(contract.get("paths", {})),
        "endpoint_count": len(endpoints),
        "read_only_count": sum(not item["mutating"] for item in endpoints),
        "mutating_count": sum(item["mutating"] for item in endpoints),
        "deprecated_count": sum(item["deprecated"] for item in endpoints),
        "method_counts": dict(sorted(methods.items())),
        "tag_counts": dict(sorted(tags.items())),
        "issue_count": len(issues),
        "error_count": errors,
        "warning_count": warnings,
    }


def contract_report(contract: dict[str, Any]) -> dict[str, Any]:
    issues = contract_issues(contract)
    return {
        "summary": summarize_contract(contract),
        "issues": issues,
    }
