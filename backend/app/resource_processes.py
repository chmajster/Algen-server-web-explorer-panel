from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .rbac import access_profile, authorize
from .resource_dashboard import top_processes
from .security import SessionUser, get_session_user

router = APIRouter()


@router.get("/api/system/processes")
def system_processes(user: SessionUser = Depends(get_session_user)) -> list[dict]:
    authorize(user, "system.status")
    if not bool(access_profile(user.username).get("is_admin")):
        raise HTTPException(403, "Administrator privileges required")
    return top_processes(None)
