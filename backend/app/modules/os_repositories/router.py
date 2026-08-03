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
from ..hosts_manager.service import registry as hosts_registry
from .jobs import manager
from .models import (
    BackupInput,
    CancelInput,
    ChannelName,
    FilterRuleInput,
    FullRemoveInput,
    HostAssignmentInput,
    PackageBuildInput,
    PromotionInput,
    RepositoryInput,
    RestoreInput,
    RollbackInput,
    SettingsInput,
    SigningKeyGenerateInput,
    SigningKeyInput,
    SnapshotInput,
    SyncInput,
)
from .security import managed_path
from .service import service

router = APIRouter(prefix="/api/modules/os-repositories", tags=["os-repositories"])


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
    return service().dashboard()


@router.get("/repositories")
def repositories(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=128),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return service().repositories(page, page_size, search)


@router.post("/repositories")
def create_repository(payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return controlled(lambda: service().save_repository(payload, user.username))


@router.get("/repositories/{repository_id}")
def repository(repository_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = service().repository(repository_id)
    if not item:
        api_error(404, "REPOSITORY_NOT_FOUND", "Repository not found")
    return item


@router.put("/repositories/{repository_id}")
def update_repository(repository_id: str, payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return controlled(lambda: service().save_repository(payload, user.username, repository_id))


@router.delete("/repositories/{repository_id}")
def delete_repository(repository_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return {"ok": controlled(lambda: service().delete_repository(repository_id, user.username))}


@router.post("/repositories/{repository_id}/plan")
def repository_plan(
    repository_id: str, payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE, mutating=False))
):
    ready()
    current = service().repository(repository_id)
    return {
        "repository_id": repository_id,
        "action": "update" if current else "create",
        "format": payload.format,
        "kind": payload.kind,
        "source": payload.source_url,
        "architectures": payload.architectures,
        "warnings": ["HTTP private mirror explicitly approved"] if payload.allow_private_http else [],
        "requires_confirmation": True,
    }


@router.post("/repositories/{repository_id}/filters/preview")
def preview_filter(
    repository_id: str, payload: FilterRuleInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))
):
    ready()
    return controlled(lambda: service().filter_preview(repository_id, payload))


@router.post("/repositories/{repository_id}/filters")
def save_filter(repository_id: str, payload: FilterRuleInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_MANAGE))):
    ready()
    return controlled(lambda: service().save_filter(repository_id, payload, user.username))


@router.post("/repositories/{repository_id}/sync")
def sync_repository(repository_id: str, payload: SyncInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SYNC))):
    ready()
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Synchronization requires confirmation")
    return controlled(lambda: manager().enqueue_sync(repository_id, user.username))


@router.get("/repositories/{repository_id}/packages")
def repository_packages(
    repository_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=128),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return service().packages(page, page_size, search, repository_id)


@router.get("/packages")
def packages(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=128),
    repository_id: str = Query("", max_length=32),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return service().packages(page, page_size, search, repository_id)


@router.post("/packages/upload")
async def upload_package(
    repository_id: str, file: UploadFile = File(...), user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_PACKAGES_UPLOAD))
):
    ready()
    try:
        return controlled(lambda: service().upload_package(repository_id, Path(file.filename or "upload").name, file.file, user.username))
    finally:
        await file.close()


@router.get("/packages/{package_id}")
def package(package_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = service().package(package_id)
    if not item:
        api_error(404, "PACKAGE_NOT_FOUND", "Package not found")
    return item


@router.get("/packages/{package_id}/download")
def package_download(package_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = service().package(package_id)
    if not item:
        api_error(404, "PACKAGE_NOT_FOUND", "Package not found")
    path = managed_path(service().root, item["relative_path"])
    if not path.is_file():
        api_error(404, "PACKAGE_FILE_MISSING", "Package file is missing")
    return FileResponse(path, filename=path.name, media_type="application/vnd.debian.binary-package" if item["format"] == "apt" else "application/x-rpm")


@router.delete("/packages/{package_id}")
def package_delete(package_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_PACKAGES_DELETE))):
    ready()
    return {"ok": controlled(lambda: service().delete_package(package_id, user.username))}


