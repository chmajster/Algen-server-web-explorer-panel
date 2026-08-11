from __future__ import annotations

import os
import importlib
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.identity.models import Role
from app.identity.permissions import Permission, ROLE_PERMISSIONS, require_permission
from app.modules.cron.models import CronJob, CronJobCreate, CronJobSource, CronJobStatus, CronJobUpdate, CronValidationRequest
from app.modules.cron.schedule import CronExpression, CronSyntaxError, next_occurrence
from app.modules.cron.service import CronReadOnlyError, CronService
from app.modules.cron.system import AtomicCronWriter, CronSystem, parse_external_config, parse_managed_config, render_config, rendered_command
from app.modules.cron import router as cron_router
from app.security import SessionUser


def cron_store(tmp_path: Path, *, system: CronSystem | None = None) -> CronService:
    return CronService(tmp_path / "private" / "cron.sqlite3", tmp_path / "etc" / "webnas", system=system, user_lookup=lambda username: SimpleNamespace(pw_name=username))


@pytest.mark.parametrize("expression", ["* * * * *", "*/5 * * * *", "0 3 1 jan mon", "0 0 * * 7", "@reboot"])
def test_schedule_parser_accepts_standard_expressions(expression: str):
    assert CronExpression.parse(expression)


@pytest.mark.parametrize("expression", ["", "* * * *", "61 * * * *", "*/0 * * * *", "1-0 * * * *", "*;reboot * * * *"])
def test_schedule_parser_rejects_invalid_and_injection_shaped_values(expression: str):
    with pytest.raises((CronSyntaxError, ValueError)):
        CronExpression.parse(expression)


def test_next_occurrence_uses_cron_day_semantics():
    following = next_occurrence("*/5 * * * *", after=datetime.fromisoformat("2026-08-11T18:37:00+02:00"))
    assert following and following.isoformat() == "2026-08-11T18:40:00+02:00"
    assert next_occurrence("@reboot") is None


def test_crud_enable_disable_duplicate_and_delete_are_transactional(tmp_path: Path, monkeypatch):
    audit: list[tuple[str, dict]] = []
    cron_service_module = importlib.import_module("app.modules.cron.service")
    monkeypatch.setattr(cron_service_module, "record_activity", lambda _category, action, _actor, **values: audit.append((action, values)))
    service = cron_store(tmp_path)
    created = service.create(CronJobCreate(name="Backup", user="root", schedule="*/5 * * * *", command="/bin/true"), "admin")
    assert service.config_valid() and created.next_run_at
    assert parse_managed_config(service.config_path.read_text(encoding="utf-8"))[0]["id"] == created.id

    disabled = service.set_enabled(created.id, False, "admin")
    assert disabled.status == CronJobStatus.disabled
    assert "# disabled:" in service.config_path.read_text(encoding="utf-8")
    updated = service.update(created.id, CronJobUpdate(name="Nightly", user="root", schedule="0 3 * * *", command="/bin/true"), "admin")
    assert updated.id == created.id and updated.name == "Nightly"
    duplicate = service.duplicate(created.id, "admin")
    assert duplicate.id != created.id and duplicate.enabled is False
    service.delete(created.id, "admin")
    assert [job.id for job in service.list_jobs(include_external=False)] == [duplicate.id]
    assert {action for action, _ in audit} >= {"cron.job.created", "cron.job.updated", "cron.job.disabled", "cron.job.deleted"}
    assert all("command" not in values.get("details", {}) for _, values in audit)


