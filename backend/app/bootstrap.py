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
from starlette.middleware.gzip import GZipMiddleware

from . import __version__
from . import settings as settings_api
from .alerts.collectors import collector_loop as alert_collector_loop
from .alerts.router import router as alerts_router
from .alerts.scheduler import start_scheduler as start_alert_scheduler
from .appliance_backup import router as appliance_backup_router
from .audit import configure_logging
from .config import AppConfig, get_config
from .core.cache import SLOW_CACHE_TTL_SECONDS, TTLCache
from .core.errors import DomainError, domain_error_handler, success_payload, unhandled_error_handler
from .core.modules import ModuleRegistry
from .jobs.models import JobStatus
from .jobs.service import service as job_service
from .ldap_authentication import repository as ldap_auth_repository
from .local_auth import initialize_active_auth_mode
from .modules.ansible_controller.scheduler import start_scheduler as start_ansible_scheduler
from .modules.os_repositories.scheduler import start_scheduler as start_os_repositories_scheduler
from .modules.proxmox_manager.scheduler import start_scheduler as start_proxmox_scheduler
from .network_mounts import active_mount_jobs
from .package_center.jobs import manager as package_job_manager
from .package_center.service import repository as package_repository
from .performance import performance_timing
from .platform_api import frontend_cache_policy
from .power_control import router as power_control_router
from .resource_sampler import resource_sampler, resource_sampler_loop
from .runtime_events import router as runtime_events_router
from .runtime_events import watch_update_progress
from .security import SessionUser, get_session_user
from .startup_bootstrap import router as startup_bootstrap_router
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
    settings_api.start_auto_update_scheduler()
    start_alert_scheduler()
    start_ansible_scheduler()
    start_os_repositories_scheduler()
    start_proxmox_scheduler()


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    module_registry: ModuleRegistry = app.state.modules
    app.state.ready = False
    initialize_active_auth_mode()
    ldap_auth_repository().settings()
    global_jobs = job_service()
    await module_registry.startup()
    repository = package_repository()
    manager = package_job_manager(repository)
    register_operation_provider(
        "file",
        lambda: [task.to_dict() for task in task_store.list_all() if task.status.value in {"queued", "running"}],
        task_store.schedule_pending,
    )
    register_operation_provider("package", repository.active_jobs, manager.schedule_pending)
    register_operation_provider(
        "job",
        lambda: [
            item.model_dump(mode="json")
            for status in (JobStatus.queued, JobStatus.running, JobStatus.cancel_requested)
            for item in global_jobs.list(status=status, limit=500).items
        ],
    )
    register_operation_provider("mount", active_mount_jobs)
    register_operation_provider("upload", active_uploads)
    register_operation_provider("direct", active_transient_operations)

    promotion_task: asyncio.Task[None] | None = None
    collector_task: asyncio.Task[None] | None = None
    runtime_event_task: asyncio.Task[None] | None = None
    resource_sampler_task: asyncio.Task[None] | None = None

    def start_runtime_side_effects() -> None:
        nonlocal collector_task, runtime_event_task, resource_sampler_task
        _start_schedulers()
        if collector_task is None or collector_task.done():
            collector_task = asyncio.create_task(alert_collector_loop(module_registry))
        if runtime_event_task is None or runtime_event_task.done():
            runtime_event_task = asyncio.create_task(watch_update_progress())
        if resource_sampler_task is None or resource_sampler_task.done():
            resource_sampler_task = asyncio.create_task(resource_sampler_loop())

    if os.environ.get("WEBNAS_CANDIDATE") != "1":
        start_runtime_side_effects()
    else:
        slot = os.environ.get("WEBNAS_SLOT", "")

        async def promote_candidate() -> None:
            active_slot_file = Path(os.environ.get("WEBNAS_ACTIVE_SLOT_FILE", "/run/webnas/active-slot"))
            while True:
                try:
                    if active_slot_file.read_text(encoding="utf-8").strip() == slot:
                        start_runtime_side_effects()
                        return
                except OSError:
                    pass
                await asyncio.sleep(0.25)

        promotion_task = asyncio.create_task(promote_candidate())
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False
        if promotion_task and not promotion_task.done():
            promotion_task.cancel()
        if collector_task and not collector_task.done():
            collector_task.cancel()
        if runtime_event_task and not runtime_event_task.done():
            runtime_event_task.cancel()
        if resource_sampler_task and not resource_sampler_task.done():
            resource_sampler_task.cancel()
        await module_registry.shutdown()


def _registry_router(registry: ModuleRegistry) -> APIRouter:
    router = APIRouter(prefix="/api/v1/modules", tags=["module-registry"])
    catalog_cache: TTLCache[list[dict]] = TTLCache(SLOW_CACHE_TTL_SECONDS)

    @router.get("")
    def module_catalog(_user: SessionUser = Depends(get_session_user)):
        catalog = catalog_cache.get_or_load(registry.public_catalog)
        return success_payload(catalog, total=len(registry.manifests))

    @router.get("/health")
    async def module_health(_user: SessionUser = Depends(get_session_user)):
        diagnostics = await registry.health()
        catalog_cache.invalidate()
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
    # settings.system_resources resolves this module global at request time.
    # Inject the shared sampler at the composition root without changing the
    # public API or the settings router's authorization dependency.
    settings_api.collect_dashboard = resource_sampler.dashboard
    app = FastAPI(title="WebNAS", version=__version__, lifespan=application_lifespan)
    app.state.ready = False
    app.state.settings = application_settings
    app.state.modules = module_registry
    app.state.container = container
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    app.middleware("http")(frontend_cache_policy)
    app.middleware("http")(performance_timing)
    module_registry.install_routers(app)
    app.include_router(_registry_router(module_registry))
    app.include_router(startup_bootstrap_router)
    app.include_router(runtime_events_router)
    app.include_router(update_detail_policy_router)
    app.include_router(power_control_router)
    app.include_router(appliance_backup_router, include_in_schema=False)
    app.include_router(alerts_router)
    if mount_frontend and FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
