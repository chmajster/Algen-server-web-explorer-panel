from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .update_coordination import read_update_request

router = APIRouter(tags=["platform"])
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def frontend_cache_policy(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if path.startswith("/assets/") else "no-cache, must-revalidate"
    return response


@router.get("/api/health")
def health():
    deployment_phase = None
    update_id = None
    try:
        request_state = read_update_request()
        if request_state.get("state") in {"preparing", "running"} and request_state.get("phase") in {"switching", "draining"}:
            deployment_phase = request_state.get("phase")
            update_id = request_state.get("id") or None
    except OSError:
        pass
    return {"status": "ok", "service": "webnas", "deployment_phase": deployment_phase, "update_id": update_id}


@router.get("/update-status", include_in_schema=False)
def update_status_frontend():
    index = frontend_dist / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Frontend build is unavailable")
    return FileResponse(index)
