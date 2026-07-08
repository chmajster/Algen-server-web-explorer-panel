from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import settings
from app.config import AppConfig


def cfg(allowed: list[str]):
    return AppConfig.model_validate({"systemd": {"allowed_services": allowed}, "proxmox": {"detect": False, "safe_mode": False}})


def test_critical_service_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg(["ssh.service"]))

    with pytest.raises(HTTPException) as exc:
        settings._assert_systemd_service_allowed("ssh.service")

    assert exc.value.status_code == 403


def test_service_must_be_allowlisted(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg(["webnas.service"]))

    with pytest.raises(HTTPException) as exc:
        settings._assert_systemd_service_allowed("docker.service")

    assert exc.value.status_code == 403


def test_allowlisted_service_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg(["docker.service"]))

    assert settings._assert_systemd_service_allowed("docker") == "docker.service"


def test_restart_requires_confirmation(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg(["webnas.service"]))

    with pytest.raises(HTTPException) as exc:
        settings.admin_systemd_service_action("webnas.service", "restart", settings.ServiceAction(admin_password="secret"), SimpleNamespace(client=None), SimpleNamespace(username="admin"))

    assert exc.value.status_code == 400


def test_service_action_is_audited(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "get_config", lambda: cfg(["webnas.service"]))
    monkeypatch.setattr(settings, "_require_admin", lambda *args, **kwargs: None)
    monkeypatch.setattr(settings, "_run", lambda args: calls.append(args))
    monkeypatch.setattr(settings, "_audit", lambda actor, action, target: calls.append([action, target]))
    monkeypatch.setattr(settings, "_service_payload", lambda service: {"name": service})

    result = settings.admin_systemd_service_action("webnas", "start", settings.ServiceAction(admin_password="secret"), SimpleNamespace(client=None), SimpleNamespace(username="admin"))

    assert result == {"name": "webnas.service"}
    assert ["systemd_start", "webnas.service"] in calls
