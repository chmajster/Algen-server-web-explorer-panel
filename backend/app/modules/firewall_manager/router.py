from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request

from ...activity import ActivityStatus

from ...auth import authenticate
from ...jobs.service import JobContext, service as jobs
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .models import FirewallActionRequest, FirewallBackupRequest, FirewallMutationRequest, FirewallRuleInput
from .rbac import FIREWALL_BACKUP, FIREWALL_DISABLE, FIREWALL_ENABLE, FIREWALL_RELOAD, FIREWALL_RESTORE, FIREWALL_RULE_CREATE, FIREWALL_RULE_DELETE, FIREWALL_RULE_EDIT, FIREWALL_VIEW
from ...identity.permissions import authorize
from .service import service


router = APIRouter(prefix="/api/modules/firewall-manager", tags=["firewall-manager"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _reauth(user: SessionUser, password: str, confirmation: str, expected: str) -> None:
    if confirmation != expected:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Exact firewall confirmation is required", expected=expected)
    authenticate(user.username, password)


def _request_context(request: Request) -> tuple[str, int]:
    client_ip = request.client.host if request.client else ""
    server = request.scope.get("server")
    port = int(server[1]) if isinstance(server, (list, tuple)) and len(server) > 1 and isinstance(server[1], int) else 0
    return client_ip, port


def _safe(operation: str, *, request: Request, acknowledge: bool, rule_id: str = "", rule: FirewallRuleInput | None = None) -> dict[str, Any]:
    client_ip, port = _request_context(request)
    plan = service().plan(operation, rule_id=rule_id, rule=rule, client_ip=client_ip, webnas_port=port)
    if plan["high_risk"] and not acknowledge:
        api_error(409, "FIREWALL_LOCKOUT_RISK", "The requested firewall change can interrupt the active administrative session", warnings=plan["warnings"])
    return plan


def _job(actor: str, operation: str, handler: Callable[[JobContext], dict[str, Any]]) -> dict[str, Any]:
    def execute(context: JobContext, _metadata: dict[str, Any]) -> dict[str, Any]:
        service().record(actor, f"firewall.{operation}.started")
        context.update_progress(10, "Validate and snapshot firewall")
        rollback = service().create_backup(f"Automatic rollback before {operation}")
        try:
            context.update_progress(40, "Apply firewall change")
            result = handler(context)
            context.update_progress(80, "Verify firewall state")
            service().status()
            service().record(actor, f"firewall.{operation}", details={"rollback_backup": rollback["id"]})
            return {**result, "rollback_backup": rollback["id"]}
        except Exception as error:
            try:
                service().restore_backup(rollback["id"])
            except Exception as rollback_error:
                service().record(actor, f"firewall.{operation}", status=ActivityStatus.failure, summary=f"{type(error).__name__}; rollback={type(rollback_error).__name__}")
                raise RuntimeError("firewall operation failed and automatic rollback could not be completed") from error
            service().record(actor, f"firewall.{operation}", status=ActivityStatus.failure, summary=type(error).__name__)
            raise
    job = jobs().submit_callable(job_type=f"firewall.{operation}", module="firewall-manager", created_by=actor, handler=execute, metadata={"operation": operation}, cancellable=False)
    return {"job": job.model_dump(mode="json")}


@router.get("/status")
def status(user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_VIEW)
    return service().status()


@router.get("/rules")
def rules(user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_VIEW)
    values = service().rules()
    return {"items": values, "total": len(values)}


@router.get("/listening-ports")
def listening_ports(user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_VIEW)
    values = service().listening_ports()
    return {"items": values, "total": len(values)}


@router.post("/rules/plan")
def plan_rule(payload: FirewallRuleInput, request: Request, user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_RULE_CREATE)
    client_ip, port = _request_context(request)
    return service().plan("rule.create", rule=payload, client_ip=client_ip, webnas_port=port)


@router.post("/rules")
def create_rule(payload: FirewallMutationRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_RULE_CREATE)
    if payload.rule is None:
        api_error(422, "FIREWALL_RULE_REQUIRED", "A firewall rule is required")
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:rule:create")
    _safe("rule.create", request=request, acknowledge=payload.acknowledge_lockout, rule=payload.rule)
    rule = payload.rule
    return _job(user.username, "rule.create", lambda _context: service().add_rule(rule))


@router.put("/rules/{rule_id}")
def edit_rule(rule_id: str, payload: FirewallMutationRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_RULE_EDIT)
    if payload.rule is None:
        api_error(422, "FIREWALL_RULE_REQUIRED", "A firewall rule is required")
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:rule:edit")
    _safe("rule.edit", request=request, acknowledge=payload.acknowledge_lockout, rule_id=rule_id, rule=payload.rule)
    rule = payload.rule
    return _job(user.username, "rule.edit", lambda _context: service().edit_rule(rule_id, rule))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, payload: FirewallActionRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_RULE_DELETE)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:rule:delete")
    _safe("rule.delete", request=request, acknowledge=payload.acknowledge_lockout, rule_id=rule_id)
    return _job(user.username, "rule.delete", lambda _context: service().delete_rule(rule_id))


@router.post("/enable")
def enable(payload: FirewallActionRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_ENABLE)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:enable")
    _safe("enable", request=request, acknowledge=payload.acknowledge_lockout)
    return _job(user.username, "enable", lambda _context: service().set_enabled(True))


@router.post("/disable")
def disable(payload: FirewallActionRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_DISABLE)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:disable")
    _safe("disable", request=request, acknowledge=payload.acknowledge_lockout)
    return _job(user.username, "disable", lambda _context: service().set_enabled(False))


@router.post("/reload")
def reload_firewall(payload: FirewallActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_RELOAD)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:reload")
    return _job(user.username, "reload", lambda _context: service().reload())


@router.get("/export")
def export_config(user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_VIEW)
    return service().export_configuration()


@router.get("/backups")
def backups(user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_VIEW)
    return {"items": service().list_backups()}


@router.post("/backups")
def backup(payload: FirewallBackupRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_BACKUP)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:backup")
    return _job(user.username, "backup", lambda _context: service().create_backup(payload.description))


@router.post("/backups/{backup_id}/restore")
def restore(backup_id: str, payload: FirewallActionRequest, request: Request, user: SessionUser = Depends(mutating_user)):
    _allow(user, FIREWALL_RESTORE)
    _reauth(user, payload.pam_password, payload.confirmation, "firewall:restore")
    _safe("restore", request=request, acknowledge=payload.acknowledge_lockout)
    return _job(user.username, "restore", lambda _context: service().restore_backup(backup_id))


@router.get("/activity")
def activity(user: SessionUser = Depends(current_user)):
    _allow(user, FIREWALL_VIEW)
    return {"items": service().activity()}
