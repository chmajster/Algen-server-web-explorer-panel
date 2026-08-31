from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from .manifest import ModuleHealthState, ModuleManifest, ModuleState


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModuleDiagnostic:
    module_id: str
    state: ModuleState
    message: str = ""
    health_state: ModuleHealthState = ModuleHealthState.unknown


class ModuleRegistry:
    """Canonical catalog and composition mechanism for WebNAS modules."""

    def __init__(self) -> None:
        self._manifests: dict[str, ModuleManifest] = {}
        self._diagnostics: dict[str, ModuleDiagnostic] = {}
        self._started: set[str] = set()
        self._initialization_order_cache: tuple[str, ...] | None = None

    @property
    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._manifests[module_id] for module_id in self.initialization_order())

    def register(self, manifest: ModuleManifest) -> None:
        if manifest.id in self._manifests:
            raise ValueError(f"Duplicate module id: {manifest.id}")
        if manifest.id in manifest.dependencies:
            raise ValueError(f"Module {manifest.id} cannot depend on itself")
        self._manifests[manifest.id] = manifest
        self._initialization_order_cache = None
        state = ModuleState.active if manifest.enabled else ModuleState.disabled
        self._diagnostics[manifest.id] = ModuleDiagnostic(manifest.id, state)

    def discover(self, root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.glob("*/manifest.yaml")):
            try:
                self.register(ModuleManifest.from_yaml(path))
            except Exception as error:  # noqa: BLE001 - one broken manifest must not hide diagnostics for the rest.
                module_id = path.parent.name
                self._diagnostics[module_id] = ModuleDiagnostic(module_id, ModuleState.broken, str(error))
                logger.exception("module_manifest_invalid module=%s path=%s", module_id, path)
        self.validate_dependencies()

    def validate_dependencies(self) -> None:
        for manifest in self._manifests.values():
            missing = [dependency for dependency in manifest.dependencies if dependency not in self._manifests]
            if missing:
                self._diagnostics[manifest.id] = ModuleDiagnostic(
                    manifest.id,
                    ModuleState.unavailable,
                    f"Missing dependencies: {', '.join(missing)}",
                )
        for module_id in self.initialization_order():
            manifest = self._manifests[module_id]
            unavailable = [
                dependency
                for dependency in manifest.dependencies
                if self._diagnostics[dependency].state is not ModuleState.active
            ]
            if unavailable and self._diagnostics[module_id].state is ModuleState.active:
                self._diagnostics[module_id] = ModuleDiagnostic(
                    module_id,
                    ModuleState.unavailable,
                    f"Unavailable dependencies: {', '.join(unavailable)}",
                )

    def initialization_order(self) -> tuple[str, ...]:
        if self._initialization_order_cache is not None:
            return self._initialization_order_cache

        result: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(module_id: str) -> None:
            if module_id in visited:
                return
            if module_id in visiting:
                raise ValueError(f"Cyclic module dependency involving {module_id}")
            visiting.add(module_id)
            manifest = self._manifests[module_id]
            for dependency in manifest.dependencies:
                if dependency in self._manifests:
                    visit(dependency)
            visiting.remove(module_id)
            visited.add(module_id)
            result.append(module_id)

        for module_id in sorted(self._manifests):
            visit(module_id)
        self._initialization_order_cache = tuple(result)
        return self._initialization_order_cache

    @staticmethod
    def _load(reference: str) -> Any:
        module_name, attribute = reference.split(":", 1)
        return getattr(importlib.import_module(module_name), attribute)

    def _mark_broken(self, manifest: ModuleManifest, message: str) -> None:
        self._diagnostics[manifest.id] = ModuleDiagnostic(
            manifest.id,
            ModuleState.broken,
            message,
            ModuleHealthState.unknown,
        )

    def _dependency_failures(self, manifest: ModuleManifest) -> list[str]:
        return [
            dependency
            for dependency in manifest.dependencies
            if self._diagnostics[dependency].state is not ModuleState.active
        ]

    def install_routers(self, app: FastAPI) -> None:
        for manifest in self.manifests:
            if self._diagnostics[manifest.id].state is not ModuleState.active:
                continue
            unavailable = self._dependency_failures(manifest)
            if unavailable:
                self._diagnostics[manifest.id] = ModuleDiagnostic(
                    manifest.id,
                    ModuleState.unavailable,
                    f"Unavailable dependencies during router initialization: {', '.join(unavailable)}",
                )
                continue
            try:
                routers: list[APIRouter] = []
                for reference in manifest.routers:
                    router = self._load(reference)
                    if not isinstance(router, APIRouter):
                        raise TypeError(f"{reference} is not an APIRouter")
                    routers.append(router)
                for router in routers:
                    app.include_router(router)
            except Exception as error:  # noqa: BLE001 - optional modules are isolated; critical modules fail closed.
                self._mark_broken(manifest, f"Router initialization failed: {error}")
                logger.exception("module_router_initialization_failed module=%s", manifest.id)
                if manifest.critical:
                    raise RuntimeError(f"Could not initialize critical module {manifest.id}") from error

    def public_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                **manifest.model_dump(exclude={"routers", "startup", "shutdown", "health_check"}),
                "state": self._diagnostics[manifest.id].state,
                "health_state": self._diagnostics[manifest.id].health_state,
                "diagnostic": self._diagnostics[manifest.id].message,
            }
            for manifest in self.manifests
        ]

    async def startup(self) -> None:
        """Start module-owned runtime services in dependency order.

        Startup is idempotent. Failure of an optional module is isolated and recorded;
        a manifest marked ``critical`` still prevents application startup.
        """
        for manifest in self.manifests:
            if manifest.id in self._started or self._diagnostics[manifest.id].state is not ModuleState.active:
                continue
            unavailable = self._dependency_failures(manifest)
            if unavailable:
                self._diagnostics[manifest.id] = ModuleDiagnostic(
                    manifest.id,
                    ModuleState.unavailable,
                    f"Unavailable dependencies during startup: {', '.join(unavailable)}",
                )
                continue
            if not manifest.startup:
                continue
            try:
                result = self._load(manifest.startup)()
                if inspect.isawaitable(result):
                    await result
                self._started.add(manifest.id)
                logger.info("module_started module=%s", manifest.id)
            except Exception as error:  # noqa: BLE001 - isolate optional modules while preserving diagnostics.
                self._mark_broken(manifest, f"Startup failed: {error}")
                logger.exception("module_startup_failed module=%s", manifest.id)
                if manifest.shutdown:
                    try:
                        rollback = self._load(manifest.shutdown)()
                        if inspect.isawaitable(rollback):
                            await rollback
                        logger.info("module_startup_rolled_back module=%s", manifest.id)
                    except Exception:  # noqa: BLE001 - best-effort cleanup must not hide the startup failure.
                        logger.exception("module_startup_rollback_failed module=%s", manifest.id)
                if manifest.critical:
                    await self.shutdown()
                    raise RuntimeError(f"Could not start critical module {manifest.id}") from error

    async def shutdown(self) -> None:
        """Stop successfully started module services in reverse dependency order."""
        for manifest in reversed(self.manifests):
            if manifest.id not in self._started:
                continue
            try:
                if manifest.shutdown:
                    result = self._load(manifest.shutdown)()
                    if inspect.isawaitable(result):
                        await result
                logger.info("module_stopped module=%s", manifest.id)
            except Exception as error:  # noqa: BLE001 - shutdown continues for remaining modules.
                self._mark_broken(manifest, f"Shutdown failed: {error}")
                logger.exception("module_shutdown_failed module=%s", manifest.id)
            finally:
                self._started.discard(manifest.id)

    @staticmethod
    def _parse_health_state(value: Any) -> ModuleHealthState:
        raw = str(value or "").strip().lower()
        try:
            return ModuleHealthState(raw)
        except ValueError:
            prefix = raw.split(":", 1)[0].strip()
            if prefix in {"critical", "failed", "failure", "error", "unhealthy"}:
                return ModuleHealthState.unhealthy
            if prefix in {"degraded", "warning", "warn"}:
                return ModuleHealthState.degraded
            if prefix in {"healthy", "ok", "ready"}:
                return ModuleHealthState.healthy
            return ModuleHealthState.unknown

    @classmethod
    def _health_result(cls, value: Any) -> tuple[ModuleHealthState, str]:
        if isinstance(value, ModuleHealthState):
            return value, value.value
        if isinstance(value, dict):
            raw_state = value.get("health_state", value.get("status", ModuleHealthState.healthy.value))
            state = cls._parse_health_state(raw_state)
            return state, str(value.get("message") or raw_state or "ok")
        if isinstance(value, str):
            return cls._parse_health_state(value), value or "ok"
        return ModuleHealthState.healthy, str(value or "ok")

    async def health(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for manifest in self.manifests:
            diagnostic = self._diagnostics[manifest.id]
            if manifest.health_check and diagnostic.state is ModuleState.active:
                previous_health = diagnostic.health_state
                try:
                    value = self._load(manifest.health_check)()
                    if inspect.isawaitable(value):
                        value = await value
                    health_state, message = self._health_result(value)
                    diagnostic = ModuleDiagnostic(manifest.id, diagnostic.state, message, health_state)
                    if previous_health in {ModuleHealthState.unhealthy, ModuleHealthState.degraded} and health_state is ModuleHealthState.healthy:
                        logger.info("module_health_recovered module=%s", manifest.id)
                except Exception as error:  # noqa: BLE001 - health failures must not poison lifecycle state.
                    diagnostic = ModuleDiagnostic(
                        manifest.id,
                        diagnostic.state,
                        str(error),
                        ModuleHealthState.unhealthy,
                    )
                    logger.exception("module_health_failed module=%s", manifest.id)
                self._diagnostics[manifest.id] = diagnostic
            result.append(
                {
                    "module_id": manifest.id,
                    "state": diagnostic.state,
                    "health_state": diagnostic.health_state,
                    "message": diagnostic.message,
                }
            )
        return result

    def diagnostics(self) -> tuple[ModuleDiagnostic, ...]:
        return tuple(self._diagnostics[key] for key in sorted(self._diagnostics))
