import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import settings, update_coordination
from app.security import SessionUser


@pytest.fixture
def update_environment(monkeypatch, tmp_path):
    config = SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "logs")))
    monkeypatch.setattr(settings, "get_config", lambda: config)
    monkeypatch.setattr(update_coordination, "get_config", lambda: config)
    monkeypatch.setattr(settings, "_installed_publication_version", lambda: "2.0.0")
    update_coordination.clear_operation_providers()
    yield tmp_path
    update_coordination.clear_operation_providers()


def update_status():
    return {
        "available": True,
        "update_available": True,
        "installed_version": "1.0.0",
        "available_version": "2.0.0",
        "remote": "c" * 40,
        "released_at": 1_784_289_600,
    }


def running_process():
    return {"ok": True, "pid": 123, "unit": "webnas-self-update.service", "log": "/var/log/webnas/update.log"}


def blocker(operation_type: str, status: str = "running"):
    return {
        "id": f"{operation_type}-1",
        "type": operation_type,
        "status": status,
        "created_at": 10,
        "started_at": 11,
        "finished_at": None,
        "progress": 25,
        "description": operation_type,
        "user_id": "alice",
    }


def test_update_without_active_operations_starts_immediately(monkeypatch, update_environment):
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: running_process())

    result = settings._request_update(actor="admin", update_config=False, status=update_status())

    assert result["state"] == "running"
    assert result["active_count"] == 0
    request_state = update_coordination.read_update_request()
    assert request_state["state"] == "running"
    assert request_state["commit_revision"] == "c" * 40
    assert request_state["commit_date"] == 1_784_289_600


@pytest.mark.parametrize("operation_type", ["copy", "move", "package.install"])
def test_update_waits_for_active_file_and_package_operations(monkeypatch, update_environment, operation_type):
    operations = [blocker(operation_type, "queued")]
    update_coordination.register_operation_provider("test", lambda: operations)
    started = []
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: started.append(True) or running_process())

    result = settings._request_update(actor="admin", update_config=False, status=update_status())

    assert result["state"] == "waiting"
    assert result["active_count"] == 1
    assert result["blockers"][0]["type"] == operation_type
    assert result["blockers"][0]["status"] == "queued"
    assert not started


def test_waiting_update_starts_automatically_after_operations_finish(monkeypatch, update_environment):
    operations = [blocker("copy")]
    update_coordination.register_operation_provider("files", lambda: operations)
    started = []
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: started.append(True) or running_process())
    waiting = settings._request_update(actor="admin", update_config=False, status=update_status())

    operations.clear()
    result = settings._process_waiting_update(waiting["id"])

    assert result["state"] == "running"
    assert started == [True]


def test_transient_file_operation_is_registered_before_update_admission(monkeypatch, update_environment):
    update_coordination.register_operation_provider("direct", update_coordination.active_transient_operations)
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: running_process())

    with update_coordination.transient_operation("file.write", description="notes.txt", user_id="alice"):
        result = settings._request_update(actor="admin", update_config=False, status=update_status())

    assert result["state"] == "waiting"
    assert result["blockers"][0]["type"] == "file.write"
    assert result["blockers"][0]["description"] == "notes.txt"


def test_second_update_request_is_rejected(monkeypatch, update_environment):
    update_coordination.register_operation_provider("files", lambda: [blocker("copy")])
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: running_process())
    settings._request_update(actor="admin", update_config=False, status=update_status())

    with pytest.raises(HTTPException) as raised:
        settings._request_update(actor="admin", update_config=False, status=update_status())

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "UPDATE_ALREADY_ACTIVE"


def test_new_operations_are_rejected_while_update_is_running(update_environment):
    update_coordination.write_update_request({"id": "update-1", "state": "running", "phase": "installing"})

    with pytest.raises(HTTPException) as raised:
        with update_coordination.operation_admission():
            pytest.fail("operation must not be admitted")

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "UPDATE_IN_PROGRESS"


def test_update_state_survives_backend_restart(update_environment):
    update_coordination.write_update_request({
        "id": "update-1",
        "state": "running",
        "phase": "installing",
        "actor": "admin",
        "started_at": 100,
        "previous_version": "1.0.0",
        "target_version": "2.0.0",
    })

    recovered = update_coordination.read_update_request()

    assert recovered["id"] == "update-1"
    assert recovered["state"] == "running"
    assert recovered["previous_version"] == "1.0.0"


def test_orphaned_preparing_update_fails_safely_after_restart(update_environment):
    update_coordination.write_update_request({
        "id": "update-1",
        "state": "preparing",
        "phase": "preparing",
        "requested_at": 1,
        "started_at": 1,
        "previous_version": "1.0.0",
        "target_version": "2.0.0",
    })

    recovered = settings._update_progress()

    assert recovered["state"] == "failed"
    assert recovered["phase"] == "failed"
    assert "odzyskać stanu aktualizacji" in recovered["message"]


