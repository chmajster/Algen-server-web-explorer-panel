import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1] / "app"


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


def test_core_does_not_import_business_modules():
    violations: list[str] = []
    for path in (BACKEND / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (node.module.startswith("app.modules") or "package_center" in node.module):
                violations.append(f"{path.name}:{node.lineno}:{node.module}")
    assert violations == []
