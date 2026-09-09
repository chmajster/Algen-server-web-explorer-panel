# API Explorer

API Explorer is a read-only development and diagnostics module for inspecting and testing the FastAPI contract exposed by WebNAS.

## Purpose

The module provides a searchable endpoint inventory, OpenAPI diagnostics and a structural API test suite without forwarding, replaying or proxying HTTP requests. This keeps the feature safe for administrative use: it cannot be used as an SSRF proxy and it cannot accidentally execute destructive API operations.

## Access

All routes require an authenticated session with `modules.view`.

The module routes are deliberately excluded from the generated public OpenAPI contract. This prevents the diagnostic feature from changing `frontend/src/generated/api-types.ts` and avoids self-reporting its own inspection endpoints.

## Routes

```text
GET /api/modules/api/summary
GET /api/modules/api/endpoints
GET /api/modules/api/contract
GET /api/modules/api/tests
```

### Summary

`GET /api/modules/api/summary` returns:

- OpenAPI version and application version;
- path and endpoint counts;
- read-only and mutating operation counts;
- deprecated operation count;
- method and tag counts;
- contract warning/error counts and overall contract status.

### Endpoint catalog

`GET /api/modules/api/endpoints` accepts:

- `search` — searches path, method, summary, description, tags and `operationId`;
- `method` — exact HTTP method filter;
- `tag` — case-insensitive exact OpenAPI tag filter;
- `include_deprecated` — include/exclude deprecated operations;
- `offset` and `limit` — bounded pagination, maximum 500 rows.

Each result contains the path, method, tags, summary, description, `operationId`, deprecation flag, mutation classification, request body requirement, parameter count and declared response codes.

### Contract diagnostics

`GET /api/modules/api/contract` checks the live schema for:

- duplicate `operationId` values;
- missing `operationId` values;
- application operations outside `/api/`;
- missing tags;
- missing declared 2xx responses;
- request bodies declared on read-only methods.

Duplicate `operationId` values are errors. The remaining findings are warnings.

### API test suite

`GET /api/modules/api/tests` executes a deterministic, read-only structural test suite against the live OpenAPI document. It never calls application endpoints and never performs outbound HTTP requests.

The report contains an overall status, score, total/passed/failed counts and every individual test result. Checks include:

- OpenAPI version, API title and API version;
- valid `paths` structure;
- unique and present `operationId` values;
- `/api/` namespace consistency;
- tags and endpoint documentation;
- declared responses and at least one 2xx response;
- descriptions for inline responses;
- no request body on GET/HEAD/OPTIONS;
- content types for inline request bodies;
- declarations for every `{path_parameter}`;
- required path parameters;
- path parameters matching the URL template;
- duplicate parameters within the same OpenAPI scope;
- schema or content definition for inline parameters.

The suite distinguishes warning-level contract quality failures from error-level structural failures. The score is the percentage of passed checks.

## Tests

Focused backend suites:

```bash
python -m pytest backend/tests/test_api_explorer.py backend/tests/test_api_contract_suite.py -ra
```

Coverage includes schema flattening, filtering, pagination, deprecation handling, diagnostics, duplicate operation IDs, RBAC, query validation, path parameter rules, request body rules, response documentation, parameter schemas, deterministic reporting, network-isolation guarantees and the requirement that API Explorer stays outside the public OpenAPI schema.