def test_failed_update_is_persisted_and_does_not_report_success(monkeypatch, update_environment):
    def fail(*args, **kwargs):
        raise HTTPException(503, "installer failed")

    monkeypatch.setattr(settings, "_start_update_process", fail)

    result = settings._request_update(actor="admin", update_config=False, status=update_status())

    assert result["state"] == "failed"
    assert result["phase"] == "failed"
    assert result["failed_phase"] == "preparing"
    assert "installer failed" in result["message"]
    assert update_coordination.read_update_request()["state"] == "failed"


def test_completion_notice_is_acknowledged_once_per_user(monkeypatch, update_environment):
    monkeypatch.setattr(settings, "authorize", lambda *args, **kwargs: None)
    update_coordination.write_update_request({
        "id": "update-1",
        "state": "completed",
        "previous_version": "1.0.0",
        "current_version": "2.0.0",
        "finished_at": 200,
        "commit_revision": "c" * 40,
        "commit_date": 1_784_289_600,
    })
    user = SessionUser(username="admin", csrf_token="csrf")

    assert settings.admin_updates_completion(user)["notice"] == {
        "id": "update-1",
        "previous_version": "1.0.0",
        "current_version": "2.0.0",
        "finished_at": 200,
        "commit_revision": "c" * 40,
        "commit_date": 1_784_289_600,
    }
    settings.admin_updates_completion_acknowledge(settings.UpdateCompletionAck(update_id="update-1"), user)
    assert settings.admin_updates_completion(user)["notice"] is None


def test_legacy_completion_notice_derives_installed_commit_metadata(monkeypatch, update_environment):
    revision = "d" * 40
    monkeypatch.setattr(settings, "authorize", lambda *args, **kwargs: None)
    monkeypatch.setattr(settings, "_installed_revision", lambda: revision)
    monkeypatch.setattr(settings, "_remote_release_timestamp", lambda value: 1_784_300_000 if value == revision else None)
    update_coordination.write_update_request({
        "id": "update-legacy",
        "state": "completed",
        "previous_version": "1.0.0",
        "current_version": "2.0.0",
        "finished_at": 200,
    })

    notice = settings.admin_updates_completion(SessionUser(username="admin", csrf_token="csrf"))["notice"]

    assert notice["commit_revision"] == revision
    assert notice["commit_date"] == 1_784_300_000


def test_stale_completion_ack_does_not_acknowledge_a_new_update(monkeypatch, update_environment):
    monkeypatch.setattr(settings, "authorize", lambda *args, **kwargs: None)
    update_coordination.write_update_request({
        "id": "update-2",
        "state": "completed",
        "previous_version": "2.0.0",
        "current_version": "3.0.0",
        "finished_at": 300,
    })
    user = SessionUser(username="admin", csrf_token="csrf")

    result = settings.admin_updates_completion_acknowledge(settings.UpdateCompletionAck(update_id="update-1"), user)

    assert result == {"ok": False, "stale": True}
    assert settings.admin_updates_completion(user)["notice"]["id"] == "update-2"


def test_user_without_update_permission_cannot_read_completion(monkeypatch, update_environment):
    def deny(*args, **kwargs):
        raise HTTPException(403, "Brak uprawnień")

    monkeypatch.setattr(settings, "authorize", deny)

    with pytest.raises(HTTPException) as raised:
        settings.admin_updates_completion(SessionUser(username="operator", csrf_token="csrf"))

    assert raised.value.status_code == 403


def test_public_update_status_hides_logs_and_operation_details(monkeypatch, update_environment):
    monkeypatch.setattr(settings, "_update_progress", lambda: {
        "id": "update-1",
        "state": "waiting",
        "phase": "waiting",
        "running": True,
        "progress": 5,
        "requested_at": 100,
        "started_at": None,
        "finished_at": None,
        "previous_version": "1.0.0",
        "target_version": "2.0.0",
        "current_version": "1.0.0",
        "message": "Oczekiwanie",
        "active_count": 1,
        "blockers": [{"id": "secret-id", "type": "copy", "status": "running", "started_at": 90, "progress": 25, "description": "/home/alice/private"}],
        "log": "update.log",
        "lines": ["Authorization: Bearer secret"],
    })

    result = settings.system_update_status(SessionUser(username="operator", csrf_token="csrf"))

    assert result["lines"] == []
    assert result["log"] == ""
    assert result["blockers"][0]["id"] == "operation-1"
    assert result["blockers"][0]["description"] == ""


def test_update_status_route_serves_spa_after_a_full_reload(monkeypatch, tmp_path):
    from app import http_api

    frontend = tmp_path / "dist"
    frontend.mkdir()
    index = frontend / "index.html"
    index.write_text("<!doctype html><title>WebNAS</title>", encoding="utf-8")
    monkeypatch.setattr(http_api, "frontend_dist", frontend)

    response = http_api.update_status_frontend()

    assert Path(response.path) == index


