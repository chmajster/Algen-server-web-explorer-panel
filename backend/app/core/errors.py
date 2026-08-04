from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status: int = 400
    field: str | None = None
    details: dict[str, Any] = dataclass_field(default_factory=dict)


def error_payload(error: DomainError) -> dict[str, Any]:
    return {"data": None, "meta": {}, "error": {"code": error.code, "message": error.message, "field": error.field, "details": error.details}}


async def domain_error_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, DomainError):
        raise error
    return JSONResponse(error_payload(error), status_code=error.status)


def success_payload(data: Any, **meta: Any) -> dict[str, Any]:
    return {"data": data, "meta": meta, "error": None}
