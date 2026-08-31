import ast
from collections import Counter
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1] / "app"
REPOSITORY = BACKEND.parents[1]

# Temporary migration ledger for command execution that predates CommandRunner.
# The test below is a ratchet: new router subprocess calls fail immediately and
# these exact budgets must be reduced as legacy call-sites move into adapters.
LEGACY_ROUTER_COMMAND_BUDGET = {
    ("modules/router.py", "subprocess.run"): 1,
    ("modules/ansible_controller/router.py", "subprocess.run"): 1,
    ("modules/hosts_manager/router.py", "subprocess.run"): 7,
    ("modules/docker_manager/router.py", "subprocess.Popen"): 1,
}


def test_composition_root_contains_no_business_routes_or_router_imports():
    source = (BACKEND / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in tree.body)
    assert "include_router" not in source
    assert "@app." not in source


def test_bootstrap_does_not_import_specific_business_modules():
    source = (BACKEND / "bootstrap.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("modules."):
            violations.append(f"bootstrap.py:{node.lineno}:{node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app.modules."):
                    violations.append(f"bootstrap.py:{node.lineno}:{alias.name}")
    assert violations == []


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


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return f"{node.func.value.id}.{node.func.attr}"
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def test_http_routers_do_not_add_direct_system_command_execution():
    forbidden = {"subprocess.run", "subprocess.Popen", "subprocess.call", "os.system", "os.popen"}
    observed: Counter[tuple[str, str]] = Counter()
    violations: list[str] = []
    for path in BACKEND.rglob("router.py"):
        relative = str(path.relative_to(BACKEND))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = _call_name(node)
            if call not in forbidden:
                continue
            key = (relative, call)
            observed[key] += 1
            if observed[key] > LEGACY_ROUTER_COMMAND_BUDGET.get(key, 0):
                violations.append(f"{relative}:{node.lineno}:{call}")
    assert violations == []
    assert all(observed[key] <= budget for key, budget in LEGACY_ROUTER_COMMAND_BUDGET.items())


def test_shell_true_is_forbidden_outside_explicit_command_boundary():
    violations: list[str] = []
    for path in BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    violations.append(f"{path.relative_to(BACKEND)}:{node.lineno}:shell=True")
    assert violations == []


def test_command_runner_is_the_documented_new_execution_boundary():
    source = (BACKEND / "command_runner.py").read_text(encoding="utf-8")
    assert "class ReadOnlyCommandRunner" in source
    assert "class PrivilegedCommandRunner" in source
    assert "shell=False" in source
    assert "privileged_broker.runtime" in source


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
