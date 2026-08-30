from __future__ import annotations

from fastapi import APIRouter, Depends

from ...activity import ActivityCategory, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .models import DiagnosticInput, PolicyRuleInput, RouteInput, TransactionConfirmInput
from .service import RoutingUnavailable, service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/modules/routing-manager", tags=["routing-manager"])


def _controlled(operation):
    try:
        return operation()
    except RoutingUnavailable:
        api_error(503, "ROUTING_UNAVAILABLE", "Routing backend is unavailable")
    except LookupError:
        api_error(404, "ROUTING_TRANSACTION_NOT_FOUND", "Routing transaction was not found")
    except ValueError:
        api_error(422, "ROUTING_VALIDATION_FAILED", "Routing request is invalid")
    except PermissionError:
        api_error(503, "ROUTING_PERMISSION_DENIED", "Routing operation is not permitted")
    except RuntimeError:
        api_error(502, "ROUTING_OPERATION_FAILED", "Routing operation failed")


def _audit(actor: str, action: str, target: str = "") -> None:
    record_activity(ActivityCategory.configuration, action, actor, target=target, source="routing-manager")


@router.get("/overview")
def overview(user: SessionUser = Depends(current_user)):
    authorize(user, "routing.view")
    return _controlled(lambda: {"backend": service().backend(), "routes": service().routes(), "rules": service().rules(), "tables": service().tables()})


@router.get("/routes")
def routes(user: SessionUser = Depends(current_user)):
    authorize(user, "routing.view")
    return _controlled(lambda: {"items": service().routes()})


@router.get("/rules")
def rules(user: SessionUser = Depends(current_user)):
    authorize(user, "routing.view")
    return _controlled(lambda: {"items": service().rules()})


@router.get("/tables")
def tables(user: SessionUser = Depends(current_user)):
    authorize(user, "routing.view")
    return _controlled(lambda: {"items": service().tables()})


@router.post("/routes/preview/{action}")
def preview(action: str, payload: RouteInput, user: SessionUser = Depends(current_user)):
    authorize(user, "routing.manage")
    return _controlled(lambda: service().preview(action, payload))


@router.post("/routes/{action}")
def apply_route(action: str, payload: RouteInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "routing.commit")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Routing changes require confirmation")
    job = _controlled(lambda: service().enqueue(action, payload, user.username))
    _audit(user.username, f"routing_{action}", payload.destination)
    return job


@router.post("/rules/{action}")
def policy_rule(action: str, payload: PolicyRuleInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "routing.commit")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Policy routing changes require confirmation")
    result = _controlled(lambda: service().policy_rule(action, payload, actor=user.username))
    _audit(user.username, f"routing_rule_{action}", payload.table)
    return result


@router.post("/diagnostics")
def diagnostics(payload: DiagnosticInput, user: SessionUser = Depends(current_user)):
    authorize(user, "routing.view")
    return _controlled(lambda: service().diagnostics(payload.target))


@router.get("/transactions/{transaction_id}")
def transaction(transaction_id: str, user: SessionUser = Depends(current_user)):
    authorize(user, "routing.view")
    return _controlled(lambda: service().transaction(transaction_id))


@router.post("/transactions/{transaction_id}/confirm")
def confirm(transaction_id: str, payload: TransactionConfirmInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "routing.commit")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Routing transaction confirmation is required")
    result = _controlled(lambda: service().confirm(transaction_id))
    _audit(user.username, "routing_confirm", transaction_id)
    return result


@router.post("/transactions/{transaction_id}/rollback")
def rollback(transaction_id: str, payload: TransactionConfirmInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, "routing.commit")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Routing rollback requires confirmation")
    result = _controlled(lambda: service().rollback(transaction_id))
    _audit(user.username, "routing_rollback", transaction_id)
    return result
