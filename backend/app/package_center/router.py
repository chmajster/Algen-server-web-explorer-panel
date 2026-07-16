from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..audit import logger
from ..identity.permissions import Permission, authorize
from ..security import SessionUser
from .jobs import manager
from .models import AdminPackageAction, PackageAction, PackageSourceInput, api_error
from .security import current_user, mutating_user, reauthenticate
from .service import categories, get_module, list_modules, plan_operation, repository

router = APIRouter(prefix="/api/apps", tags=["package-center"])


@router.get("")
def modules(
    search: str = "",
    category: str = "",
    status: str = "",
    compatible_only: bool = False,
    installed_only: bool = False,
    updates_only: bool = False,
    user: SessionUser = Depends(current_user),
):
    authorize(user, Permission.MODULES_VIEW)
    return list_modules(search=search, category=category, status=status, compatible_only=compatible_only, installed_only=installed_only, updates_only=updates_only)


@router.get("/categories")
def module_categories(user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return categories()


@router.get("/installed")
def installed_modules(user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return list_modules(installed_only=True)


@router.get("/updates")
def module_updates(user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return list_modules(updates_only=True)


@router.get("/jobs")
def package_jobs(status: str | None = None, module_id: str | None = None, limit: int = Query(200, ge=1, le=500), user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return repository().list_jobs(status=status, module_id=module_id, limit=limit)


@router.get("/jobs/{job_id}")
def package_job(job_id: str, user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    job = repository().get_job(job_id)
    if not job:
        api_error(404, "JOB_NOT_FOUND", "Package job not found")
    return job


@router.get("/jobs/{job_id}/events")
async def package_job_events(job_id: str, user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    async def events():
        last = ""
        while True:
            job = repository().get_job(job_id)
            if not job:
                yield 'event: error\ndata: {"code":"JOB_NOT_FOUND"}\n\n'
                return
            payload = json.dumps(job, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if job["status"] in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.75)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    existing = repository().get_job(job_id)
    if not existing:
        api_error(404, "JOB_NOT_FOUND", "Package job not found")
    authorize(user, _package_permission(PackageAction(existing["action"])))
    reauthenticate(user, payload.admin_password)
    job = manager(repository()).cancel(job_id)
    logger.info("package_action actor=%s module=%s action=cancel job=%s", user.username, job["module_id"], job_id)
    return job


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    existing = repository().get_job(job_id)
    if not existing:
        api_error(404, "JOB_NOT_FOUND", "Package job not found")
    authorize(user, _package_permission(PackageAction(existing["action"])))
    reauthenticate(user, payload.admin_password)
    return manager(repository()).retry(job_id, user.username)


@router.get("/history")
def package_history(limit: int = Query(300, ge=1, le=1000), user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return repository().history(limit)


@router.get("/sources")
def package_sources(user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_INSTALL)
    return repository().list_sources()


@router.post("/sources")
def create_source(payload: PackageSourceInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_INSTALL)
    source = repository().create_source(payload)
    logger.info("package_source actor=%s action=create source=%s", user.username, source["id"])
    return source


@router.put("/sources/{source_id}")
def update_source(source_id: str, payload: PackageSourceInput, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_INSTALL)
    source = repository().update_source(source_id, payload)
    if not source:
        api_error(404, "SOURCE_NOT_FOUND", "Package source not found")
    logger.info("package_source actor=%s action=update source=%s", user.username, source_id)
    return source


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_INSTALL)
    if not repository().delete_source(source_id):
        api_error(404, "SOURCE_NOT_FOUND", "Package source not found")
    logger.info("package_source actor=%s action=delete source=%s", user.username, source_id)
    return {"ok": True}


@router.post("/sources/{source_id}/sync")
def sync_source(source_id: str, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_INSTALL)
    source = next((item for item in repository().list_sources() if item["id"] == source_id), None)
    if not source:
        api_error(404, "SOURCE_NOT_FOUND", "Package source not found")
    parsed = urlparse(source["github_url"])
    owner, repo_name = parsed.path.strip("/").split("/")
    request = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo_name}", headers={"Accept": "application/vnd.github+json", "User-Agent": "WebNAS-Package-Center"})
    try:
        # The request URL always uses the fixed api.github.com HTTPS host.
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
            data = json.loads(response.read(1_000_000).decode("utf-8"))
        metadata = {key: data.get(key) for key in ("full_name", "description", "default_branch", "updated_at", "stargazers_count")}
        result = repository().sync_source(source_id, metadata=metadata)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
        result = repository().sync_source(source_id, error=str(error)[:500])
    logger.info("package_source actor=%s action=sync source=%s result=%s", user.username, source_id, "ok" if result and not result["validation_error"] else "failed")
    return result


@router.get("/{module_id}/logs")
def module_logs(module_id: str, user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_LOGS)
    get_module(module_id)
    jobs = repository().list_jobs(module_id=module_id, limit=20)
    return {"jobs": jobs, "lines": [entry["line"] for job in reversed(jobs) for entry in job["log_tail"]][-500:]}


@router.post("/{module_id}/plan")
def package_plan(module_id: str, action: PackageAction = PackageAction.install, remove_data: bool = False, user: SessionUser = Depends(mutating_user)):
    authorize(user, _package_permission(action))
    return plan_operation(module_id, action, remove_data=remove_data)


def _package_permission(action: PackageAction) -> Permission:
    if action == PackageAction.install:
        return Permission.MODULES_INSTALL
    if action == PackageAction.update:
        return Permission.MODULES_UPDATE
    if action == PackageAction.uninstall:
        return Permission.MODULES_UNINSTALL
    return Permission.MODULES_CONFIGURE


def _enqueue_action(module_id: str, action: PackageAction, payload: AdminPackageAction, user: SessionUser) -> dict:
    if not payload.confirm_plan:
        api_error(400, "PLAN_CONFIRMATION_REQUIRED", "The operation plan must be confirmed")
    reauthenticate(user, payload.admin_password)
    plan = plan_operation(module_id, action, remove_data=payload.remove_data)
    return {"job": manager(repository()).enqueue(plan, user.username)}


@router.post("/{module_id}/install")
def install_module(module_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_INSTALL)
    return _enqueue_action(module_id, PackageAction.install, payload, user)


@router.post("/{module_id}/update")
def update_module(module_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_UPDATE)
    return _enqueue_action(module_id, PackageAction.update, payload, user)


@router.post("/{module_id}/uninstall")
def uninstall_module(module_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_UNINSTALL)
    return _enqueue_action(module_id, PackageAction.uninstall, payload, user)


@router.post("/{module_id}/start")
def start_module(module_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    return _enqueue_action(module_id, PackageAction.start, payload, user)


@router.post("/{module_id}/stop")
def stop_module(module_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    return _enqueue_action(module_id, PackageAction.stop, payload, user)


@router.post("/{module_id}/restart")
def restart_module(module_id: str, payload: AdminPackageAction, user: SessionUser = Depends(mutating_user)):
    authorize(user, Permission.MODULES_CONFIGURE)
    return _enqueue_action(module_id, PackageAction.restart, payload, user)


@router.get("/{module_id}")
def module_detail(module_id: str, user: SessionUser = Depends(current_user)):
    authorize(user, Permission.MODULES_VIEW)
    return get_module(module_id)
