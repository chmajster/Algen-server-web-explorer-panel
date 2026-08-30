from __future__ import annotations

from fastapi import APIRouter, Depends

from ...identity.permissions import Permission, require_permission
from ...security import SessionUser
from .details import details_service
from .service import service


router = APIRouter(prefix="/api/storage", tags=["storage-manager"], include_in_schema=False)


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


@router.get("/details")
def details(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    inventory = service()
    roots = inventory.block_devices()
    mounted = inventory.filesystems()
    health = inventory.device_health(roots)
    return details_service().snapshot(devices=roots, filesystems=mounted, health=health)


@router.get("/lvm")
def lvm(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    return {"read_only": True, "lvm": details_service().lvm()}


@router.get("/mounts")
def mounts(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    inventory = service()
    roots = inventory.block_devices()
    mounted = inventory.filesystems()
    return details_service().mounts(filesystems=mounted, devices=roots)


@router.get("/io")
def io(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    roots = service().block_devices()
    return details_service().io_sample(roots)


@router.get("/pools")
def pools(user: SessionUser = Depends(require_permission(Permission.MODULES_VIEW))):
    del user
    mounted = service().filesystems()
    return {"read_only": True, **details_service().pools(mounted)}


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
