from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response

from .security import SessionUser, get_session_user
from .settings import admin_updates_progress, settings_me, system_update_status
from .tasks import task_store


router = APIRouter(tags=["startup"])

TaskScope = Literal["all", "own", "none"]


def build_startup_payload(request: Request, user: SessionUser) -> dict[str, Any]:
    """Compose the data needed before rendering the desktop without weakening RBAC."""

    profile = settings_me(request, user)
    permissions = {str(value) for value in profile.get("permissions", [])}

    task_scope: TaskScope
    if "transfers.view_all" in permissions:
        task_scope = "all"
        tasks = [task.to_dict() for task in task_store.list_all()]
    elif "transfers.view_own" in permissions:
        task_scope = "own"
        tasks = [task.to_dict() for task in task_store.list_for(user.username)]
    else:
        task_scope = "none"
        tasks = []

    update_detailed = "updates.view" in permissions
    update_progress = admin_updates_progress(user) if update_detailed else system_update_status(user)
    return {
        "user": {
            "username": user.username,
            "home": str(profile.get("home", "")),
            "csrf_token": user.csrf_token,
        },
        "profile": profile,
        "tasks": tasks,
        "task_scope": task_scope,
        "update_progress": update_progress,
        "update_detailed": update_detailed,
    }


@router.get("/api/bootstrap", include_in_schema=False)
def startup_bootstrap(
    request: Request,
    response: Response,
    user: SessionUser = Depends(get_session_user),
):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Vary"] = "Cookie, Accept-Language"
    return build_startup_payload(request, user)
