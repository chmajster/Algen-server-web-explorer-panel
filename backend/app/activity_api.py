from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .activity import ActivityCategory, ActivityStatus, repository
from .rbac import authorize, has_permission
from .security import SessionUser, get_session_user


router = APIRouter(prefix="/api/activity", tags=["activity"])


def current_user(request: Request) -> SessionUser:
    return get_session_user(request)


@router.get("")
def activity_events(
    category: ActivityCategory | None = None,
    status: ActivityStatus | None = None,
    actor: str = Query(default="", max_length=128),
    search: str = Query(default="", max_length=200),
    since: float | None = Query(default=None, ge=0),
    until: float | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    user: SessionUser = Depends(current_user),
):
    authorize(user, "audit.view_own")
    # Keep the legacy permission probe for extensions that still expose the
    # pre-v1 RBAC name while preferring the granular identity permission.
    global_scope = has_permission(user.username, "audit.view_all") or has_permission(user.username, "audit.view")
    effective_actor = actor.strip() if global_scope and actor.strip() else None if global_scope else user.username
    items, total = repository().list(
        actor=effective_actor,
        category=category,
        status=status,
        search=search.strip(),
        since=since,
        until=until,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "scope": "global" if global_scope else "own",
    }


@router.get("/summary")
def activity_summary(user: SessionUser = Depends(current_user)):
    authorize(user, "audit.view_own")
    global_scope = has_permission(user.username, "audit.view_all") or has_permission(user.username, "audit.view")
    return {**repository().summary(actor=None if global_scope else user.username), "scope": "global" if global_scope else "own"}


@router.get("/export")
def activity_export(user: SessionUser = Depends(current_user)):
    authorize(user, "audit.export")
    items, total = repository().list(page=1, page_size=1000)
    return {"items": [item.model_dump(mode="json") for item in items], "total": total, "truncated": total > 1000}
