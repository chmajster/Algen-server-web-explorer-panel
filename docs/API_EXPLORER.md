# API Explorer

API Explorer is a read-only development and diagnostics module for inspecting the FastAPI contract exposed by WebNAS.

## Purpose

The module provides a searchable endpoint inventory and lightweight OpenAPI validation without forwarding, replaying or proxying HTTP requests. This keeps the feature safe for administrative use: it cannot be used as an SSRF proxy and it cannot accidentally execute destructive API operations.

## Access

All routes require an authenticated session with `modules.view`.

The module routes are deliberately excluded from the generated public OpenAPI contract. This prevents the diagnostic feature from changing `frontend/src/generated/api-types.ts` and avoids self-reporting its own inspection endpoints.

## Routes

```text
GET /api/modules/api/summary
GET /api/modules/api/endpoints
GET /api/modules/api/contract
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

## Tests

The focused backend suite is:

```bash
python -m pytest backend/tests/test_api_explorer.py -ra
```

It covers schema flattening, filtering, pagination, deprecation handling, diagnostics, duplicate operation IDs, RBAC, query validation and the guarantee that API Explorer remains outside the generated public OpenAPI schema.
