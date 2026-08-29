from __future__ import annotations

from fastapi import APIRouter, Depends

from ...identity.permissions import Permission, require_permission
from ...security import SessionUser
from .service import service


router = APIRouter(prefix="/api/storage", tags=["storage-manager"])


@router.get("/summary")
def summary(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    return service().snapshot()


@router.get("/devices")
def devices(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    roots = service().block_devices()
    return {"devices": roots, "device_health": service().device_health(roots), "read_only": True}


@router.get("/filesystems")
def filesystems(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    return {"filesystems": service().filesystems(), "read_only": True}


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(require_permission(Permission.MODULES_DIAGNOSTICS))):
    del user
    snapshot = service().snapshot()
    return {
        "state": snapshot["state"],
        "issues": snapshot["issues"],
        "md_arrays": snapshot["md_arrays"],
        "zfs_pools": snapshot["zfs_pools"],
        "btrfs_filesystems": snapshot["btrfs_filesystems"],
        "tools": snapshot["tools"],
        "generated_at": snapshot["generated_at"],
        "read_only": True,
    }
