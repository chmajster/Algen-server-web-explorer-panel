from __future__ import annotations

import logging
import secrets
import sqlite3
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


def _integrity_error_response(endpoint: str, error: sqlite3.IntegrityError, request_id: str) -> tuple[int, dict[str, Any]]:
    database_reason = str(error)
    common = {
        "stage": "database",
        "endpoint": endpoint,
        "request_id": request_id,
    }

    if endpoint.startswith("/api/modules/hosts-manager/credentials") and "UNIQUE constraint failed: credentials.name" in database_reason:
        return 409, {
            "code": "CREDENTIAL_NAME_CONFLICT",
            "message": "Poświadczenie o tej nazwie już istnieje.",
            "field": "name",
            "reason": "duplicate_credential_name",
            "constraint": "unique",
            "hint": "Użyj innej nazwy poświadczenia albo wybierz istniejące poświadczenie zapisane w Hosts Manager. Dla Proxmox możesz przełączyć uwierzytelnianie na zapisane poświadczenie zamiast tworzyć kolejne o tej samej nazwie.",
            **common,
        }

    if "UNIQUE constraint failed:" in database_reason:
        return 409, {
            "code": "DATABASE_UNIQUE_CONFLICT",
            "message": "Nie można zapisać danych, ponieważ rekord z taką unikalną wartością już istnieje.",
            "reason": "unique_constraint",
            "constraint": "unique",
            "hint": f"Zmień wartość pola, które musi być unikalne. Jeśli konflikt nie jest widoczny w formularzu, sprawdź logi backendu dla request_id={request_id}.",
            **common,
        }

    if "FOREIGN KEY constraint failed" in database_reason:
        return 409, {
            "code": "DATABASE_REFERENCE_CONFLICT",
            "message": "Nie można zapisać danych, ponieważ wskazany powiązany rekord nie istnieje albo jest nadal wymagany.",
            "reason": "foreign_key_constraint",
            "constraint": "foreign_key",
            "hint": f"Odśwież dane i sprawdź wybrane powiązanie. Szczegóły techniczne są w logach backendu dla request_id={request_id}.",
            **common,
        }

    if "NOT NULL constraint failed:" in database_reason:
        return 422, {
            "code": "DATABASE_REQUIRED_VALUE",
            "message": "Nie można zapisać danych, ponieważ brakuje wymaganej wartości.",
            "reason": "not_null_constraint",
            "constraint": "not_null",
            "hint": f"Uzupełnij wymagane pola. Jeśli formularz wygląda na kompletny, sprawdź logi backendu dla request_id={request_id}.",
            **common,
        }

    return 409, {
        "code": "DATABASE_CONSTRAINT_ERROR",
        "message": "Baza danych odrzuciła zapis z powodu naruszenia ograniczenia integralności.",
        "reason": "integrity_constraint",
        "constraint": "integrity",
        "hint": f"Sprawdź, czy dane nie są duplikatem i czy wszystkie powiązane rekordy nadal istnieją. Szczegóły techniczne są w logach backendu dla request_id={request_id}.",
        **common,
    }


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

    if isinstance(error, sqlite3.IntegrityError):
        status, detail = _integrity_error_response(endpoint, error, request_id)
        return JSONResponse({"detail": detail}, status_code=status, headers={"X-Request-ID": request_id})

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
