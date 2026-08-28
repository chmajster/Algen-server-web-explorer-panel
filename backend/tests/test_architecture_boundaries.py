import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1] / "app"
REPOSITORY = BACKEND.parents[1]


def test_composition_root_contains_no_business_routes_or_router_imports():
    source = (BACKEND / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in tree.body)
    assert "include_router" not in source
    assert "@app." not in source


def test_manifest_catalog_contains_data_only_and_no_executable_manifests():
    root = BACKEND / "modules" / "builtin"
    assert list(root.glob("*/manifest.yaml"))
    assert not list(root.glob("*/manifest.py"))
    assert not list(root.glob("*/*.sh"))


def test_legacy_mixed_http_router_is_removed():
    assert not (BACKEND / "http_api.py").exists()
    file_router = (BACKEND / "modules" / "files" / "api" / "router.py").read_text(encoding="utf-8")
    assert "/api/auth/" not in file_router
    assert "/api/health" not in file_router


def test_core_does_not_import_business_modules():
    violations: list[str] = []
    for path in (BACKEND / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (node.module.startswith("app.modules") or "package_center" in node.module):
                violations.append(f"{path.name}:{node.lineno}:{node.module}")
    assert violations == []


def _absolute_import(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = ["app", "modules", *path.relative_to(BACKEND / "modules").parent.parts]
    prefix = package[: len(package) - node.level + 1]
    return ".".join([*prefix, *((node.module or "").split("."))]).rstrip(".")


def test_modules_only_use_public_cross_module_contracts():
    modules_root = BACKEND / "modules"
    violations: list[str] = []
    for path in modules_root.rglob("*.py"):
        relative = path.relative_to(modules_root)
        if len(relative.parts) < 2 or not (modules_root / relative.parts[0] / "__init__.py").exists():
            continue
        owner = relative.parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported = _absolute_import(path, node)
            parts = imported.split(".")
            if len(parts) < 3 or parts[:2] != ["app", "modules"] or parts[2] == owner:
                continue
            public_path = len(parts) == 3 or parts[3].startswith("public") or imported == "app.modules.planning"
            if not public_path:
                violations.append(f"{relative}:{node.lineno}:{imported}")
    assert violations == []


def test_frontend_has_discovered_manifests_and_composed_api_clients():
    frontend = REPOSITORY / "frontend" / "src"
    api_source = (frontend / "api.ts").read_text(encoding="utf-8")
    desktop_root_source = (frontend / "app" / "Desktop.tsx").read_text(encoding="utf-8")
    desktop_controller_source = (frontend / "app" / "DesktopController.tsx").read_text(encoding="utf-8")
    manifests = list((frontend / "modules").glob("*/manifest.tsx"))
    clients = list((frontend / "modules").glob("*/api/client.ts"))

    assert len(api_source.splitlines()) < 100
    assert "request<" not in api_source
    assert len(manifests) >= 10
    assert len(clients) >= 10
    assert "switch (item.app)" not in desktop_root_source
    assert "switch (item.app)" not in desktop_controller_source
    assert "moduleRegistry.render" in desktop_controller_source
    assert len(desktop_root_source.splitlines()) < 30
