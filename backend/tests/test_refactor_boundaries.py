from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"


def test_apps_is_only_a_compatibility_facade():
    source = (BACKEND / "apps.py").read_text(encoding="utf-8")
    assert "jobs: dict" not in source
    assert "threading.Thread" not in source
    assert "class AppJob" not in source
    assert source.count("\n") < 320


def test_jobs_own_persistence_and_controlled_runner():
    repository = (BACKEND / "jobs" / "repository.py").read_text(encoding="utf-8")
    runner = (BACKEND / "jobs" / "runner.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS jobs" in repository
    assert "ThreadPoolExecutor" in runner
    assert "threading.Thread" not in runner


def test_plugin_subsystem_does_not_depend_on_apps_internals():
    for path in (BACKEND / "plugins").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from ..apps" not in source
        assert "from app.apps" not in source


def test_plugin_models_do_not_persist_secret_payload_fields():
    source = (BACKEND / "plugins" / "models.py").read_text(encoding="utf-8")
    for forbidden in ("password:", "token:", "private_key:", "secret:"):
        assert forbidden not in source
    assert "credential_id" in source


def test_generated_types_live_only_in_generated_directory():
    generated = ROOT / "frontend" / "src" / "core" / "api" / "generated" / "api-types.ts"
    assert generated.parent.name == "generated"
    for path in (ROOT / "frontend" / "src").rglob("api-types.ts"):
        assert path == generated
