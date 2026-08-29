from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from ...activity import ActivityCategory, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .models import TerminateSessionInput
from .service import LoginHistoryUnavailable, service

register_infrastructure_permissions(); router = APIRouter(prefix="/api/modules/login-history", tags=["login-history"])

def _controlled(operation):
    try: return operation()
    except LoginHistoryUnavailable as error: api_error(503, "LOGIN_HISTORY_UNAVAILABLE", str(error))
    except RuntimeError as error: api_error(502, "LOGIN_HISTORY_OPERATION_FAILED", str(error))

@router.get("/overview")
def overview(user: SessionUser = Depends(current_user)):
    authorize(user, "login_history.view"); return _controlled(service().overview)

@router.get("/events")
def events(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), username: str = Query("", max_length=128), source_ip: str = Query("", max_length=64), result: str = Query("", max_length=16), session_type: str = Query("", max_length=16), query: str = Query("", max_length=160), since: str = Query("7 days ago", max_length=64), user: SessionUser = Depends(current_user)):
    authorize(user, "login_history.view"); return _controlled(lambda: service().events(limit=limit, offset=offset, username=username, source_ip=source_ip, result=result, session_type=session_type, query=query, since=since))

@router.get("/sessions")
def sessions(user: SessionUser = Depends(current_user)):
    authorize(user, "login_history.view"); return _controlled(lambda: {"items": service().active_sessions()})

@router.get("/findings")
def findings(user: SessionUser = Depends(current_user)):
    authorize(user, "login_history.view"); return _controlled(lambda: {"items": service().security_findings()})

@router.post("/sessions/terminate")
def terminate(payload: TerminateSessionInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "login_history.sessions.terminate")
    if not payload.confirm: api_error(422, "CONFIRMATION_REQUIRED", "Terminating a login session requires confirmation")
    result = _controlled(lambda: service().terminate_session(payload.session_id))
    record_activity(ActivityCategory.login, "login_session_terminate", user.username, target=payload.session_id, source="login-history")
    return result
