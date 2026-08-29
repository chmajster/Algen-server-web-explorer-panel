from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ...identity.permissions import Permission, authorize, require_permission
from ...package_center.models import api_error
from ...package_center.service import repository as package_repository
from ...security import SessionUser
from .offline_jobs import offline_job_manager
from .offline_models import BundlePinInput, OfflineExportInput, OfflineImportInput, OfflineSettingsInput, OfflineTargetInput
from .offline_service import offline_service

router = APIRouter(prefix="/api/modules/os-repositories/offline", tags=["os-repositories-offline"])


def ready() -> None:
    if "os-repositories" not in package_repository().installed():
        api_error(404, "MODULE_NOT_INSTALLED", "Repozytoria systemowe module is not installed")


def controlled(operation):
    try:
        return operation()
    except KeyError as error:
        api_error(404, "RESOURCE_NOT_FOUND", str(error).strip("'"))
    except ValueError as error:
        api_error(422, "INVALID_OPERATION", str(error))
    except RuntimeError as error:
        api_error(409, "OPERATION_UNAVAILABLE", str(error))


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return offline_service().dashboard()


@router.get("/settings")
def settings(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return offline_service().settings()


@router.put("/settings")
def save_settings(payload: OfflineSettingsInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_CONFIGURE))):
    ready()
    return controlled(lambda: offline_service().save_settings(payload, user.username))


@router.get("/targets")
def targets(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return offline_service().targets()


@router.post("/targets")
def create_target(payload: OfflineTargetInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return controlled(lambda: offline_service().save_target(payload, user.username))


@router.get("/targets/{target_id}")
def target(target_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = offline_service().target(target_id)
    if not item:
        api_error(404, "OFFLINE_TARGET_NOT_FOUND", "Offline repository target not found")
    return item


@router.put("/targets/{target_id}")
def update_target(target_id: str, payload: OfflineTargetInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return controlled(lambda: offline_service().save_target(payload, user.username, target_id))


@router.delete("/targets/{target_id}")
def delete_target(target_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return {"ok": controlled(lambda: offline_service().delete_target(target_id, user.username))}


@router.post("/exports/plan")
def export_plan(payload: OfflineExportInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return controlled(lambda: offline_service().plan_export(payload))


@router.post("/exports")
def create_export(payload: OfflineExportInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Offline bundle export requires confirmation")
    return controlled(lambda: offline_job_manager().enqueue_export(payload, user.username))


@router.get("/bundles")
def bundles(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return offline_service().bundles(page, page_size)


@router.get("/bundles/{bundle_id}")
def bundle(bundle_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = offline_service().bundle(bundle_id)
    if not item:
        api_error(404, "OFFLINE_BUNDLE_NOT_FOUND", "Offline bundle not found")
    return item


@router.get("/bundles/{bundle_id}/download")
def download_bundle(bundle_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    path = controlled(lambda: offline_service().bundle_path(bundle_id))
    assert isinstance(path, Path)
    return FileResponse(path, filename=path.name, media_type="application/gzip")


@router.put("/bundles/{bundle_id}/pin")
def pin_bundle(bundle_id: str, payload: BundlePinInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return controlled(lambda: offline_service().pin_bundle(bundle_id, payload, user.username))


@router.delete("/bundles/{bundle_id}")
def delete_bundle(
    bundle_id: str,
    force: bool = Query(False),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_PACKAGES_DELETE)),
):
    ready()
    return {"ok": controlled(lambda: offline_service().delete_bundle(bundle_id, user.username, force=force))}


@router.get("/imports/staged")
def staged_bundles(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return {"items": offline_service().discover_staged()}


@router.post("/imports/upload")
async def upload_bundle(file: UploadFile = File(...), user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_PACKAGES_UPLOAD))):
    ready()
    try:
        return controlled(lambda: offline_service().stage_upload(Path(file.filename or "bundle.tar.gz").name, file.file))
    finally:
        await file.close()


@router.get("/imports/{staged_id}/inspect")
def inspect_bundle(staged_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return controlled(lambda: offline_service().inspect_staged(staged_id))


@router.post("/imports/{staged_id}/verify")
def verify_bundle(
    staged_id: str,
    repository_id: str = Query(..., min_length=32, max_length=32),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW)),
):
    ready()
    return controlled(lambda: offline_job_manager().enqueue_verify(staged_id, repository_id, user.username))


@router.post("/imports/{staged_id}")
def import_bundle(staged_id: str, payload: OfflineImportInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_PACKAGES_UPLOAD))):
    ready()
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Offline bundle import requires confirmation")
    if payload.publish_channel and payload.publish_channel.value == "production":
        authorize(user, Permission.OS_REPOSITORIES_CHANNELS_PROMOTE)
    return controlled(lambda: offline_job_manager().enqueue_import(staged_id, payload, user.username))


@router.get("/delta/plan")
def delta_plan(
    base_snapshot_id: str = Query(..., min_length=32, max_length=32),
    target_snapshot_id: str = Query(..., min_length=32, max_length=32),
    architecture: str = Query(..., min_length=1, max_length=32),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return controlled(lambda: offline_service().delta_plan(base_snapshot_id, target_snapshot_id, architecture))


@router.post("/snapshots/{snapshot_id}/freeze")
def freeze_snapshot(snapshot_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    return controlled(lambda: offline_service().freeze_snapshot(snapshot_id, user.username))


@router.get("/storage")
def storage(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return offline_service().storage()


@router.get("/jobs")
def offline_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("", pattern=r"^(|queued|running|completed|failed|cancelled)$"),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return offline_job_manager().jobs(page, page_size, status)


@router.get("/jobs/{job_id}")
def offline_job(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = offline_job_manager().job(job_id)
    if not item:
        api_error(404, "OFFLINE_JOB_NOT_FOUND", "Offline repository job not found")
    return item


@router.get("/jobs/{job_id}/events")
async def offline_job_events(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()

    async def events():
        previous = ""
        while True:
            item = offline_job_manager().job(job_id)
            if not item:
                yield 'event: error\ndata: {"code":"OFFLINE_JOB_NOT_FOUND"}\n\n'
                return
            data = json.dumps(item, ensure_ascii=False)
            if data != previous:
                yield f"data: {data}\n\n"
                previous = data
            if item["status"] in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.75)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/jobs/{job_id}/cancel")
def cancel_offline_job(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_JOBS_CANCEL))):
    ready()
    return controlled(lambda: offline_job_manager().cancel(job_id, user.username))


@router.post("/jobs/{job_id}/retry")
def retry_offline_job(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    return controlled(lambda: offline_job_manager().retry(job_id, user.username))
