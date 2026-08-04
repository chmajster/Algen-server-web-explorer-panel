from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from .manifest import ModuleManifest, ModuleState


@dataclass(frozen=True, slots=True)
class ModuleDiagnostic:
    module_id: str
    state: ModuleState
    message: str = ""


class ModuleRegistry:
    """Canonical catalog and composition mechanism for WebNAS modules."""

    def __init__(self) -> None:
        self._manifests: dict[str, ModuleManifest] = {}
        self._diagnostics: dict[str, ModuleDiagnostic] = {}

    @property
    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._manifests[module_id] for module_id in self.initialization_order())

    def register(self, manifest: ModuleManifest) -> None:
        if manifest.id in self._manifests:
            raise ValueError(f"Duplicate module id: {manifest.id}")
        if manifest.id in manifest.dependencies:
            raise ValueError(f"Module {manifest.id} cannot depend on itself")
        self._manifests[manifest.id] = manifest
        state = ModuleState.active if manifest.enabled else ModuleState.disabled
        self._diagnostics[manifest.id] = ModuleDiagnostic(manifest.id, state)

    def discover(self, root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.glob("*/manifest.yaml")):
            try:
                self.register(ModuleManifest.from_yaml(path))
            except Exception as error:  # noqa: BLE001 - one broken module must not hide diagnostics for the rest.
                module_id = path.parent.name
                self._diagnostics[module_id] = ModuleDiagnostic(module_id, ModuleState.broken, str(error))
        self.validate_dependencies()

    def validate_dependencies(self) -> None:
        for manifest in self._manifests.values():
            missing = [dependency for dependency in manifest.dependencies if dependency not in self._manifests]
            if missing:
                self._diagnostics[manifest.id] = ModuleDiagnostic(
                    manifest.id, ModuleState.unavailable, f"Missing dependencies: {', '.join(missing)}"
                )
        self.initialization_order()

    def initialization_order(self) -> tuple[str, ...]:
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
        return tuple(result)

    @staticmethod
    def _load(reference: str) -> Any:
        module_name, attribute = reference.split(":", 1)
        return getattr(importlib.import_module(module_name), attribute)

    def install_routers(self, app: FastAPI) -> None:
        for manifest in self.manifests:
            if self._diagnostics[manifest.id].state is not ModuleState.active:
                continue
            try:
                for reference in manifest.routers:
                    router = self._load(reference)
                    if not isinstance(router, APIRouter):
                        raise TypeError(f"{reference} is not an APIRouter")
                    app.include_router(router)
            except Exception as error:  # noqa: BLE001 - preserve startup and expose the broken module.
                self._diagnostics[manifest.id] = ModuleDiagnostic(manifest.id, ModuleState.broken, str(error))
                raise RuntimeError(f"Could not initialize module {manifest.id}: {error}") from error

    def public_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                **manifest.model_dump(exclude={"routers"}),
                "state": self._diagnostics[manifest.id].state,
                "diagnostic": self._diagnostics[manifest.id].message,
            }
            for manifest in self.manifests
        ]

    def diagnostics(self) -> tuple[ModuleDiagnostic, ...]:
        return tuple(self._diagnostics[key] for key in sorted(self._diagnostics))
