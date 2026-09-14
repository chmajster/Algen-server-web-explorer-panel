from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import settings, update_coordination
from app.security import SessionUser


REVISION = "a" * 40


@pytest.fixture
def recovery(monkeypatch, tmp_path):
    config = SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "logs")))
    monkeypatch.setattr(settings, "get_config", lambda: config)
    monkeypatch.setattr(update_coordination, "get_config", lambda: config)
    monkeypatch.setattr(settings, "_installed_publication_version", lambda: "2.0")
    monkeypatch.setattr(settings, "repository_versions", lambda: [{"revision": REVISION, "name": "v1.0", "kind": "tag", "published_at": None}])
    monkeypatch.setattr(settings, "get_session_user", lambda _: SessionUser("admin", "csrf"))
    monkeypatch.setattr(settings, "authorize", lambda *args: None)
    monkeypatch.setattr(settings.admin_rate_limiter, "check", lambda _: None)
    monkeypatch.setattr(settings, "_audit", lambda *args: None)
    update_coordination.clear_operation_providers()
    update_coordination.write_update_request({"id": "failure-1", "state": "failed", "phase": "prepare"})
    calls = []
    monkeypatch.setattr(settings, "_start_update_process", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True, "pid": 123, "unit": "webnas-test.service"})
    app = FastAPI()
    app.include_router(settings.router)
    yield TestClient(app), calls
    update_coordination.clear_operation_providers()


def post(client, **payload):
    return client.post("/api/admin/system/updates/recover", headers={"X-CSRF-Token": "csrf"}, json={"revision": REVISION, "failed_update_id": "failure-1", **payload})


def test_recovery_installs_older_or_same_revision_and_preserves_config(recovery):
    client, calls = recovery
    response = post(client)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "running"
    assert calls == [((False,), {"actor": "admin", "npm_audit_fix": False, "revision": REVISION})]
    state = update_coordination.read_update_request()
    assert state["install_revision"] == REVISION
    assert state["target_version"] == "v1.0"
    assert state["recovery_of"] == "failure-1"
    assert not state["update_config"]
    assert post(client).status_code == 409
    assert len(calls) == 1


def test_pin_survives_waiting_and_is_used_after_operations_finish(recovery):
    client, calls = recovery
    operations = [{"id": "copy", "type": "copy", "status": "running"}]
    update_coordination.register_operation_provider("test", lambda: operations)
    response = post(client)
    assert response.json()["state"] == "waiting"
    assert not calls
    queued_id = response.json()["id"]
    assert update_coordination.read_update_request()["install_revision"] == REVISION
    operations.clear()
    assert settings._process_waiting_update(queued_id)["state"] == "running"
    assert calls[0][1]["revision"] == REVISION


@pytest.mark.parametrize("state", ["idle", "completed", "waiting", "preparing", "running"])
def test_non_failed_update_cannot_be_recovered(recovery, state):
    client, calls = recovery
    update_coordination.write_update_request({"id": "failure-1", "state": state})
    assert post(client).status_code == 409
    assert not calls


def test_stale_failure_id_does_not_replace_state(recovery):
    client, calls = recovery
    assert post(client, failed_update_id="old-failure").status_code == 409
    assert update_coordination.read_update_request()["id"] == "failure-1"
    assert not calls


def test_unknown_valid_sha_is_rejected(recovery):
    client, calls = recovery
    assert post(client, revision="b" * 40).status_code == 400
    assert not calls


@pytest.mark.parametrize("payload", [{"revision": "main"}, {"revision": "a" * 40 + ";touch x"}, {"update_config": True}, {"failed_update_id": ""}])
def test_invalid_or_unexpected_recovery_fields_are_rejected(recovery, payload):
    client, calls = recovery
    assert post(client, **payload).status_code == 422
    assert not calls


def test_recovery_requires_csrf(recovery):
    client, calls = recovery
    response = client.post("/api/admin/system/updates/recover", json={"revision": REVISION, "failed_update_id": "failure-1"})
    assert response.status_code == 403
    assert not calls


def test_permission_is_checked_before_fetching_versions(recovery, monkeypatch):
    client, calls = recovery

    def deny(*args):
        raise HTTPException(403, "denied")

    monkeypatch.setattr(settings, "authorize", deny)
    monkeypatch.setattr(settings, "repository_versions", lambda: pytest.fail("repository must not be queried"))
    assert client.get("/api/admin/system/updates/versions").status_code == 403
    assert post(client).status_code == 403
    assert not calls


def test_revision_is_checked_at_process_boundary(recovery):
    # Call the real process boundary through a separate test below; persisted
    # state also rejects invalid or conflicting pins before changing failure state.
    with pytest.raises(HTTPException):
        settings._request_update(actor="admin", update_config=False, install_revision="--help")
    with pytest.raises(HTTPException):
        settings._request_update(actor="admin", update_config=True, status={"remote": REVISION}, install_revision=REVISION)


def test_broker_receives_pinned_revision(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "broker_required", lambda: True)
    monkeypatch.setattr(settings, "update_service", lambda **kwargs: calls.append(kwargs) or {"unit": "webnas-test.service", "pid": None})
    monkeypatch.setattr(settings, "_audit", lambda *args: None)
    settings._start_update_process(False, actor="admin", revision=REVISION)
    assert calls[0]["revision"] == REVISION
    with pytest.raises(HTTPException):
        settings._start_update_process(False, actor="admin", revision="main;id")
    assert len(calls) == 1


def test_anonymous_requests_are_rejected_before_version_lookup(recovery, monkeypatch):
    client, calls = recovery

    def unauthenticated(*args):
        raise HTTPException(401, "Authentication required")

    monkeypatch.setattr(settings, "get_session_user", unauthenticated)
    monkeypatch.setattr(settings, "repository_versions", lambda: pytest.fail("must authenticate first"))
    assert client.get("/api/admin/system/updates/versions").status_code == 401
    assert post(client).status_code == 401
    assert not calls


def test_non_brokered_runner_passes_revision(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(settings, "broker_required", lambda: False)
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "log"))))
    monkeypatch.setattr(settings, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "_tool", lambda name: name)
    monkeypatch.setattr(settings, "_audit", lambda *args: None)

    def run(args, **kwargs):
        if args[0] == "curl":
            return SimpleNamespace(returncode=0, stdout=b"#!/usr/bin/env bash\nexit 0\n")
        progress = settings._update_progress_path()
        data = json.loads(progress.read_text())
        data["pid"] = 456
        progress.write_text(json.dumps(data))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(settings.subprocess, "run", run)
    settings._start_update_process(False, actor="admin", revision=REVISION)
    runner = (tmp_path / "data/settings/update-runner.sh").read_text()
    assert "--revision " + REVISION in runner
    assert "--update-config" not in runner