def test_database_failure_rolls_managed_file_back(tmp_path: Path, monkeypatch):
    service = cron_store(tmp_path)
    before = render_config([])
    service.writer.apply(before)
    monkeypatch.setattr(service.repository, "create", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database failed")))
    with pytest.raises(RuntimeError, match="database failed"):
        service.create(CronJobCreate(name="Unsafe partial", user="root", schedule="* * * * *", command="/bin/true"), "admin")
    assert service.config_path.read_text(encoding="utf-8") == before
    assert service.repository.list() == []


def test_post_write_verification_failure_rolls_back(tmp_path: Path, monkeypatch):
    service = cron_store(tmp_path)
    service.writer.apply(render_config([]))
    original = service.config_path.read_bytes()
    monkeypatch.setattr(service.writer, "verify", lambda _expected: (_ for _ in ()).throw(RuntimeError("verification failed")))
    with pytest.raises(RuntimeError, match="verification failed"):
        service.create(CronJobCreate(name="Rollback", user="root", schedule="* * * * *", command="/bin/true"), "admin")
    assert service.config_path.read_bytes() == original


def test_atomic_writer_uses_private_backup_and_safe_cron_mode():
    root_parent = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
    root = Path(tempfile.mkdtemp(prefix="webnas-cron-test-", dir=root_parent))
    try:
        target = root / "cron.d" / "webnas"
        writer = AtomicCronWriter(target, root / "backups", enforce_permissions=False)
        writer.apply(render_config([]))
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
        assert target.stat().st_uid == os.geteuid()
        writer.apply(render_config([]) + "\n")
        backups = list((root / "backups").glob("*.cron.bak"))
        assert backups and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    finally:
        shutil.rmtree(root)


def test_external_entries_are_stable_and_read_only(tmp_path: Path):
    values = parse_external_config("*/10 * * * * root /usr/local/bin/report\n", source=CronJobSource.cron_d, source_label="/etc/cron.d/report", system=True)
    assert len(values) == 1 and values[0].read_only and values[0].status == CronJobStatus.external
    assert values[0].id == parse_external_config("*/10 * * * * root /usr/local/bin/report\n", source=CronJobSource.cron_d, source_label="/etc/cron.d/report", system=True)[0].id
    service = cron_store(tmp_path)
    service._external_cache = (float("inf"), values)
    with pytest.raises(CronReadOnlyError):
        service.set_enabled(values[0].id, False, "admin")


def test_external_parser_marks_bad_lines_invalid_without_adopting_them():
    values = parse_external_config("bad schedule root reboot\n", source=CronJobSource.system_crontab, source_label="/etc/crontab", system=True)
    assert values[0].status == CronJobStatus.invalid
    assert values[0].source == CronJobSource.system_crontab
    assert values[0].read_only is True


def test_cron_and_crond_detection_uses_fixed_argument_arrays(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("app.modules.cron.system.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"systemctl", "crontab"} else None)

    def runner(args, **kwargs):
        calls.append(args)
        assert kwargs.get("shell") is False
        loaded = args[2].startswith("crond")
        return subprocess.CompletedProcess(args, 0, "loaded\n" if loaded else "not-found\n", "")

    system = CronSystem(runner=runner)
    assert system.daemon() == "crond"
    assert all(call[:2] == ["/usr/bin/systemctl", "show"] for call in calls)


def test_command_is_rendered_as_configuration_and_never_executed(monkeypatch):
    executed: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: executed.append((args, kwargs)))
    job = CronJob(id="11111111-1111-4111-8111-111111111111", name="Shell data", user="root", schedule="* * * * *", command="echo ok; touch /tmp/example", working_directory="/srv", environment=[{"name": "LANG", "value": "C"}], timeout_seconds=30)
    rendered = rendered_command(job)
    assert "/usr/bin/timeout" in rendered and "/bin/sh -c" in rendered and "touch /tmp/example" in rendered
    assert executed == []
    with pytest.raises(ValidationError):
        CronJobCreate(name="bad", user="root;reboot", schedule="* * * * *", command="/bin/true")
    with pytest.raises(ValidationError):
        CronJobCreate(name="bad", user="root", schedule="* * * * *", command="/bin/true\nreboot")


def test_diagnostics_report_missing_user_duplicate_and_executable(tmp_path: Path):
    existing = {"root"}
    service = CronService(tmp_path / "data" / "cron.sqlite3", tmp_path / "etc" / "webnas", user_lookup=lambda username: SimpleNamespace() if username in existing else (_ for _ in ()).throw(KeyError(username)))
    service.create(CronJobCreate(name="One", user="root", schedule="* * * * *", command="/definitely/missing"), "admin")
    service.create(CronJobCreate(name="Two", user="root", schedule="* * * * *", command="/definitely/missing"), "admin")
    codes = {item.code: item.status for item in service.diagnostics(blocked_by_proxmox=True)}
    assert codes["duplicates"] == "warning"
    assert codes["proxmox-safe-mode"] == "warning"
    assert any(code.startswith("executable-") and value == "warning" for code, value in codes.items())


def test_logs_are_bounded_filtered_and_redacted(tmp_path: Path):
    system = CronSystem()
    system.log_sources = lambda: [{"id": "journal:cron", "label": "cron"}]  # type: ignore[method-assign]
    system.logs = lambda _source, _limit: ["root backup token=abc", "alice cleanup"]  # type: ignore[method-assign]
    service = cron_store(tmp_path, system=system)
    result = service.logs("journal:cron", limit=1, search="backup")
    assert len(result["entries"]) == 1
    assert "abc" not in result["entries"][0]["message"]
    assert "[REDACTED]" in result["entries"][0]["message"]


def test_rbac_defaults_and_csrf_dependency(monkeypatch):
    assert Permission.CRON_DELETE.value in ROLE_PERMISSIONS[Role.admin]
    assert Permission.CRON_EDIT.value in ROLE_PERMISSIONS[Role.operator]
    assert Permission.CRON_DELETE.value not in ROLE_PERMISSIONS[Role.operator]
    assert {Permission.CRON_VIEW.value, Permission.CRON_LOGS.value} <= ROLE_PERMISSIONS[Role.auditor]
    assert not any(value.startswith("cron.") for value in ROLE_PERMISSIONS[Role.user])
    user = SessionUser(username="admin", csrf_token="csrf")
    monkeypatch.setattr("app.identity.permissions.get_session_user", lambda _request: user)
    monkeypatch.setattr("app.identity.permissions.authorize", lambda current, permission: None)
    dependency = require_permission(Permission.CRON_CREATE)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    with pytest.raises(HTTPException) as error:
        dependency(request)
    assert error.value.status_code == 403
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"x-csrf-token", b"csrf")]})
    assert dependency(request) == user


def test_api_models_validate_schedule_and_proxmox_safe_mode(monkeypatch):
    with pytest.raises(ValidationError):
        CronValidationRequest(schedule="* *;shutdown * * *", command="/bin/true").definition()
    monkeypatch.setattr(cron_router, "_ready", lambda: None)
    monkeypatch.setattr(cron_router, "get_module", lambda _module_id: {"blocked_by_proxmox": True})
    with pytest.raises(HTTPException) as error:
        cron_router._enqueue("job_enable", SessionUser(username="admin", csrf_token="csrf"), job_id="11111111-1111-4111-8111-111111111111")
    assert error.value.status_code == 403


def test_managed_parser_rejects_tampered_markers():
    job = CronJob(id="11111111-1111-4111-8111-111111111111", name="One", user="root", schedule="* * * * *", command="/bin/true")
    content = render_config([job])
    assert parse_managed_config(content)[0]["enabled"] is True
    with pytest.raises(ValueError, match="enabled|disabled"):
        parse_managed_config(content.replace("# enabled: true", "# enabled: false"))
