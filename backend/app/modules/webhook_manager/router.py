from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..infrastructure_permissions import register_infrastructure_permissions
from .events import event_types
from .models import WebhookDeleteInput, WebhookInput
from .service import WebhookValidationError, service

register_infrastructure_permissions()
router = APIRouter(prefix="/api/modules/webhook-manager", tags=["webhook-manager"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, *, failed: bool = False) -> None:
    record_activity(
        ActivityCategory.module,
        action,
        actor,
        target=target,
        details=details or {},
        status=ActivityStatus.failure if failed else ActivityStatus.success,
        source="webhook-manager",
    )


def _controlled(operation):
    try:
        return operation()
    except KeyError as error:
        api_error(404, "WEBHOOK_NOT_FOUND", str(error).strip("'"))
    except WebhookValidationError as error:
        api_error(422, "WEBHOOK_VALIDATION_FAILED", str(error))
    except PermissionError as error:
        api_error(403, "WEBHOOK_SECRET_ACCESS_DENIED", str(error))
    except ValueError as error:
        api_error(422, "WEBHOOK_VALIDATION_FAILED", str(error))


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(current_user)):
    _allow(user, "webhook-manager.view")
    return service().dashboard()


@router.get("/events")
def events(user: SessionUser = Depends(current_user)):
    _allow(user, "webhook-manager.view")
    return {"events": event_types()}


@router.get("/webhooks")
def webhooks(user: SessionUser = Depends(current_user)):
    _allow(user, "webhook-manager.view")
    return {"items": service().webhooks()}


@router.get("/webhooks/{webhook_id}")
def webhook(webhook_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, "webhook-manager.view")
    item = service().webhook(webhook_id)
    if not item:
        api_error(404, "WEBHOOK_NOT_FOUND", "Webhook not found")
    return item


@router.post("/webhooks")
def create_webhook(payload: WebhookInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "webhook-manager.manage")
    result = _controlled(lambda: service().save(payload, user.username))
    _activity(user.username, "webhook_create", result["id"], {"name": result["name"]})
    return result


@router.put("/webhooks/{webhook_id}")
def update_webhook(webhook_id: str, payload: WebhookInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "webhook-manager.manage")
    if not service().webhook(webhook_id):
        api_error(404, "WEBHOOK_NOT_FOUND", "Webhook not found")
    result = _controlled(lambda: service().save(payload, user.username, webhook_id))
    _activity(user.username, "webhook_update", webhook_id, {"name": result["name"]})
    return result


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, payload: WebhookDeleteInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, "webhook-manager.manage")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Webhook removal requires confirmation")
    item = service().webhook(webhook_id)
    if not item:
        api_error(404, "WEBHOOK_NOT_FOUND", "Webhook not found")
    removed = service().delete(webhook_id)
    _activity(user.username, "webhook_delete", webhook_id, {"name": item["name"]})
    return {"ok": removed}


@router.put("/webhooks/{webhook_id}/enabled")
def set_enabled(
    webhook_id: str,
    enabled: bool = Query(...),
    user: SessionUser = Depends(mutating_user),
):
    _allow(user, "webhook-manager.manage")
    result = _controlled(lambda: service().set_enabled(webhook_id, enabled, user.username))
    _activity(user.username, "webhook_enable" if enabled else "webhook_disable", webhook_id)
    return result


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "webhook-manager.test")
    try:
        result = _controlled(lambda: service().test(webhook_id))
    except Exception:
        _activity(user.username, "webhook_test", webhook_id, failed=True)
        raise
    _activity(user.username, "webhook_test", webhook_id, {"status": result["status"], "http_status": result["http_status"]})
    return result


@router.get("/deliveries")
def deliveries(
    webhook_id: str = Query("", max_length=64),
    status: str = Query("", max_length=16),
    limit: int = Query(250, ge=1, le=1000),
    user: SessionUser = Depends(current_user),
):
    _allow(user, "webhook-manager.deliveries.view")
    return _controlled(lambda: {"items": service().deliveries(webhook_id=webhook_id, status=status, limit=limit)})
