from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


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


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    request_id = secrets.token_hex(8)
    endpoint = request.url.path
    logger.error(
        "Unhandled WebNAS backend error request_id=%s method=%s path=%s error_type=%s",
        request_id,
        request.method,
        endpoint,
        type(error).__name__,
        exc_info=(type(error), error, error.__traceback__),
    )
    detail = {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "WebNAS napotkał nieoczekiwany błąd backendu.",
        "stage": "backend",
        "endpoint": endpoint,
        "reason": type(error).__name__,
        "request_id": request_id,
        "hint": f"Sprawdź logi backendu WebNAS i wyszukaj request_id={request_id}. Szczegóły wyjątku pozostają wyłącznie w logach serwera.",
    }
    return JSONResponse({"detail": detail}, status_code=500, headers={"X-Request-ID": request_id})


def success_payload(data: Any, **meta: Any) -> dict[str, Any]:
    return {"data": data, "meta": meta, "error": None}
