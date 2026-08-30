from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...jobs.service import JobContext, service as jobs
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .checks import CATEGORIES
from .rbac import COMPLIANCE_SCAN, COMPLIANCE_VIEW
from .service import service


router = APIRouter(prefix="/api/modules/compliance-manager", tags=["compliance-manager"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


@router.get("/summary")
def summary(user: SessionUser = Depends(current_user)):
    _allow(user, COMPLIANCE_VIEW)
    return service().summary()


@router.get("/controls")
def controls(
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user: SessionUser = Depends(current_user),
):
    _allow(user, COMPLIANCE_VIEW)
    if category is not None and category not in CATEGORIES:
        return {"items": [], "total": 0}
    values = service().controls(category=category, status=status)
    return {"items": values, "total": len(values)}


@router.get("/benchmarks")
def benchmarks(user: SessionUser = Depends(current_user)):
    _allow(user, COMPLIANCE_VIEW)
    return service().benchmarks()


@router.get("/policies")
def policies(user: SessionUser = Depends(current_user)):
    _allow(user, COMPLIANCE_VIEW)
    return {
        "items": [
            {"id": "ssh", "name": "SSH", "source": "sshd -T / sshd_config"},
            {"id": "sudo", "name": "sudo", "source": "/etc/sudoers and /etc/sudoers.d"},
            {"id": "filesystem", "name": "Filesystem", "source": "mount table and protected file metadata"},
            {"id": "kernel", "name": "Kernel", "source": "/proc/sys effective sysctl values"},
            {"id": "pam", "name": "PAM", "source": "distribution PAM stack and login.defs"},
            {"id": "firewall", "name": "Firewall", "source": "Firewall Manager normalized backend"},
        ],
        "total": len(CATEGORIES),
    }


@router.post("/scan")
def scan(user: SessionUser = Depends(mutating_user)):
    _allow(user, COMPLIANCE_SCAN)

    def execute(context: JobContext, metadata: dict[str, Any]) -> dict[str, Any] | None:
        _ = metadata
        record_activity(
            ActivityCategory.module,
            "compliance.scan.started",
            user.username,
            target="compliance-manager",
            status=ActivityStatus.queued,
            source="compliance-manager",
        )
        context.update_progress(10, "Collecting compliance policy state")
        result = service().scan()
        context.update_progress(95, "Compliance score calculated")
        record_activity(
            ActivityCategory.module,
            "compliance.scan.completed",
            user.username,
            target="compliance-manager",
            status=ActivityStatus.success,
            details={"score": result.score, "passed": result.passed, "failed": result.failed, "manual": result.manual},
            source="compliance-manager",
        )
        return result.model_dump(mode="json")

    job = jobs().submit_callable(
        job_type="compliance.scan",
        module="compliance-manager",
        created_by=user.username,
        handler=execute,
        metadata={},
        cancellable=False,
    )
    return {"job": job.model_dump(mode="json")}