def test_health_exposes_only_a_planned_handover_phase(monkeypatch):
    from app import http_api

    monkeypatch.setattr(http_api, "read_update_request", lambda: {
        "id": "update-1", "state": "running", "phase": "switching",
    })
    assert http_api.health() == {
        "status": "ok", "service": "webnas", "deployment_phase": "switching", "update_id": "update-1",
    }

    monkeypatch.setattr(http_api, "read_update_request", lambda: {
        "id": "update-1", "state": "running", "phase": "installing",
    })
    assert http_api.health()["deployment_phase"] is None


def test_update_progress_preserves_switching_phase_from_durable_request(monkeypatch, update_environment):
    update_coordination.write_update_request({
        "id": "update-1", "state": "running", "phase": "switching", "requested_at": 10, "started_at": 11,
    })
    progress_path = settings._update_progress_path()
    progress_path.write_text(json.dumps({
        "running": True, "exit_code": None, "started_at": 11, "finished_at": None,
        "pid": 123, "unit": "webnas-self-update.service",
    }), encoding="utf-8")
    monkeypatch.setattr(settings.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    result = settings._update_progress()

    assert result["id"] == "update-1"
    assert result["phase"] == "switching"
    assert result["progress"] == 88


def test_visible_update_log_is_scrubbed(monkeypatch, update_environment):
    progress_path = settings._update_progress_path()
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps({"running": False, "exit_code": 1, "started_at": 10, "finished_at": 20, "pid": 1, "unit": "update.service"}), encoding="utf-8")
    log_path = update_environment / "logs" / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("Authorization: Bearer secret-token\npassword=hunter2\n/home/alice/private/file\n", encoding="utf-8")

    result = settings._update_progress()
    visible = "\n".join(result["lines"])

    assert "secret-token" not in visible
    assert "hunter2" not in visible
    assert "/home/alice" not in visible


def test_canonical_update_steps_have_the_required_order(update_environment):
    assert update_coordination.UPDATE_STEPS == (
        "prepare", "check_operations", "check_update", "download_repository", "download_version", "verify_files",
        "install_backend_dependencies", "install_frontend_dependencies", "build_frontend", "update_configuration",
        "switch_version", "restart_services", "health_check", "complete",
    )


def test_step_transition_is_atomic_and_persists_timestamps(update_environment):
    update_coordination.write_update_request({"id": "update-steps", "state": "running"})
    started = update_coordination.start_update_step("download_version", "Downloading")
    completed = update_coordination.complete_update_step("download_version", "Downloaded")
    step = next(item for item in completed["steps"] if item["id"] == "download_version")

    assert next(item for item in started["steps"] if item["id"] == "download_version")["status"] == "running"
    assert step["status"] == "success"
    assert step["started_at"] is not None
    assert step["finished_at"] >= step["started_at"]
    assert update_coordination.read_update_request()["steps"] == completed["steps"]


def test_failed_step_records_failed_phase_and_redacts_secrets(update_environment):
    update_coordination.write_update_request({"id": "update-failed", "state": "running"})
    failed = update_coordination.fail_update_step("build_frontend", "token=abc123 build failed")
    step = next(item for item in failed["steps"] if item["id"] == "build_frontend")

    assert failed["state"] == "failed"
    assert failed["failed_phase"] == "build_frontend"
    assert step["status"] == "failed"
    assert "abc123" not in step["error"]


def test_legacy_request_without_steps_is_normalized(update_environment):
    path = update_coordination.update_request_path()
    path.write_text(json.dumps({"id": "legacy", "state": "running", "phase": "installing"}), encoding="utf-8")
    recovered = update_coordination.read_update_request()

    assert [step["id"] for step in recovered["steps"]] == list(update_coordination.UPDATE_STEPS)
    assert all(step["status"] == "pending" for step in recovered["steps"])
    assert recovered["phase"] == "installing"


def test_no_available_update_completes_and_skips_installation_steps(update_environment):
    state = settings._record_up_to_date(actor="admin", status={"installed_version": "2.0.0", "available_version": "2.0.0", "remote": "c" * 40})

    assert state["state"] == "completed"
    assert state["message"] == "System jest aktualny."
    assert state["progress"] == 100
    assert next(step for step in state["steps"] if step["id"] == "check_update")["status"] == "success"
    assert next(step for step in state["steps"] if step["id"] == "download_version")["status"] == "skipped"


def test_restart_service_phase_is_finalized_after_backend_returns(update_environment):
    steps = update_coordination.default_update_steps()
    next(step for step in steps if step["id"] == "restart_services").update({"status": "running", "started_at": 1})
    update_coordination.write_update_request({
        "id": "update-restart", "state": "running", "phase": "restart_services", "requested_at": 1, "started_at": 1, "steps": steps,
    })

    recovered = settings._update_progress()

    assert recovered["state"] == "completed"
    assert recovered["progress"] == 100
    assert next(step for step in recovered["steps"] if step["id"] == "health_check")["status"] == "success"
