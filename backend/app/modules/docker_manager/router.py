from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ...activity import ActivityCategory, record_activity
from ...auth import authenticate
from ...identity.permissions import authorize, has_permission
from ...package_center.jobs import manager
from ...package_center.executor import SAFE_ENV, redact
from ...package_center.models import PackageAction, PackagePlan, api_error
from ...package_center.service import get_module, plan_operation, repository
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from ..providers import DockerProvider
from .models import (
    AppActionRequest,
    AppInstallRequest,
    ComposeActionRequest,
    ComposeSaveRequest,
    ContainerDefaultsPolicy,
    ContainerActionRequest,
    ContainerCreateRequest,
    ContainerFilesystemImportRequest,
    ContainerRestoreRequest,
    ContainerSettingsRequest,
    DaemonConfigRequest,
    DefaultBridgeConfigRequest,
    EngineActionRequest,
    ImageActionRequest,
    NetworkActionRequest,
    NetworkCreateRequest,
    PrunePlanRequest,
    RegistryCatalogResponse,
    RegistryRequest,
    RegistrySource,
    RegistryTagsResponse,
    VolumeActionRequest,
    VolumeCreateRequest,
    validate_repository,
)
from .storage import store


router = APIRouter(prefix="/api/modules/docker", tags=["containers-manager"])
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
REVISION_RE = re.compile(r"^[0-9]{10,16}-[a-f0-9]{12}$")
PUBLIC_DOCKER_HUB = {
    "id": "docker-hub-public",
    "name": "Docker Hub",
    "provider": "docker_hub",
    "server": "docker.io",
    "username": "",
    "tls": True,
    "ca_certificate_configured": False,
    "secret_configured": False,
    "built_in": True,
    "public_access": True,
    "created_at": 0,
    "updated_at": 0,
}


def _provider(user: SessionUser) -> DockerProvider:
    return DockerProvider(user.username)


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _allow_any(user: SessionUser, *permissions: str) -> None:
    if any(has_permission(user.username, permission) for permission in permissions):
        return
    authorize(user, permissions[0])


def _catalog_registry(registry_id: str) -> tuple[dict, dict[str, str] | None]:
    if registry_id == PUBLIC_DOCKER_HUB["id"]:
        return PUBLIC_DOCKER_HUB, None
    if not re.fullmatch(r"[a-f0-9]{24}", registry_id):
        api_error(422, "INVALID_REGISTRY_ID", "Invalid registry identifier")
    return store().public_registry(registry_id), store().registry_credentials(registry_id)


def _enqueue(operation: str, payload: dict, user: SessionUser, *, warning: str = "") -> dict:
    module = get_module("docker")
    if module["blocked_by_proxmox"]:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Docker mutations are blocked by Proxmox Safe Mode")
    provider = DockerProvider(user.username)
    if operation not in provider.manifest.capabilities.actions:
        api_error(400, "DOCKER_ACTION_NOT_SUPPORTED", "Unsupported Docker operation")
    plan = PackagePlan(
        module_id="docker",
        action=PackageAction.manage,
        distribution=module["distribution"],
        compatible=bool(module["compatible"]),
        blocked_by_proxmox=bool(module["blocked_by_proxmox"]),
        services=provider.manifest.systemd_services,
        config_paths=provider.manifest.config_paths,
        warnings=[warning] if warning else [],
        steps=["Validate typed request", "Execute controlled Docker operation", "Verify Docker state", "Write audit result"],
        payload={**payload, "operation": operation},
    )
    job = manager(repository()).enqueue(plan, user.username)
    return {"job": job}


def _critical(user: SessionUser, *, password: str | None, confirmation: str, expected: str, permission: str = "docker.high_risk") -> None:
    _allow(user, permission)
    if confirmation != expected:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "The exact resource name must be entered", expected=expected)
    if not password:
        api_error(400, "PAM_CONFIRMATION_REQUIRED", "Current account password is required")
    authenticate(user.username, password)


