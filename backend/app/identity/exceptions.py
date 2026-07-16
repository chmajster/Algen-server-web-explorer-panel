from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException


def identity_error(status: int, code: str, message: str, *, field: str | None = None) -> NoReturn:
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    raise HTTPException(status, detail)
