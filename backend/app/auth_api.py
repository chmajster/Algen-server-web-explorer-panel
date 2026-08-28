from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .activity import ActivityCategory, ActivityStatus, record_activity
from .audit import logger
from .auth import authenticate, normalize_username, user_home
from .security import clear_session, create_session, get_session_user, rate_limiter, require_csrf

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


def current_user(request: Request):
    return get_session_user(request)


def csrf_user(request: Request):
    user = get_session_user(request)
    require_csrf(request, user)
    return user


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    username = normalize_username(payload.username)
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{username}"
    try:
        rate_limiter.check(key)
        authenticate(username, payload.password)
    except HTTPException as error:
        if error.status_code != 429:
            rate_limiter.record_failure(key)
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": error.status_code},
            source="auth",
        )
        raise

    rate_limiter.clear(key)
    csrf = create_session(response, username, remember_me=payload.remember_me)
    logger.info("login user=%s", username)
    record_activity(ActivityCategory.login, "login", username, details={"client": client, "persistent": payload.remember_me}, source="auth")
    return {"username": username, "home": user_home(username), "csrf_token": csrf}


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(csrf_user)):
    logger.info("logout user=%s", user.username)
    record_activity(ActivityCategory.login, "logout", user.username, source="auth")
    clear_session(response, request)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"username": user.username, "home": user_home(user.username), "csrf_token": user.csrf_token}
