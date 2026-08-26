from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .audit import configure_logging
from .config import AppConfig, get_config
from .core.modules import ModuleRegistry
from .core.errors import DomainError, domain_error_handler, success_payload
from .platform_api import frontend_cache_policy
from .modules.ansible_controller.scheduler import start_scheduler as start_ansible_scheduler
from .modules.os_repositories.scheduler import start_scheduler as start_os_repositories_scheduler
from .network_mounts import active_mount_jobs
from .package_center.jobs import manager as package_job_manager
from .package_center.service import repository as package_repository
from .power_control import router as power_control_router
from .security import SessionUser, get_session_user
from .settings import start_auto_update_scheduler
from .tasks import task_store
from .update_coordination import active_transient_operations, register_operation_provider
from .update_detail_policy import router as update_detail_policy_router
from .uploads import active_uploads


BUILTIN_MODULES = Path(__file__).resolve().parent / "modules" / "builtin"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    settings: AppConfig
    modules: ModuleRegistry


def build_module_registry(root: Path = BUILTIN_MODULES) -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.discover(root)
    return registry


def _start_schedulers() -> None:
    start_auto_update_scheduler()
    start_ansible_scheduler()
    start_os_repositories_scheduler()


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    module_registry: ModuleRegistry = app.state.modules
    await module_registry.startup()
    repository = package_repository()
    manager = package_job_manager(repository)
    register_operation_provider(
        "file",
        lambda: [task.to_dict() for task in task_store.list_all() if task.status.value in {"queued", "running"}],
        task_store.schedule_pending,
    )
    register_operation_provider("package", repository.active_jobs, manager.schedule_pending)
    register_operation_provider("mount", active_mount_jobs)
    register_operation_provider("upload", active_uploads)
    register_operation_provider("direct", active_transient_operations)
    promotion_task: asyncio.Task[None] | None = None
    if os.environ.get("WEBNAS_CANDIDATE") != "1":
        _start_schedulers()
    else:
        slot = os.environ.get("WEBNAS_SLOT", "")

        async def promote_candidate() -> None:
            active_slot_file = Path(os.environ.get("WEBNAS_ACTIVE_SLOT_FILE", "/run/webnas/active-slot"))
            while True:
                try:
                    if active_slot_file.read_text(encoding="utf-8").strip() == slot:
                        _start_schedulers()
                        return
                except OSError:
                    pass
                await asyncio.sleep(0.25)

        promotion_task = asyncio.create_task(promote_candidate())
    try:
        yield
    finally:
        if promotion_task and not promotion_task.done():
            promotion_task.cancel()
        await module_registry.shutdown()


def _registry_router(registry: ModuleRegistry) -> APIRouter:
    router = APIRouter(prefix="/api/v1/modules", tags=["module-registry"])

    @router.get("")
    def module_catalog(_user: SessionUser = Depends(get_session_user)):
        return success_payload(registry.public_catalog(), total=len(registry.manifests))

    @router.get("/health")
    async def module_health(_user: SessionUser = Depends(get_session_user)):
        diagnostics = await registry.health()
        return success_payload({
            "status": "ok" if all(item["state"] in {"active", "disabled"} for item in diagnostics) else "degraded",
            "modules": diagnostics,
        })

    return router


def create_app(settings: AppConfig | None = None, *, registry: ModuleRegistry | None = None, mount_frontend: bool = True) -> FastAPI:
    """Composition root. Dependencies may be replaced without importing business internals."""
    configure_logging()
    application_settings = settings or get_config()
    module_registry = registry or build_module_registry()
    container = ApplicationContainer(application_settings, module_registry)
    app = FastAPI(title="WebNAS", version="0.1.15", lifespan=application_lifespan)
    app.state.settings = application_settings
    app.state.modules = module_registry
    app.state.container = container
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.middleware("http")(frontend_cache_policy)
    module_registry.install_routers(app)
    app.include_router(_registry_router(module_registry))
    app.include_router(update_detail_policy_router)
    app.include_router(power_control_router)
    if mount_frontend and FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