@router.get("/snapshots")
def snapshots(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    repository_id: str = Query("", max_length=32),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return service().snapshots(page, page_size, repository_id)


@router.post("/repositories/{repository_id}/snapshots")
def create_snapshot(repository_id: str, payload: SnapshotInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    return controlled(lambda: service().create_snapshot(repository_id, payload, user.username))


@router.get("/snapshots/{snapshot_id}")
def snapshot(snapshot_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = service().snapshot(snapshot_id)
    if not item:
        api_error(404, "SNAPSHOT_NOT_FOUND", "Snapshot not found")
    return item


@router.delete("/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    return {"ok": controlled(lambda: service().delete_snapshot(snapshot_id, user.username))}


@router.get("/snapshots/{snapshot_id}/compare")
def compare(
    snapshot_id: str,
    other: str = Query(..., min_length=32, max_length=32),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return controlled(lambda: service().compare_snapshots(snapshot_id, other))


@router.get("/channels")
def channels(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return service().channels()


@router.post("/channels/{channel_id}/promote")
def promote(channel_id: str, payload: PromotionInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    channel = service().store.one("SELECT * FROM channels WHERE id=?", (channel_id,))
    if not channel:
        api_error(404, "CHANNEL_NOT_FOUND", "Channel not found")
    if channel["name"] == "production":
        authorize(user, Permission.OS_REPOSITORIES_CHANNELS_PROMOTE)
        if not payload.confirm or payload.confirmation_text != "Production":
            api_error(422, "CONFIRMATION_REQUIRED", "Production promotion requires typing Production")
    elif not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Channel publication requires confirmation")
    return controlled(lambda: service().publish(channel["repository_id"], ChannelName(channel["name"]), payload.snapshot_id, user.username))


@router.get("/channels/{channel_id}/plan")
def channel_plan(
    channel_id: str,
    snapshot_id: str = Query(..., min_length=32, max_length=32),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return controlled(lambda: service().channel_plan(channel_id, snapshot_id))


@router.post("/channels/{channel_id}/rollback")
def rollback(channel_id: str, payload: RollbackInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SNAPSHOTS_MANAGE))):
    ready()
    channel = service().store.one("SELECT * FROM channels WHERE id=?", (channel_id,))
    if not channel:
        api_error(404, "CHANNEL_NOT_FOUND", "Channel not found")
    if channel["name"] == "production":
        authorize(user, Permission.OS_REPOSITORIES_CHANNELS_PROMOTE)
        if payload.confirmation_text != "Production":
            api_error(422, "CONFIRMATION_REQUIRED", "Production rollback requires typing Production")
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Channel rollback requires confirmation")
    return controlled(lambda: service().rollback_channel(channel_id, user.username))


@router.get("/builds")
def builds(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return service().builds()


@router.post("/builds")
def build(payload: PackageBuildInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_PACKAGES_BUILD))):
    ready()
    return controlled(lambda: service().build_package(payload, user.username))


@router.get("/keys")
def keys(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_KEYS_VIEW, mutating=False))):
    ready()
    return service().keys()


@router.post("/keys")
def create_key(payload: SigningKeyInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_KEYS_MANAGE))):
    ready()
    return controlled(lambda: service().save_key(payload, user.username))


@router.post("/keys/generate")
def generate_key(payload: SigningKeyGenerateInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_KEYS_MANAGE))):
    ready()
    return controlled(lambda: service().generate_key(payload, user.username))


@router.get("/keys/{key_id}")
def key(key_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_KEYS_VIEW, mutating=False))):
    ready()
    item = service().key(key_id)
    if not item:
        api_error(404, "KEY_NOT_FOUND", "Signing key not found")
    return item


@router.get("/keys/{key_id}/export")
def export_key(key_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_KEYS_VIEW, mutating=False))):
    ready()
    item = service().key(key_id)
    if not item:
        api_error(404, "KEY_NOT_FOUND", "Signing key not found")
    return {"id": item["id"], "name": item["name"], "fingerprint": item["fingerprint"], "public_key": item["public_key"]}


@router.delete("/keys/{key_id}")
def delete_key(key_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_KEYS_MANAGE))):
    ready()
    return {"ok": controlled(lambda: service().delete_key(key_id, user.username))}


@router.get("/host-assignments")
def assignments(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return service().assignments()


@router.post("/host-assignments")
def assign(payload: HostAssignmentInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_HOSTS_ASSIGN))):
    ready()
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Host assignment requires confirmation")
    registry = hosts_registry()
    if payload.host_id and not registry.host(payload.host_id):
        api_error(404, "HOST_NOT_FOUND", "Host was not found in Hosts Manager")
    if payload.group_id and not any(item["id"] == payload.group_id for item in registry.list_groups()):
        api_error(404, "GROUP_NOT_FOUND", "Host group was not found in Hosts Manager")
    return controlled(lambda: service().save_assignment(payload, user.username))


@router.get("/host-assignments/{assignment_id}/configuration")
def assignment_configuration(assignment_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return controlled(lambda: service().host_configuration(assignment_id))


@router.delete("/host-assignments/{assignment_id}")
def delete_assignment(assignment_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_HOSTS_ASSIGN))):
    ready()
    return {"ok": controlled(lambda: service().delete_assignment(assignment_id, user.username))}


@router.get("/jobs")
def jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("", pattern=r"^(|queued|running|completed|failed|cancelled)$"),
    user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False)),
):
    ready()
    return manager().jobs(page, page_size, status)


@router.get("/jobs/{job_id}")
def job(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    item = manager().job(job_id)
    if not item:
        api_error(404, "JOB_NOT_FOUND", "Job not found")
    return item


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()

    async def events():
        previous = ""
        while True:
            item = manager().job(job_id)
            if not item:
                yield 'event: error\ndata: {"code":"JOB_NOT_FOUND"}\n\n'
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
def cancel_job(job_id: str, payload: CancelInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_JOBS_CANCEL))):
    ready()
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Job cancellation requires confirmation")
    return controlled(lambda: manager().cancel(job_id, user.username))


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_SYNC))):
    ready()
    return controlled(lambda: manager().retry(job_id, user.username))


@router.get("/history")
def history(limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return service().history(limit)


@router.get("/settings")
def settings(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return service().settings()


@router.put("/settings")
def save_settings(payload: SettingsInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_CONFIGURE))):
    ready()
    return controlled(lambda: service().save_settings(payload, user.username))


@router.get("/backups")
def backups(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_BACKUP, mutating=False))):
    ready()
    return service().backups()


@router.post("/backups")
def backup(payload: BackupInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_BACKUP))):
    ready()
    return controlled(lambda: service().create_backup(payload, user.username))


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: str, payload: RestoreInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_RESTORE))):
    ready()
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Restore requires confirmation")
    return controlled(lambda: service().restore_backup(backup_id, payload.checksum, payload.confirmation_text, user.username, payload.private_keys_passphrase))


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_VIEW, mutating=False))):
    ready()
    return service().diagnostics()


@router.post("/full-remove")
def full_remove(payload: FullRemoveInput, user: SessionUser = Depends(require_permission(Permission.OS_REPOSITORIES_FULL_REMOVE))):
    ready()
    return controlled(lambda: service().full_remove(payload.confirmation_text, payload.force, user.username))


from .host_capabilities import register_host_capability  # noqa: E402

register_host_capability()
