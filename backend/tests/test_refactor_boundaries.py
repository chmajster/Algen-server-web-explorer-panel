from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"


def test_apps_is_only_a_compatibility_facade():
    source = (BACKEND / "apps.py").read_text(encoding="utf-8")
    assert "jobs: dict" not in source
    assert "threading.Thread" not in source
    assert "class AppJob" not in source
    assert source.count("\n") < 320


def test_logs_is_only_a_compatibility_facade():
    source = (BACKEND / "logs.py").read_text(encoding="utf-8")
    assert source.count("\n") < 140
    assert "subprocess.Popen(" not in source
    assert "@router.get" not in source
    assert "log_system" in source


def test_log_sources_use_explicit_protocol_adapters():
    source = (BACKEND / "log_system" / "adapters.py").read_text(encoding="utf-8")
    assert "class LogSource(Protocol)" in source
    assert "def available(" in source
    assert "def read(" in source
    assert "class JournalLogSource" in source
    assert "class FileLogSource" in source
    service = (BACKEND / "log_system" / "service.py").read_text(encoding="utf-8")
    assert "resolve_log_source" in service
    assert "elif source" not in service


def test_jobs_own_persistence_and_controlled_runner():
    repository = (BACKEND / "jobs" / "repository.py").read_text(encoding="utf-8")
    runner = (BACKEND / "jobs" / "runner.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS jobs" in repository
    assert "ThreadPoolExecutor" in runner
    assert "threading.Thread" not in runner


def test_package_center_executes_through_global_job_service():
    source = (BACKEND / "package_center" / "jobs.py").read_text(encoding="utf-8")
    assert "JobService" in source
    assert "submit_callable" in source
    assert "threading.Thread" not in source
    assert "JobRunner" not in source


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


def test_generated_types_are_single_source_and_marked_generated():
    generated = ROOT / "frontend" / "src" / "generated" / "api-types.ts"
    assert generated.exists()
    source = generated.read_text(encoding="utf-8")
    assert "AUTO-GENERATED" in source
    assert "DO NOT EDIT" in source
    for path in (ROOT / "frontend" / "src").rglob("api-types.ts"):
        assert path == generated
