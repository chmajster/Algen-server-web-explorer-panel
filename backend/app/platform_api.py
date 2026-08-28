from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from .update_coordination import read_update_request


router = APIRouter(tags=["platform"])
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
ASSET_PREFIX = "/assets/"
_RANGE_REQUEST_HEADERS = {b"range", b"if-range"}
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _strip_asset_range_headers(request: Request) -> None:
    """Force complete frontend assets instead of cacheable partial responses."""

    headers = request.scope.get("headers")
    if not isinstance(headers, list):
        return
    request.scope["headers"] = [
        (name, value)
        for name, value in headers
        if name.lower() not in _RANGE_REQUEST_HEADERS
    ]


def _asset_response_is_complete(response) -> bool:
    if response.status_code != 200:
        return False
    content_length = response.headers.get("Content-Length")
    return bool(content_length and content_length.isdigit() and int(content_length) > 0)


def _apply_security_headers(response: Response) -> None:
    for name, value in _SECURITY_HEADERS.items():
        if name not in response.headers:
            response.headers[name] = value


async def frontend_cache_policy(request: Request, call_next):
    path = request.url.path
    is_asset = path.startswith(ASSET_PREFIX)

    if is_asset:
        # Starlette StaticFiles supports Range requests. JavaScript and CSS are
        # executable resources and must never be delivered as an isolated range
        # that an intermediary could later reuse as the complete immutable file.
        _strip_asset_range_headers(request)

    response = await call_next(request)
    _apply_security_headers(response)

    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        return response

    if is_asset:
        response.headers["Accept-Ranges"] = "none"
        if _asset_response_is_complete(response):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            # Never retain 206, truncated, zero-length or failed asset responses.
            response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"

    return response


def _deployment_metadata() -> dict[str, object | None]:
    deployment_phase = None
    update_id = None
    try:
        request_state = read_update_request()
        if request_state.get("state") in {"preparing", "running"} and request_state.get("phase") in {"switching", "draining"}:
            deployment_phase = request_state.get("phase")
            update_id = request_state.get("id") or None
    except OSError:
        pass
    return {"deployment_phase": deployment_phase, "update_id": update_id}


@router.get("/api/health/live")
def liveness():
    """Process-level health only; external providers never affect liveness."""

    return {"status": "ok", "service": "webnas", "check": "liveness", **_deployment_metadata()}


@router.get("/api/health/ready")
def readiness(request: Request, response: Response):
    """Report whether local startup and module-registry initialization completed."""

    ready = bool(getattr(request.app.state, "ready", False))
    if not ready:
        response.status_code = 503
    return {"status": "ok" if ready else "not_ready", "service": "webnas", "check": "readiness", **_deployment_metadata()}


@router.get("/api/health")
def health():
    """Backward-compatible health endpoint retained for existing installers."""

    return {"status": "ok", "service": "webnas", **_deployment_metadata()}


@router.get("/update-status", include_in_schema=False)
def update_status_frontend():
    index = frontend_dist / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Frontend build is unavailable")
    return FileResponse(index)
