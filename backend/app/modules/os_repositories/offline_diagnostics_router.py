from __future__ import annotations

from fastapi import APIRouter, Depends

from ...package_center.models import api_error
from ...package_center.service import repository as package_repository
from ...security import SessionUser
from .offline_diagnostics import offline_diagnostics
from .offline_permissions import OFFLINE_VIEW, register_offline_repository_permissions

register_offline_repository_permissions()
router = APIRouter(prefix="/api/modules/os-repositories/offline", tags=["os-repositories-offline"])


def ready() -> None:
    if "os-repositories" not in package_repository().installed():
        api_error(404, "MODULE_NOT_INSTALLED", "Repozytoria systemowe module is not installed")


from ...identity.permissions import require_permission  # noqa: E402


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(require_permission(OFFLINE_VIEW, mutating=False))):
    ready()
    return offline_diagnostics()