def _project(value: str) -> str:
    if not PROJECT_RE.fullmatch(value):
        api_error(400, "INVALID_COMPOSE_PROJECT", "Invalid Compose project name")
    return value


def _assert_mutation_allowed() -> None:
    if get_module("docker")["blocked_by_proxmox"]:
        api_error(403, "MODULE_BLOCKED_BY_PROXMOX", "Docker mutations are blocked by Proxmox Safe Mode")


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view")
    return _provider(user).dashboard()


@router.get("/engine")
def engine(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view")
    provider = _provider(user)
    return {"status": provider.get_status(), "config": provider.get_config(), "diagnostics": [item.model_dump(mode="json") for item in provider.run_diagnostics()]}


@router.get("/policy/container-defaults")
def container_defaults_policy(user: SessionUser = Depends(current_user)):
    _allow_any(user, "docker.view", "docker.create_container")
    return ContainerDefaultsPolicy.model_validate(store().container_defaults_policy())


@router.put("/policy/container-defaults")
def save_container_defaults_policy(payload: ContainerDefaultsPolicy, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.update_engine")
    return store().save_container_defaults_policy(payload.model_dump(mode="json"))


@router.post("/engine/actions")
def engine_action(payload: EngineActionRequest, user: SessionUser = Depends(mutating_user)):
    permissions = {
        "install": "docker.install_engine", "reinstall": "docker.install_engine", "update": "docker.update_engine",
        "start": "docker.start_service", "stop": "docker.stop_service", "restart": "docker.start_service",
        "enable": "docker.start_service", "disable": "docker.stop_service", "test": "docker.diagnostics",
    }
    _allow(user, permissions[payload.action])
    if payload.action in {"install", "reinstall", "update", "stop", "restart", "disable"}:
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=f"docker:{payload.action}", permission=permissions[payload.action])
    if payload.action == "test":
        provider = _provider(user)
        return {"diagnostics": [item.model_dump(mode="json") for item in provider.run_diagnostics()]}
    package_action = PackageAction(payload.action)
    plan = plan_operation("docker", package_action)
    job = manager(repository()).enqueue(plan, user.username)
    return {"job": job}


@router.get("/daemon-config")
def daemon_config(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view")
    return _provider(user).get_config()


@router.post("/daemon-config/validate")
def validate_daemon_config(payload: DaemonConfigRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.update_engine")
    return _provider(user).validate_config(payload.config)


@router.put("/daemon-config")
def save_daemon_config(payload: DaemonConfigRequest, user: SessionUser = Depends(mutating_user)):
    _assert_mutation_allowed()
    _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected="daemon.json", permission="docker.update_engine")
    validation = _provider(user).validate_config(payload.config)
    if not validation.ok:
        api_error(422, "CONFIG_VALIDATION_FAILED", "Docker daemon configuration is invalid", errors=validation.errors)
    module = get_module("docker")
    plan = PackagePlan(module_id="docker", action=PackageAction.apply, distribution=module["distribution"], compatible=bool(module["compatible"]), blocked_by_proxmox=bool(module["blocked_by_proxmox"]), services=["docker"], config_paths=["/etc/docker/daemon.json"], steps=["Validate daemon.json", "Create backup", "Write atomically", "Restart Docker", "Verify or roll back"], payload={"config": payload.config}, create_backup=True)
    return {"job": manager(repository()).enqueue(plan, user.username), "validation": validation}


@router.get("/containers")
def containers(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), search: str = "", state: Literal["all", "created", "running", "paused", "restarting", "removing", "exited", "dead"] = "all", sort: str = "Names", direction: Literal["asc", "desc"] = "asc", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_containers")
    return _provider(user).containers(page=page, page_size=page_size, search=search[:200], state=state, sort=sort[:32], direction=direction)


@router.post("/containers")
def create_container(payload: ContainerCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.create_container")
    if payload.confirmation != payload.name:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the container name to create it", expected=payload.name)
    input_ref = store().stage_input({"environment": payload.secret_environment}) if payload.secret_environment else ""
    definition = payload.model_dump(mode="json", exclude={"secret_environment", "confirmation"})
    try:
        return _enqueue("container_create", {"definition": definition, "input_ref": input_ref}, user)
    except Exception:
        store().discard_input(input_ref)
        raise


@router.post("/containers/import")
async def import_container_filesystem(
    file: UploadFile = File(...),
    repository: str = Form(...),
    confirmation: str = Form(...),
    user: SessionUser = Depends(mutating_user),
):
    _allow(user, "docker.restore_backup")
    _assert_mutation_allowed()
    payload = ContainerFilesystemImportRequest(repository=repository, confirmation=confirmation)
    if payload.confirmation != payload.repository:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the target image reference to import the container filesystem", expected=payload.repository)
    if not file.filename or not file.filename.lower().endswith((".tar", ".tar.gz", ".tgz")):
        api_error(422, "INVALID_CONTAINER_ARCHIVE", "Container filesystem import requires a tar archive")
    filename = f"container-upload-{int(time.time())}-{hashlib.sha256(file.filename.encode()).hexdigest()[:12]}.tar"
    target = store().artifacts_dir / filename
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 20 * 1024 * 1024 * 1024:
                    api_error(413, "CONTAINER_ARCHIVE_TOO_LARGE", "Container archive exceeds 20 GiB")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(target, 0o600)
        artifact = store().register_artifact(target, kind="container_filesystem_upload", display_name=file.filename[:200], actor=user.username)
        input_ref = store().stage_input({"artifact_id": artifact["id"], "repository": payload.repository})
        return _enqueue("container_import", {"input_ref": input_ref}, user)
    except Exception:
        target.unlink(missing_ok=True)
        raise


@router.get("/containers/{target}/stats")
def container_stats(target: str, history_hours: int = Query(1, ge=1, le=168), user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_stats")
    provider = _provider(user)
    current = provider.current_stats(target)
    container_id = str(current[0]["container_id"]) if current else str(provider.container_details(target)["id"])[:12]
    return {"current": current[0] if current else None, "history": store().stats(container_id, since=time.time() - history_hours * 3600)}


@router.get("/containers/{target}/logs")
def container_logs(target: str, tail: int = Query(500, ge=1, le=5000), since: str = "", until: str = "", search: str = "", level: str = "", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_logs")
    return _provider(user).container_logs(target, tail=tail, since=since[:40], until=until[:40], search=search[:200], level=level[:32])


@router.get("/containers/{target}/logs/stream")
def container_logs_stream(target: str, tail: int = Query(200, ge=0, le=1000), user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_logs")
    provider = _provider(user)
    normalized = provider._checked_identifier(target, "container")
    executable = shutil.which("docker")
    if not executable:
        api_error(409, "DOCKER_UNAVAILABLE", "Docker CLI is unavailable")

    def stream() -> Iterator[str]:
        messages: queue.Queue[str | None] = queue.Queue(maxsize=1000)
        process = subprocess.Popen(
            [executable, "logs", "--follow", "--tail", str(tail), "--timestamps", normalized],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            shell=False,
            env=SAFE_ENV,
            start_new_session=True,
        )

        def read() -> None:
            try:
                if process.stdout:
                    for line in process.stdout:
                        try:
                            messages.put(redact(line.rstrip()), timeout=1)
                        except queue.Full:
                            continue
            finally:
                try:
                    messages.put(None, timeout=1)
                except queue.Full:
                    pass

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while True:
                try:
                    line = messages.get(timeout=15)
                except queue.Empty:
                    if process.poll() is not None:
                        yield "event: end\ndata: {}\n\n"
                        break
                    yield ": keep-alive\n\n"
                    continue
                if line is None:
                    yield "event: end\ndata: {}\n\n"
                    break
                yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            reader.join(timeout=2)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/containers/{target}/processes")
def container_processes(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.inspect_container")
    return _provider(user).container_processes(target)


@router.get("/containers/{target}/compose")
def container_compose(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.inspect_container")
    return _provider(user).generate_compose(target)


@router.get("/containers/{target}/settings")
def container_settings(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.inspect_container")
    return _provider(user).container_settings(target)


@router.put("/containers/{target}/settings")
def update_container_settings(target: str, payload: ContainerSettingsRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.create_container")
    if payload.confirmation != target:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the current container name to update its settings", expected=target)
    settings = payload.model_dump(mode="json", exclude={"confirmation"})
    return _enqueue("container_settings", {"target": target, "settings": settings}, user, warning="Resource and restart settings are applied to the running container")


@router.get("/containers/{target}")
def container_detail(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.inspect_container")
    return _provider(user).container_details(target)


@router.post("/containers/{target}/actions")
def container_action(target: str, payload: ContainerActionRequest, user: SessionUser = Depends(mutating_user)):
    permission = {
        "start": "docker.start_container", "stop": "docker.stop_container", "restart": "docker.restart_container",
        "pause": "docker.stop_container", "unpause": "docker.start_container", "kill": "docker.stop_container",
        "rename": "docker.create_container", "remove": "docker.remove_container", "duplicate": "docker.create_container",
        "recreate": "docker.create_container", "check_update": "docker.pull_image", "update": "docker.pull_image",
    }[payload.action]
    _allow(user, permission)
    if payload.action == "remove" and payload.force:
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=target)
    elif payload.action in {"remove", "kill", "recreate", "update"} and payload.confirmation != target:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the container name to confirm the operation", expected=target)
    operation_payload = payload.model_dump(mode="json", exclude={"action", "pam_password", "confirmation"})
    return _enqueue(f"container_{payload.action}", {"target": target, **operation_payload}, user, warning="The operation may briefly interrupt container services" if payload.action in {"recreate", "update"} else "")


@router.post("/containers/{target}/export")
def export_container(target: str, confirmation: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.export_backup")
    if confirmation != target:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the container name to export it", expected=target)
    return _enqueue("container_export", {"target": target}, user)


@router.post("/containers/{target}/backup")
def backup_container(target: str, confirmation: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.export_backup")
    if confirmation != target:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the container name to back it up", expected=target)
    return _enqueue("container_backup", {"target": target}, user)


@router.get("/images")
def images(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), search: str = "", sort: str = "Repository", direction: Literal["asc", "desc"] = "asc", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_images")
    return _provider(user).images(page=page, page_size=page_size, search=search[:200], sort=sort[:32], direction=direction)


@router.get("/images/search")
def search_images(q: str = Query(min_length=2, max_length=100), limit: int = Query(25, ge=1, le=100), user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_images")
    return _provider(user).search_registry(q, limit)


@router.get("/images/details")
def image_detail(image: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_images")
    return _provider(user).image_details(image)


@router.post("/images/actions")
def image_action(payload: ImageActionRequest, user: SessionUser = Depends(mutating_user)):
    permission = "docker.pull_image" if payload.action in {"pull", "update"} else "docker.remove_image" if payload.action == "remove" else "docker.prune" if payload.action == "prune" else "docker.export_backup"
    _allow(user, permission)
    expected = payload.image or "images"
    if payload.action == "prune" or payload.force:
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=expected)
    elif payload.action in {"remove", "save"} and payload.confirmation != expected:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the image reference to confirm", expected=expected)
    data = payload.model_dump(mode="json", exclude={"action", "pam_password", "confirmation"})
    return _enqueue(f"image_{payload.action}", data, user)


@router.post("/images/import")
async def import_image(file: UploadFile = File(...), user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.restore_backup")
    _assert_mutation_allowed()
    if not file.filename or not file.filename.lower().endswith((".tar", ".tar.gz", ".tgz")):
        api_error(422, "INVALID_IMAGE_ARCHIVE", "Docker image import requires a tar archive")
    filename = f"upload-{int(time.time())}-{hashlib.sha256(file.filename.encode()).hexdigest()[:12]}.tar"
    target = store().artifacts_dir / filename
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 20 * 1024 * 1024 * 1024:
                    api_error(413, "IMAGE_ARCHIVE_TOO_LARGE", "Image archive exceeds 20 GiB")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(target, 0o600)
        artifact = store().register_artifact(target, kind="image_upload", display_name=file.filename[:200], actor=user.username)
        input_ref = store().stage_input({"artifact_id": artifact["id"]})
        return _enqueue("image_load", {"input_ref": input_ref}, user)
    except Exception:
        target.unlink(missing_ok=True)
        raise


@router.get("/registries")
def registries(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_registries")
    return {"items": [PUBLIC_DOCKER_HUB, *store().list_registries()]}


@router.get("/registries/sources", response_model=list[RegistrySource])
def registry_sources(user: SessionUser = Depends(current_user)):
    _allow_any(user, "docker.view_images", "docker.manage_registries")
    values = [PUBLIC_DOCKER_HUB, *store().list_registries()]
    return [
        {
            "id": value["id"],
            "name": value["name"],
            "provider": value["provider"],
            "server": value["server"],
            "built_in": bool(value.get("built_in")),
            "public_access": bool(value.get("public_access")),
        }
        for value in values
    ]


@router.get("/registries/catalog", response_model=RegistryCatalogResponse)
def registry_catalog(
    registry_id: str = Query(max_length=64),
    query: str = Query(min_length=2, max_length=100),
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(25, ge=1, le=100),
    official: Literal["all", "official", "unofficial"] = "all",
    sort: Literal["relevance", "name", "stars"] = "relevance",
    direction: Literal["asc", "desc"] = "desc",
    user: SessionUser = Depends(current_user),
):
    _allow_any(user, "docker.view_images", "docker.manage_registries")
    normalized_query = query.strip()
    if len(normalized_query) < 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ /-]{1,99}", normalized_query):
        api_error(422, "INVALID_REGISTRY_SEARCH", "Registry search must contain 2-100 safe characters")
    registry, credentials = _catalog_registry(registry_id)
    return _provider(user).registry_catalog(
        registry,
        credentials,
        query=normalized_query,
        page=page,
        page_size=page_size,
        official=official,
        sort=sort,
        direction=direction,
    )


@router.get("/registries/tags", response_model=RegistryTagsResponse)
def registry_tags(
    registry_id: str = Query(max_length=64),
    repository_name: str = Query(min_length=1, max_length=255),
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(100, ge=1, le=100),
    user: SessionUser = Depends(current_user),
):
    _allow_any(user, "docker.view_images", "docker.manage_registries")
    try:
        repository_name = validate_repository(repository_name)
    except ValueError:
        api_error(422, "INVALID_REGISTRY_REPOSITORY", "Invalid registry repository name")
    registry, credentials = _catalog_registry(registry_id)
    return _provider(user).registry_tags(
        registry,
        credentials,
        repository=repository_name,
        page=page,
        page_size=page_size,
    )


@router.post("/registries")
def create_registry(payload: RegistryRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_registries")
    _assert_mutation_allowed()
    value = store().save_registry(registry_id=None, **payload.model_dump())
    record_activity(ActivityCategory.module, "registry_create", user.username, target="docker", details={"registry_id": value["id"], "server": value["server"]}, source="containers-manager")
    result = _enqueue("registry_login", {"registry_id": value["id"]}, user)
    return {"registry": value, **result}


@router.put("/registries/{registry_id}")
def update_registry(registry_id: str, payload: RegistryRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_registries")
    _assert_mutation_allowed()
    value = store().save_registry(registry_id=registry_id, **payload.model_dump())
    record_activity(ActivityCategory.module, "registry_update", user.username, target="docker", details={"registry_id": value["id"], "server": value["server"]}, source="containers-manager")
    return {"registry": value, **_enqueue("registry_login", {"registry_id": value["id"]}, user)}


@router.post("/registries/{registry_id}/test")
def test_registry(registry_id: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_registries")
    return _enqueue("registry_login", {"registry_id": registry_id}, user)


@router.post("/registries/{registry_id}/logout")
def logout_registry(registry_id: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_registries")
    store().public_registry(registry_id)
    return _enqueue("registry_logout", {"registry_id": registry_id}, user)


@router.delete("/registries/{registry_id}")
def delete_registry(registry_id: str, confirmation: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_registries")
    _assert_mutation_allowed()
    value = store().public_registry(registry_id)
    if confirmation != value["name"]:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the registry name to remove it", expected=value["name"])
    credentials = store().registry_credentials(registry_id)
    provider = _provider(user)
    result = provider._run(["docker", "logout", credentials["server"]], timeout=120)
    if result.returncode not in {0, 1}:
        provider._result(result, "Could not remove Docker registry session")
    provider.configure_registry_trust(credentials["server"], "")
    store().delete_registry(registry_id)
    record_activity(ActivityCategory.module, "registry_delete", user.username, target="docker", details={"registry_id": registry_id, "server": credentials["server"]}, source="containers-manager")
    return {"ok": True}


@router.get("/volumes")
def volumes(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), search: str = "", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_volumes")
    return _provider(user).volumes(page=page, page_size=page_size, search=search[:200])


@router.post("/volumes")
def create_volume(payload: VolumeCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_volumes")
    if _provider(user).named_resource_exists("volume", payload.name):
        api_error(409, "VOLUME_NAME_EXISTS", "A Docker volume with this name already exists")
    return _enqueue("volume_create", {"definition": payload.model_dump(mode="json")}, user)


@router.get("/volumes/{target}")
def volume_detail(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_volumes")
    return _provider(user).volume_details(target)


@router.post("/volumes/{target}/actions")
def volume_action(target: str, payload: VolumeActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_volumes")
    if payload.action == "clone" and payload.target_name and _provider(user).named_resource_exists("volume", payload.target_name):
        api_error(409, "VOLUME_NAME_EXISTS", "A Docker volume with this name already exists")
    if payload.action in {"remove", "prune", "restore"}:
        expected = "volumes" if payload.action == "prune" else target
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=expected, permission="docker.prune" if payload.action == "prune" else "docker.restore_backup" if payload.action == "restore" else "docker.high_risk")
    data = payload.model_dump(mode="json", exclude={"action", "pam_password", "confirmation"})
    return _enqueue(f"volume_{payload.action}", {"target": target, **data}, user)


@router.get("/networks")
def networks(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), search: str = "", user: SessionUser = Depends(current_user)):
    _allow_any(user, "docker.manage_networks", "docker.create_container")
    return _provider(user).networks(page=page, page_size=page_size, search=search[:200])


@router.get("/networks/default-bridge")
def default_bridge_network(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_networks")
    return _provider(user).default_bridge_config()


@router.put("/networks/default-bridge")
def save_default_bridge_network(payload: DefaultBridgeConfigRequest, user: SessionUser = Depends(mutating_user)):
    _assert_mutation_allowed()
    _critical(
        user,
        password=payload.pam_password,
        confirmation=payload.confirmation,
        expected="bridge",
        permission="docker.update_engine",
    )
    provider = _provider(user)
    config = provider.merge_default_bridge_config(
        payload.model_dump(mode="json", exclude={"confirmation", "pam_password"})
    )
    validation = provider.validate_config(config)
    if not validation.ok:
        api_error(422, "CONFIG_VALIDATION_FAILED", "Docker default bridge configuration is invalid", errors=validation.errors)
    module = get_module("docker")
    plan = PackagePlan(
        module_id="docker",
        action=PackageAction.apply,
        distribution=module["distribution"],
        compatible=bool(module["compatible"]),
        blocked_by_proxmox=bool(module["blocked_by_proxmox"]),
        services=["docker"],
        config_paths=["/etc/docker/daemon.json"],
        steps=["Validate default bridge settings", "Create backup", "Write daemon.json atomically", "Restart Docker", "Verify or roll back"],
        warnings=["Changing the default bridge configuration restarts Docker and can interrupt containers"],
        payload={"config": config},
        create_backup=True,
    )
    return {"job": manager(repository()).enqueue(plan, user.username), "validation": validation}


@router.post("/networks")
def create_network(payload: NetworkCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_networks")
    if _provider(user).named_resource_exists("network", payload.name):
        api_error(409, "NETWORK_NAME_EXISTS", "A Docker network with this name already exists")
    return _enqueue("network_create", {"definition": payload.model_dump(mode="json")}, user)


@router.get("/networks/{target}")
def network_detail(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_networks")
    return _provider(user).network_details(target)


@router.get("/networks/{target}/containers")
def network_containers(target: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_networks")
    return _provider(user).network_container_candidates(target)


@router.post("/networks/{target}/actions")
def network_action(target: str, payload: NetworkActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_networks")
    if payload.action in {"remove", "prune"}:
        expected = "networks" if payload.action == "prune" else target
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=expected, permission="docker.prune" if payload.action == "prune" else "docker.high_risk")
    data = payload.model_dump(mode="json", exclude={"action", "pam_password", "confirmation"})
    return _enqueue(f"network_{payload.action}", {"target": target, **data}, user)


@router.get("/compose")
def compose_projects(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_compose")
    return _provider(user).list_resources("compose", limit=1000)


@router.get("/compose/{project}")
def compose_project(project: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_compose")
    project = _project(project)
    provider = _provider(user)
    return {**provider.get_compose(project), "plan": provider.compose_plan(project), "history": provider.compose_history(project)}


@router.put("/compose/{project}")
def save_compose(project: str, payload: ComposeSaveRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_compose")
    _assert_mutation_allowed()
    project = _project(project)
    provider = _provider(user)
    private = payload.secret_environment if payload.secret_environment is not None else provider.compose_secret_environment(project)
    validation = provider.validate_compose_runtime(payload.content, environment=payload.environment, secret_environment=private)
    if not validation["valid"]:
        api_error(422, "COMPOSE_VALIDATION_FAILED", "docker compose config rejected the project", errors=validation["errors"])
    result = provider.save_compose(project, payload.content, environment=payload.environment, secret_environment=payload.secret_environment, actor=user.username, description=payload.description)
    record_activity(ActivityCategory.module, "compose_save", user.username, target="docker", details={"project": project, "revision": result["revision"]}, source="containers-manager")
    return result


@router.post("/compose/{project}/validate")
def validate_compose(project: str, payload: ComposeSaveRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_compose")
    project = _project(project)
    provider = _provider(user)
    private = payload.secret_environment if payload.secret_environment is not None else provider.compose_secret_environment(project)
    return provider.validate_compose_runtime(payload.content, environment=payload.environment, secret_environment=private)


@router.post("/compose/{project}/actions")
def compose_action(project: str, payload: ComposeActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_compose")
    project = _project(project)
    if payload.action == "validate":
        return _provider(user).compose_plan(project)
    plan = _provider(user).compose_plan(project)
    if not plan["valid"]:
        api_error(422, "COMPOSE_VALIDATION_FAILED", "docker compose config rejected the project", errors=plan["errors"])
    if payload.action == "delete" or payload.remove_volumes:
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=project)
    data = payload.model_dump(mode="json", exclude={"action", "pam_password", "confirmation"})
    return _enqueue(f"compose_{payload.action}", {"project": project, **data}, user)


@router.get("/compose/{project}/status")
def compose_status(project: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_compose")
    return _provider(user).compose_status(_project(project))


@router.get("/compose/{project}/logs")
def compose_logs(project: str, service: str = "", tail: int = Query(500, ge=1, le=5000), since: str = "", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_compose")
    return _provider(user).compose_logs(_project(project), service=service, tail=tail, since=since[:40])


@router.get("/compose/{project}/history")
def compose_history(project: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.manage_compose")
    return {"items": _provider(user).compose_history(_project(project))}


@router.post("/compose/{project}/history/{revision}/rollback")
def compose_rollback(project: str, revision: str, confirmation: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.manage_compose")
    _assert_mutation_allowed()
    project = _project(project)
    if not REVISION_RE.fullmatch(revision):
        api_error(400, "INVALID_COMPOSE_REVISION", "Invalid Compose revision")
    if confirmation != project:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the project name to roll back", expected=project)
    result = _provider(user).rollback_compose(project, revision, user.username)
    record_activity(ActivityCategory.module, "compose_rollback", user.username, target="docker", details={"project": project, "from_revision": revision, "revision": result["revision"]}, source="containers-manager")
    return result


@router.get("/apps")
def apps(search: str = "", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view_containers")
    return _provider(user).list_resources("apps", limit=100, search=search[:200])


@router.post("/apps/{app_id}/install")
def install_app(app_id: str, payload: AppInstallRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.create_container")
    if payload.confirmation != app_id:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the application identifier to install it", expected=app_id)
    input_ref = store().stage_input({"environment": payload.secret_environment}) if payload.secret_environment else ""
    try:
        settings = payload.model_dump(mode="json", exclude={"secret_environment", "confirmation"})
        return _enqueue("app_install", {"app_id": app_id, "input_ref": input_ref, **settings}, user)
    except Exception:
        store().discard_input(input_ref)
        raise


@router.post("/apps/{app_id}/{action}")
def app_action(app_id: str, action: Literal["start", "stop", "restart", "update", "remove"], payload: AppActionRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, "docker.remove_container" if action == "remove" else "docker.pull_image" if action == "update" else "docker.restart_container")
    if action == "remove":
        _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=app_id)
    elif action == "update" and payload.confirmation != app_id:
        api_error(400, "EXACT_CONFIRMATION_REQUIRED", "Enter the application identifier to confirm", expected=app_id)
    return _enqueue(f"app_{action}", {"app_id": app_id}, user)


@router.get("/events")
def events(since_seconds: int = Query(3600, ge=1, le=86400), limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(current_user)):
    _allow(user, "docker.view")
    return _provider(user).events(since_seconds=since_seconds, limit=limit)


@router.get("/prune/plan")
def prune_plan(resources: str = "containers,images,networks,volumes,build_cache", user: SessionUser = Depends(current_user)):
    _allow(user, "docker.prune")
    selected = [item for item in resources.split(",") if item]
    return _provider(user).prune_plan(selected)


@router.post("/prune")
def prune(payload: PrunePlanRequest, user: SessionUser = Depends(mutating_user)):
    _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected="PRUNE", permission="docker.prune")
    return _enqueue("system_prune", {"resources": payload.resources}, user, warning="Unused Docker resources will be permanently removed")


@router.get("/backups")
def backups(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.export_backup")
    return {"configuration": _provider(user).list_backups(), "artifacts": store().list_artifacts()}


@router.post("/backups/{backup_id}/restore")
def restore_container_backup(backup_id: str, payload: ContainerRestoreRequest, user: SessionUser = Depends(mutating_user)):
    _critical(user, password=payload.pam_password, confirmation=payload.confirmation, expected=payload.new_name, permission="docker.restore_backup")
    input_ref = store().stage_input({"environment": payload.secret_environment}) if payload.secret_environment else ""
    try:
        return _enqueue("container_restore", {"backup_id": backup_id, "new_name": payload.new_name, "input_ref": input_ref}, user, warning="Secret values are accepted only through a one-time private input and are never read from the backup")
    except Exception:
        store().discard_input(input_ref)
        raise


@router.get("/artifacts/{artifact_id}")
def download_artifact(artifact_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, "docker.export_backup")
    path, metadata = store().artifact(artifact_id)
    return FileResponse(path, filename=metadata["display_name"], media_type="application/octet-stream", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(current_user)):
    _allow(user, "docker.diagnostics")
    provider = _provider(user)
    return {"generated_at": time.time(), "status": provider.get_status(), "checks": [item.model_dump(mode="json") for item in provider.run_diagnostics()], "config": provider.get_config(), "prune": provider.prune_plan(["containers", "images", "networks", "volumes", "build_cache"])}
