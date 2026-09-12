from __future__ import annotations

import importlib
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import settings
from app.app_store import samba
from app.identity.repository import IdentityRepository
from app.modules.cron.repository import CronRepository
from app.modules.providers.docker import DockerProvider
from app.modules.secrets_manager.models import SecretInput
from app.modules.secrets_manager.service import SecretsManagerService

secrets_module = importlib.import_module("app.modules.secrets_manager.service")


def _settings_config(tmp_path: Path):
    return SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path), log_dir=str(tmp_path / "logs")))


def test_user_settings_wrong_shape_or_malformed_json_degrades_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "get_config", lambda: _settings_config(tmp_path))
    path = settings._settings_path("alice")
    path.write_text("[]", encoding="utf-8")
    assert settings._read_settings("alice") == {}
    path.write_text("{", encoding="utf-8")
    assert settings._read_settings("alice") == {}


def test_wallpaper_metadata_wrong_shape_and_bad_timestamp_do_not_break_gallery(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "get_config", lambda: _settings_config(tmp_path))
    wallpaper_id = "a" * 32
    directory = settings._wallpaper_directory("alice")
    image = directory / f"{wallpaper_id}.png"
    image.write_bytes(b"png")
    metadata = directory / f"{wallpaper_id}.json"
    metadata.write_text("[]", encoding="utf-8")
    assert settings._wallpaper_items("alice")[0]["name"] == image.name
    metadata.write_text(json.dumps({"name": "safe.png", "created_at": []}), encoding="utf-8")
    item = settings._wallpaper_items("alice")[0]
    assert item["name"] == "safe.png"
    assert isinstance(item["created_at"], int)


def test_auto_update_wrong_shape_json_degrades_to_default(monkeypatch, tmp_path):
    path = tmp_path / "auto_update.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(settings, "_auto_update_path", lambda: path)
    assert settings._read_auto_update_state() == settings._default_auto_update_state()


def test_git_output_does_not_expose_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "_tool", lambda name: name)
    monkeypatch.setattr(settings, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        settings.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "SECRET /root/token"),
    )
    with pytest.raises(HTTPException) as caught:
        settings._git_output(["ls-remote", "origin"])
    assert caught.value.detail == "Git command failed"
    assert "SECRET" not in str(caught.value.detail)


def test_broker_update_failure_does_not_expose_runtime_error(monkeypatch):
    monkeypatch.setattr(settings, "broker_required", lambda: True)
    monkeypatch.setattr(settings, "update_service", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("SECRET /root/private")))
    with pytest.raises(HTTPException) as caught:
        settings._start_update_process(False, actor="admin")
    assert caught.value.status_code == 503
    assert caught.value.detail == "Could not start the WebNAS update service"


def test_samba_command_failure_does_not_expose_stderr(monkeypatch):
    monkeypatch.setattr(samba, "broker_required", lambda: False)
    monkeypatch.setattr(
        samba.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "SECRET smb.conf path"),
    )
    with pytest.raises(HTTPException) as caught:
        samba._run(["testparm", "-s"])
    assert caught.value.detail == "Samba command failed"
    assert "SECRET" not in str(caught.value.detail)


def test_identity_change_wrong_shape_json_is_safely_normalized(tmp_path):
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO permission_changes(created_at,actor,subject_type,subject,action,previous_json,current_json,status,error_code) VALUES(?,?,?,?,?,?,?,?,?)",
            (time.time(), "admin", "user", "alice", "test", "[]", '"wrong"', "success", ""),
        )
    change = repository.changes(limit=1)[0]
    assert change.previous == {}
    assert change.current == {}


def test_cron_corrupt_environment_and_history_json_do_not_break_reads(tmp_path):
    repository = CronRepository(tmp_path / "cron.sqlite3")
    now = time.time()
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO cron_jobs(id,name,description,username,schedule,command,working_directory,environment_json,timeout_seconds,enabled,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("00000000-0000-4000-8000-000000000001", "Job", "", "root", "* * * * *", "/bin/true", None, "{}", None, 1, now, now, "admin", "admin"),
        )
        connection.execute(
            "INSERT INTO cron_history(job_id,action,actor,details_json,created_at) VALUES(?,?,?,?,?)",
            ("00000000-0000-4000-8000-000000000001", "test", "admin", "[]", now),
        )
    assert repository.list()[0].environment == []
    assert repository.history("00000000-0000-4000-8000-000000000001")[0]["details"] == {}


def test_secrets_audit_corrupt_or_wrong_shape_json_does_not_break_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_module, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path / "data"))))
    root = tmp_path / "data"
    service = SecretsManagerService(
        path=root / "secrets-manager" / "secrets.sqlite3",
        key_path=root / "secrets" / "secrets-manager.key",
        hosts_path=root / "missing-hosts.sqlite3",
        hosts_key_path=root / "secrets" / "hosts-manager.key",
        webhooks_path=root / "missing-webhooks.sqlite3",
    )
    item = service.save(SecretInput(name="demo", type="generic_secret", secret="value"), "admin")
    with service.connect() as connection:
        connection.execute(
            "INSERT INTO secret_audit(id,secret_id,action,consumer_module,purpose,actor,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("audit-bad", item["id"], "test", "", "", "admin", "[]", time.time()),
        )
    assert service.audit(secret_id=item["id"], limit=1)[0]["details"] == {}
    with service.connect() as connection:
        connection.execute("UPDATE secret_audit SET details_json='{' WHERE id='audit-bad'")
    assert service.audit(secret_id=item["id"], limit=1)[0]["details"] == {}


def test_docker_compose_history_skips_valid_non_object_json(tmp_path):
    class FakeProvider:
        compose_dir = tmp_path

        def get_compose(self, project: str):
            return {"project": project}

    history = tmp_path / "demo" / "history"
    history.mkdir(parents=True)
    (history / "bad.json").write_text("[]", encoding="utf-8")
    assert DockerProvider.compose_history(FakeProvider(), "demo") == []
