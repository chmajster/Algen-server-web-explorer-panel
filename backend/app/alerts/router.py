from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..identity.permissions import Permission, require_permission
from ..package_center.models import api_error
from ..security import SessionUser
from .models import AlertActionInput, AlertSeverity, AlertState, RuleInput, SinkInput, TestDeliveryInput
from .service import service


router = APIRouter(prefix="/api/alerts", tags=["alerts"], include_in_schema=False)


def _audit(actor: str, action: str, target: str, details: dict | None = None, *, failed: bool = False) -> None:
    record_activity(
        ActivityCategory.administration,
        action,
        actor,
        target=target,
        details=details or {},
        status=ActivityStatus.failure if failed else ActivityStatus.success,
        source="alerts",
    )


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.SYSTEM_STATUS))):
    del user
    return service().dashboard()


@router.get("")
def alerts(
    state: AlertState | None = None,
    severity: AlertSeverity | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    user: SessionUser = Depends(require_permission(Permission.SYSTEM_STATUS)),
):
    del user
    return service().list_alerts(
        state=state.value if state else "",
        severity=severity.value if severity else "",
        limit=limit,
    )


@router.post("/{alert_id}/acknowledge")
def acknowledge(
    alert_id: str,
    payload: AlertActionInput,
    user: SessionUser = Depends(require_permission(Permission.MODULES_CONFIGURE, mutating=True)),
):
    try:
        item = service().acknowledge(alert_id, user.username, payload.note)
    except ValueError as error:
        api_error(409, "ALERT_STATE_CONFLICT", str(error))
    if item is None:
        api_error(404, "ALERT_NOT_FOUND", "Alert not found")
    _audit(user.username, "alert_acknowledge", alert_id, {"note": payload.note[:200]})
    return item


@router.post("/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    payload: AlertActionInput,
    user: SessionUser = Depends(require_permission(Permission.MODULES_CONFIGURE, mutating=True)),
):
    item = service().resolve_alert(alert_id, user.username)
    if item is None:
        api_error(404, "ALERT_NOT_FOUND", "Alert not found")
    _audit(user.username, "alert_resolve", alert_id, {"note": payload.note[:200]})
    return item


@router.get("/rules")
def rules(user: SessionUser = Depends(require_permission(Permission.SYSTEM_STATUS))):
    del user
    return service().list_rules()


@router.post("/rules")
def create_rule(
    payload: RuleInput,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    try:
        item = service().save_rule(payload, user.username)
    except KeyError:
        api_error(422, "ALERT_SINK_NOT_FOUND", "One or more notification sinks do not exist")
    _audit(user.username, "alert_rule_create", item["id"], {"source": item["source"], "severity": item["severity"]})
    return item


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    payload: RuleInput,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    try:
        item = service().save_rule(payload, user.username, rule_id)
    except KeyError:
        api_error(422, "ALERT_SINK_NOT_FOUND", "One or more notification sinks do not exist")
    _audit(user.username, "alert_rule_update", rule_id, {"source": item["source"], "severity": item["severity"]})
    return item


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    try:
        removed = service().delete_rule(rule_id)
    except PermissionError:
        api_error(409, "BUILTIN_ALERT_RULE", "Built-in alert rules cannot be deleted")
    except ValueError:
        api_error(409, "ALERT_RULE_IN_USE", "Alert rule has historical alerts")
    if not removed:
        api_error(404, "ALERT_RULE_NOT_FOUND", "Alert rule not found")
    _audit(user.username, "alert_rule_delete", rule_id)
    return {"ok": True}


@router.get("/sinks")
def sinks(user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM))):
    del user
    return service().list_sinks()


@router.post("/sinks")
def create_sink(
    payload: SinkInput,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    try:
        item = service().save_sink(payload, user.username)
    except Exception as error:
        _audit(user.username, "alert_sink_create", "new", {"error_type": type(error).__name__}, failed=True)
        raise
    _audit(user.username, "alert_sink_create", item["id"], {"name": item["name"], "type": item["type"]})
    return item


@router.put("/sinks/{sink_id}")
def update_sink(
    sink_id: str,
    payload: SinkInput,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    item = service().save_sink(payload, user.username, sink_id)
    _audit(user.username, "alert_sink_update", sink_id, {"name": item["name"], "type": item["type"]})
    return item


@router.delete("/sinks/{sink_id}")
def delete_sink(
    sink_id: str,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    try:
        removed = service().delete_sink(sink_id)
    except ValueError:
        api_error(409, "ALERT_SINK_IN_USE", "Notification sink is assigned to an alert rule")
    if not removed:
        api_error(404, "ALERT_SINK_NOT_FOUND", "Notification sink not found")
    _audit(user.username, "alert_sink_delete", sink_id)
    return {"ok": True}


@router.post("/sinks/{sink_id}/test")
def test_sink(
    sink_id: str,
    payload: TestDeliveryInput,
    user: SessionUser = Depends(require_permission(Permission.SETTINGS_EDIT_SYSTEM, mutating=True)),
):
    if payload.sink_id != sink_id:
        api_error(422, "ALERT_SINK_MISMATCH", "Sink identifier mismatch")
    try:
        result = service().test_delivery(sink_id, payload.diagnostic)
    except KeyError:
        api_error(404, "ALERT_SINK_NOT_FOUND", "Notification sink not found")
    except Exception as error:
        _audit(user.username, "alert_sink_test", sink_id, {"error_type": type(error).__name__}, failed=True)
        api_error(502, "ALERT_TEST_DELIVERY_FAILED", "Test notification delivery failed", reason=type(error).__name__)
    _audit(user.username, "alert_sink_test", sink_id, {"diagnostic": result["diagnostic"]})
    return result
