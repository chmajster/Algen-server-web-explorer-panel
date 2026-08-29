from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response

from .security import SessionUser, get_session_user
from .settings import admin_updates_progress, settings_me, system_update_status


router = APIRouter(tags=["startup"])

TaskScope = Literal["all", "own", "none"]


def build_startup_payload(request: Request, user: SessionUser) -> dict[str, Any]:
    """Compose bounded startup data without weakening RBAC or loading transfer history."""

    profile = settings_me(request, user)
    permissions = {str(value) for value in profile.get("permissions", [])}

    # Transfer history is deliberately kept off the authentication critical path.
    # Both global and per-user stores are unbounded and task serialization includes
    # log/diagnostic tails. The frontend already knows the transfer permissions from
    # `profile` and fetches the appropriate endpoint after the session is restored.
    task_scope: TaskScope = "none"
    tasks: list[dict[str, Any]] = []

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
