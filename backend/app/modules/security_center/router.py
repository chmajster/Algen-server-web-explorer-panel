from __future__ import annotations

from fastapi import APIRouter, Depends

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...jobs.service import JobContext, service as jobs
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .models import FindingStateRequest
from .rbac import SECURITY_FINDINGS_MANAGE, SECURITY_SCAN, SECURITY_VIEW
from .service import service


router = APIRouter(prefix="/api/modules/security-center", tags=["security-center"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


@router.get("/summary")
def summary(user: SessionUser = Depends(current_user)):
    _allow(user, SECURITY_VIEW)
    return service().summary()


@router.get("/findings")
def findings(user: SessionUser = Depends(current_user)):
    _allow(user, SECURITY_VIEW)
    values = service().findings()
    return {"items": values, "total": len(values)}


@router.post("/scan")
def scan(user: SessionUser = Depends(mutating_user)):
    _allow(user, SECURITY_SCAN)

    def execute(context: JobContext, _metadata: dict) -> dict:
        record_activity(ActivityCategory.module, "security.scan.started", user.username, target="security-center", status=ActivityStatus.queued, source="security-center")
        context.update_progress(10, "Collecting security signals")
        result = service().scan()
        context.update_progress(95, "Security score calculated")
        record_activity(ActivityCategory.module, "security.scan.completed", user.username, target="security-center", details={"score": result["score"], "findings": result["findings"]}, source="security-center")
        return result

    job = jobs().submit_callable(job_type="security.scan", module="security-center", created_by=user.username, handler=execute, metadata={}, cancellable=False)
    return {"job": job.model_dump(mode="json")}


@router.post("/findings/{finding_id}/state")
def finding_state(finding_id: str, payload: FindingStateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, SECURITY_FINDINGS_MANAGE)
    try:
        return service().set_status(finding_id, payload.status, user.username)
    except LookupError as error:
        api_error(404, "SECURITY_FINDING_NOT_FOUND", str(error))


@router.get("/checks")
def checks(user: SessionUser = Depends(current_user)):
    _allow(user, SECURITY_VIEW)
    return {"items": [
        {"id": "firewall", "source": "Firewall Manager"}, {"id": "authentication", "source": "SSH configuration / journal"},
        {"id": "updates", "source": "Linux Updates"}, {"id": "network", "source": "Firewall Manager / Networking"},
        {"id": "tls", "source": "HTTPS settings"}, {"id": "users", "source": "Users & Groups / NSS"},
        {"id": "permissions", "source": "Filesystem permissions"}, {"id": "failed_logins", "source": "systemd journal"},
    ]}
