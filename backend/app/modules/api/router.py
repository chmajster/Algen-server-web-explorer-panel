from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...identity.permissions import Permission, authorize
from ...rbac import current_user
from ...security import SessionUser
from .service import (
    HTTP_METHODS,
    api_test_report,
    contract_report,
    endpoint_catalog,
    filter_endpoints,
    summarize_contract,
)


router = APIRouter(
    prefix="/api/modules/api",
    tags=["api-explorer"],
    include_in_schema=False,
)


def _allow(user: SessionUser) -> None:
    authorize(user, Permission.MODULES_VIEW)


@router.get("/summary")
def summary(request: Request, user: SessionUser = Depends(current_user)):
    _allow(user)
    return summarize_contract(request.app.openapi())


@router.get("/endpoints")
def endpoints(
    request: Request,
    search: str = Query("", max_length=300),
    method: str = Query("", max_length=16),
    tag: str = Query("", max_length=100),
    include_deprecated: bool = True,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: SessionUser = Depends(current_user),
):
    _allow(user)
    normalized_method = method.strip().upper()
    if normalized_method and normalized_method not in HTTP_METHODS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "API_METHOD_UNSUPPORTED",
                "message": f"Unsupported HTTP method: {normalized_method}",
                "allowed": list(HTTP_METHODS),
            },
        )

    values = filter_endpoints(
        endpoint_catalog(request.app.openapi()),
        search=search,
        method=normalized_method,
        tag=tag,
        include_deprecated=include_deprecated,
    )
    return {
        "items": values[offset : offset + limit],
        "total": len(values),
        "offset": offset,
        "limit": limit,
    }


@router.get("/contract")
def contract(request: Request, user: SessionUser = Depends(current_user)):
    _allow(user)
    return contract_report(request.app.openapi())


@router.get("/tests")
def tests(request: Request, user: SessionUser = Depends(current_user)):
    _allow(user)
    return api_test_report(request.app.openapi())
