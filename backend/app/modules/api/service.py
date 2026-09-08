from __future__ import annotations

import re
from collections import Counter
from typing import Any


HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
PATH_ITEM_METADATA = {"parameters", "$ref", "summary", "description", "servers"}


def _operations(contract: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    values: list[tuple[str, str, dict[str, Any]]] = []
    paths = contract.get("paths", {})
    if not isinstance(paths, dict):
        return values
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for raw_method, operation in path_item.items():
            method = str(raw_method).upper()
            if raw_method in PATH_ITEM_METADATA or method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            values.append((path, method, operation))
    return sorted(values, key=lambda item: (item[0], HTTP_METHODS.index(item[1])))


def _parameter_lists(
    contract: dict[str, Any],
    path: str,
    operation: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    paths = contract.get("paths", {})
    path_item = paths.get(path, {}) if isinstance(paths, dict) else {}
    values: list[list[dict[str, Any]]] = []
    for raw in (
        path_item.get("parameters", []) if isinstance(path_item, dict) else [],
        operation.get("parameters", []),
    ):
        if isinstance(raw, list):
            values.append([item for item in raw if isinstance(item, dict)])
    return values


def _combined_parameters(
    contract: dict[str, Any],
    path: str,
    operation: dict[str, Any],
) -> list[dict[str, Any]]:
    return [parameter for values in _parameter_lists(contract, path, operation) for parameter in values]


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


def _test_result(
    check: str,
    passed: bool,
    *,
    severity: str = "warning",
    path: str = "",
    method: str = "",
    message: str,
) -> dict[str, str]:
    return {
        "check": check,
        "status": "passed" if passed else "failed",
        "severity": severity,
        "path": path,
        "method": method,
        "message": message,
    }


def api_test_results(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Run read-only structural tests against an OpenAPI document.

    These checks never execute application endpoints and never perform outbound
    HTTP requests. They validate documentation and contract invariants only.
    """

    operations = _operations(contract)
    results: list[dict[str, str]] = []
    info = contract.get("info", {})
    paths = contract.get("paths", {})

    results.extend(
        [
            _test_result(
                "openapi-version",
                bool(str(contract.get("openapi") or "").strip()),
                severity="error",
                message="OpenAPI version is declared.",
            ),
            _test_result(
                "api-title",
                isinstance(info, dict) and bool(str(info.get("title") or "").strip()),
                message="API title is declared.",
            ),
            _test_result(
                "api-version",
                isinstance(info, dict) and bool(str(info.get("version") or "").strip()),
                message="API version is declared.",
            ),
            _test_result(
                "paths-object",
                isinstance(paths, dict),
                severity="error",
                message="OpenAPI paths is an object.",
            ),
            _test_result(
                "operations-present",
                bool(operations),
                severity="error",
                message="At least one API operation is declared." if operations else "No API operations are declared.",
            ),
        ]
    )

    operation_ids = [
        str(operation.get("operationId") or "").strip()
        for _, _, operation in operations
        if str(operation.get("operationId") or "").strip()
    ]
    duplicate_ids = sorted(value for value, count in Counter(operation_ids).items() if count > 1)
    results.append(
        _test_result(
            "unique-operation-ids",
            not duplicate_ids,
            severity="error",
            message=(
                "All declared operationId values are unique."
                if not duplicate_ids
                else f"Duplicate operationId values: {', '.join(duplicate_ids)}"
            ),
        )
    )

    for path, method, operation in operations:
        scope = {"path": path, "method": method}
        operation_id = str(operation.get("operationId") or "").strip()
        tags = operation.get("tags", [])
        responses = operation.get("responses", {})
        parameters = _combined_parameters(contract, path, operation)
        parameter_lists = _parameter_lists(contract, path, operation)

        results.append(
            _test_result(
                "operation-id",
                bool(operation_id),
                **scope,
                message="operationId is declared." if operation_id else "operationId is missing.",
            )
        )
        results.append(
            _test_result(
                "api-namespace",
                path.startswith("/api/"),
                **scope,
                message="Path is inside /api/." if path.startswith("/api/") else "Path is outside /api/.",
            )
        )
        valid_tags = isinstance(tags, list) and any(str(tag).strip() for tag in tags)
        results.append(
            _test_result(
                "operation-tags",
                valid_tags,
                **scope,
                message="At least one non-empty tag is declared." if valid_tags else "No non-empty tags are declared.",
            )
        )
        documented = bool(str(operation.get("summary") or "").strip() or str(operation.get("description") or "").strip())
        results.append(
            _test_result(
                "operation-documentation",
                documented,
                **scope,
                message="Summary or description is declared." if documented else "Summary and description are both missing.",
            )
        )

        valid_responses = isinstance(responses, dict) and bool(responses)
        results.append(
            _test_result(
                "responses-declared",
                valid_responses,
                severity="error",
                **scope,
                message="At least one response is declared." if valid_responses else "No responses are declared.",
            )
        )
        response_codes = [str(code) for code in responses] if isinstance(responses, dict) else []
        has_success = any(code.startswith("2") for code in response_codes)
        results.append(
            _test_result(
                "success-response",
                has_success,
                **scope,
                message="A 2xx response is declared." if has_success else "No 2xx response is declared.",
            )
        )

        if isinstance(responses, dict):
            missing_descriptions = [
                str(code)
                for code, response in responses.items()
                if isinstance(response, dict)
                and "$ref" not in response
                and not str(response.get("description") or "").strip()
            ]
            results.append(
                _test_result(
                    "response-descriptions",
                    not missing_descriptions,
                    **scope,
                    message=(
                        "All inline responses have descriptions."
                        if not missing_descriptions
                        else f"Responses without descriptions: {', '.join(missing_descriptions)}"
                    ),
                )
            )

        read_body_ok = method not in READ_METHODS or "requestBody" not in operation
        results.append(
            _test_result(
                "read-without-request-body",
                read_body_ok,
                **scope,
                message=(
                    "Read-only method has no request body."
                    if read_body_ok
                    else f"{method} should not declare a request body."
                ),
            )
        )

        request_body = operation.get("requestBody")
        if isinstance(request_body, dict) and "$ref" not in request_body:
            content = request_body.get("content")
            has_content = isinstance(content, dict) and bool(content)
            results.append(
                _test_result(
                    "request-body-content",
                    has_content,
                    **scope,
                    message=(
                        "Inline request body declares content."
                        if has_content
                        else "Inline request body does not declare any content type."
                    ),
                )
            )

        placeholders = set(re.findall(r"{([^{}]+)}", path))
        declared_path_parameters = {
            str(parameter.get("name") or ""): parameter
            for parameter in parameters
            if parameter.get("in") == "path" and str(parameter.get("name") or "").strip()
        }
        missing_path_parameters = sorted(placeholders - set(declared_path_parameters))
        extra_path_parameters = sorted(set(declared_path_parameters) - placeholders)

        results.append(
            _test_result(
                "path-parameters-declared",
                not missing_path_parameters,
                severity="error",
                **scope,
                message=(
                    "All path placeholders have parameter declarations."
                    if not missing_path_parameters
                    else f"Missing path parameters: {', '.join(missing_path_parameters)}"
                ),
            )
        )
        results.append(
            _test_result(
                "path-parameters-match-template",
                not extra_path_parameters,
                **scope,
                message=(
                    "Declared path parameters match the path template."
                    if not extra_path_parameters
                    else f"Path parameters not present in template: {', '.join(extra_path_parameters)}"
                ),
            )
        )
        non_required_path_parameters = sorted(
            name
            for name in placeholders
            if name in declared_path_parameters and declared_path_parameters[name].get("required") is not True
        )
        results.append(
            _test_result(
                "path-parameters-required",
                not non_required_path_parameters,
                severity="error",
                **scope,
                message=(
                    "All declared path parameters are required."
                    if not non_required_path_parameters
                    else f"Path parameters must be required: {', '.join(non_required_path_parameters)}"
                ),
            )
        )

        duplicate_parameters: set[str] = set()
        for parameter_list in parameter_lists:
            seen: set[tuple[str, str]] = set()
            for parameter in parameter_list:
                key = (str(parameter.get("name") or ""), str(parameter.get("in") or ""))
                if key in seen and any(key):
                    duplicate_parameters.add(f"{key[1]}:{key[0]}")
                seen.add(key)
        results.append(
            _test_result(
                "unique-parameters",
                not duplicate_parameters,
                **scope,
                message=(
                    "No duplicate parameters are declared at the same scope."
                    if not duplicate_parameters
                    else f"Duplicate parameters: {', '.join(sorted(duplicate_parameters))}"
                ),
            )
        )

        parameters_without_schema = sorted(
            f"{str(parameter.get('in') or '?')}:{str(parameter.get('name') or '?')}"
            for parameter in parameters
            if "$ref" not in parameter
            and not isinstance(parameter.get("schema"), dict)
            and not isinstance(parameter.get("content"), dict)
        )
        results.append(
            _test_result(
                "parameter-schema",
                not parameters_without_schema,
                **scope,
                message=(
                    "All inline parameters declare schema or content."
                    if not parameters_without_schema
                    else f"Parameters without schema/content: {', '.join(parameters_without_schema)}"
                ),
            )
        )

    return results


def api_test_report(contract: dict[str, Any]) -> dict[str, Any]:
    results = api_test_results(contract)
    failed = [item for item in results if item["status"] == "failed"]
    errors = sum(item["severity"] == "error" for item in failed)
    warnings = sum(item["severity"] == "warning" for item in failed)
    total = len(results)
    passed = total - len(failed)
    score = round((passed / total) * 100, 1) if total else 100.0
    status = "error" if errors else "warning" if warnings else "ok"
    return {
        "summary": {
            "status": status,
            "total": total,
            "passed": passed,
            "failed": len(failed),
            "error_count": errors,
            "warning_count": warnings,
            "score": score,
        },
        "results": results,
    }
