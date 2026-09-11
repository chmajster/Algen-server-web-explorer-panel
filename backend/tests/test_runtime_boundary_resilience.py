from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import power_control
from app.log_system import api as logs_api
from app.log_system import sources as log_sources


def _user():
    return SimpleNamespace(username="auditor")


def test_log_service_failure_does_not_expose_systemctl_stderr(monkeypatch):
    monkeypatch.setattr(logs_api, "authorize", lambda *args, **kwargs: None)
    monkeypatch.setattr(logs_api.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(logs_api, "run_bounded", lambda *args, **kwargs: (1, "", "secret path=/srv/private token=abc"))
    with pytest.raises(HTTPException) as error:
        logs_api.log_service("ssh.service", _user())
    assert error.value.status_code == 404
    assert "secret" not in str(error.value.detail)
    assert "/srv/private" not in str(error.value.detail)


def test_log_lists_do_not_expose_command_stderr(monkeypatch):
    monkeypatch.setattr(logs_api, "authorize", lambda *args, **kwargs: None)
    monkeypatch.setattr(logs_api.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(logs_api, "run_bounded", lambda *args, **kwargs: (1, "", "token=abc /srv/private"))
    services = logs_api.log_services(_user())
    containers = logs_api.log_containers(_user())
    assert services["error"] == "systemctl could not list services"
    assert containers["error"] == "docker could not list containers"


def test_journal_failure_does_not_expose_raw_stderr(monkeypatch):
    monkeypatch.setattr(log_sources.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(log_sources, "run_bounded", lambda *args, **kwargs: (1, "", "token=abc /srv/private"))
    with pytest.raises(HTTPException) as error:
        log_sources.journal_entries(
            "journal", limit=10, priority=[], unit="", pid=None, uid=None, identifier="", transport="", hostname="", device="",
            username="", group="", boot_id="", since=None, until=None, continuation={}, direction="older",
        )
    assert error.value.status_code == 502
    assert error.value.detail == "journalctl could not read logs"


def test_power_schedule_failure_does_not_expose_system_stderr(monkeypatch):
    monkeypatch.setattr(power_control, "broker_required", lambda: False)
    monkeypatch.setattr(power_control.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        power_control.subprocess,
        "run",
        lambda *args, **kwargs: power_control.subprocess.CompletedProcess(args[0], 1, "", "token=abc path=/srv/private"),
    )
    with pytest.raises(HTTPException) as error:
        power_control._schedule_systemctl("host-restart", "reboot")
    assert error.value.status_code == 500
    assert error.value.detail == "Could not schedule host-restart"
    assert "token=abc" not in str(error.value.detail)
