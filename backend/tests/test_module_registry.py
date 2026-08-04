from pathlib import Path

import pytest

from app.bootstrap import BUILTIN_MODULES, build_module_registry, create_app
from app.core.modules import ModuleManifest, ModuleRegistry, ModuleState


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
    assert any(getattr(route, "path", None) == "/api/v1/modules" for route in first.routes)
