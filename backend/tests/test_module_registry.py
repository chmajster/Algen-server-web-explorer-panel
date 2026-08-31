import asyncio
from pathlib import Path

import pytest

from app.bootstrap import BUILTIN_MODULES, build_module_registry, create_app
from app.core.modules import ModuleHealthState, ModuleManifest, ModuleRegistry, ModuleState


def manifest(module_id: str, dependencies: list[str] | None = None) -> ModuleManifest:
    return ModuleManifest(id=module_id, name=module_id, category="test", icon="box", dependencies=dependencies or [])


def test_builtin_manifests_are_valid_unique_and_dependency_sorted():
    registry = build_module_registry()
    ids = [item.id for item in registry.manifests]

    assert len(ids) == len(set(ids))
    assert {"files", "settings", "identity", "package-center", "containers", "hosts-manager"} <= set(ids)
    assert ids.index("package-center") < ids.index("containers")
    assert all(item.state is ModuleState.active for item in registry.diagnostics())


def test_registry_rejects_duplicate_ids_and_dependency_cycles():
    registry = ModuleRegistry()
    registry.register(manifest("first"))
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(manifest("first"))

    cyclic = ModuleRegistry()
    cyclic.register(manifest("first", ["second"]))
    cyclic.register(manifest("second", ["first"]))
    with pytest.raises(ValueError, match="Cyclic"):
        cyclic.initialization_order()


def test_unavailable_state_propagates_through_dependencies():
    registry = ModuleRegistry()
    registry.register(ModuleManifest(id="base", name="base", category="test", icon="box", enabled=False))
    registry.register(manifest("consumer", ["base"]))

    registry.validate_dependencies()

    diagnostics = {item.module_id: item for item in registry.diagnostics()}
    assert diagnostics["base"].state is ModuleState.disabled
    assert diagnostics["consumer"].state is ModuleState.unavailable


def test_discovery_reports_a_broken_manifest_without_executing_it(tmp_path: Path):
    directory = tmp_path / "unsafe"
    directory.mkdir()
    (directory / "manifest.yaml").write_text("id: INVALID\nname: bad\ncategory: test\nicon: box\n", encoding="utf-8")
    registry = ModuleRegistry()

    registry.discover(tmp_path)

    assert registry.diagnostics()[0].state is ModuleState.broken
    assert not registry.manifests


def test_application_factory_builds_independent_apps_from_registry():
    first = create_app(registry=build_module_registry(BUILTIN_MODULES), mount_frontend=False)
    second = create_app(registry=build_module_registry(BUILTIN_MODULES), mount_frontend=False)

    assert first is not second
    assert first.state.modules is not second.state.modules
    assert first.state.background_tasks is not second.state.background_tasks
    assert "/api/v1/modules" in first.openapi()["paths"]


def test_registry_runs_lifecycle_and_health_callbacks(monkeypatch):
    events: list[str] = []
    registry = ModuleRegistry()
    registry.register(ModuleManifest(
        id="lifecycle", name="Lifecycle", category="test", icon="box",
        startup="app.lifecycle:start", shutdown="app.lifecycle:stop", health_check="app.lifecycle:health",
    ))
    callbacks = {
        "app.lifecycle:start": lambda: events.append("start"),
        "app.lifecycle:stop": lambda: events.append("stop"),
        "app.lifecycle:health": lambda: "healthy",
    }
    monkeypatch.setattr(registry, "_load", lambda reference: callbacks[reference])

    asyncio.run(registry.startup())
    asyncio.run(registry.startup())
    health = asyncio.run(registry.health())
    asyncio.run(registry.shutdown())
    asyncio.run(registry.shutdown())

    assert events == ["start", "stop"]
    assert health == [{
        "module_id": "lifecycle",
        "state": ModuleState.active,
        "health_state": ModuleHealthState.healthy,
        "message": "healthy",
    }]


def test_health_failure_recovers_without_poisoning_lifecycle(monkeypatch):
    registry = ModuleRegistry()
    registry.register(ModuleManifest(
        id="recoverable", name="Recoverable", category="test", icon="box",
        health_check="app.recoverable:health",
    ))
    attempts = iter([RuntimeError("temporary outage"), "healthy"])

    def health():
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(registry, "_load", lambda _reference: health)

    failed = asyncio.run(registry.health())[0]
    recovered = asyncio.run(registry.health())[0]

    assert failed["state"] is ModuleState.active
    assert failed["health_state"] is ModuleHealthState.unhealthy
    assert recovered["state"] is ModuleState.active
    assert recovered["health_state"] is ModuleHealthState.healthy


def test_optional_startup_failure_is_isolated_and_dependency_is_unavailable(monkeypatch):
    events: list[str] = []
    registry = ModuleRegistry()
    registry.register(ModuleManifest(
        id="broken", name="Broken", category="test", icon="box", startup="app.broken:start",
    ))
    registry.register(ModuleManifest(
        id="dependent", name="Dependent", category="test", icon="box", dependencies=["broken"], startup="app.dependent:start",
    ))
    registry.register(ModuleManifest(
        id="independent", name="Independent", category="test", icon="box", startup="app.independent:start",
    ))

    def load(reference: str):
        if reference == "app.broken:start":
            def fail() -> None:
                raise RuntimeError("boom")
            return fail
        return lambda: events.append(reference)

    monkeypatch.setattr(registry, "_load", load)
    asyncio.run(registry.startup())

    diagnostics = {item.module_id: item for item in registry.diagnostics()}
    assert diagnostics["broken"].state is ModuleState.broken
    assert diagnostics["dependent"].state is ModuleState.unavailable
    assert diagnostics["independent"].state is ModuleState.active
    assert events == ["app.independent:start"]


def test_critical_startup_failure_still_fails_closed(monkeypatch):
    registry = ModuleRegistry()
    registry.register(ModuleManifest(
        id="critical", name="Critical", category="test", icon="box", critical=True, startup="app.critical:start",
    ))

    def fail() -> None:
        raise RuntimeError("critical failure")

    monkeypatch.setattr(registry, "_load", lambda _reference: fail)

    with pytest.raises(RuntimeError, match="critical module"):
        asyncio.run(registry.startup())
