from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import settings
from app.config import AppConfig


def cfg(threshold: int = 1000):
    return AppConfig.model_validate({"security": {"system_uid_threshold": threshold}, "proxmox": {"detect": False, "safe_mode": False}})


def pw(name: str, uid: int = 1001, gid: int = 1001, home: str | None = None):
    return SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid, pw_dir=home or f"/home/{name}", pw_shell="/bin/bash", pw_gecos="")


def test_rejects_protected_local_user(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg())
    monkeypatch.setattr(settings.pwd, "getpwnam", lambda username: pw(username, 0))

    with pytest.raises(HTTPException) as exc:
        settings._assert_manageable_user("root", action="lock")

    assert exc.value.status_code == 403


def test_rejects_uid_below_threshold(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg())
    monkeypatch.setattr(settings.pwd, "getpwnam", lambda username: pw(username, 999))

    with pytest.raises(HTTPException) as exc:
        settings._assert_manageable_user("serviceuser", action="update")

    assert exc.value.status_code == 403


def test_allows_regular_user(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg())
    monkeypatch.setattr(settings.pwd, "getpwnam", lambda username: pw(username, 1001))

    assert settings._assert_manageable_user("alice", action="update").pw_name == "alice"


def test_rejects_protected_group(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg())

    with pytest.raises(HTTPException):
        settings._assert_manageable_group("sudo")


def test_admin_users_filters_system_accounts(monkeypatch):
    monkeypatch.setattr(settings, "get_config", lambda: cfg())
    monkeypatch.setattr(settings, "_is_admin", lambda username: True)
    accounts = [pw("root", 0), pw("alice", 1001), pw("www-data", 33)]
    monkeypatch.setattr(settings.pwd, "getpwall", lambda: accounts)
    monkeypatch.setattr(settings.pwd, "getpwnam", lambda username: next(account for account in accounts if account.pw_name == username))
    monkeypatch.setattr(settings, "_groups_for", lambda username: [])

    result = settings.admin_users(SimpleNamespace(username="admin"))

    assert [item["username"] for item in result] == ["alice"]


def test_quota_uses_setquota_when_available(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "get_config", lambda: cfg())
    monkeypatch.setattr(settings, "_require_admin", lambda *args, **kwargs: None)
    monkeypatch.setattr(settings, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(settings.pwd, "getpwnam", lambda username: pw(username, 1001, home="/home/alice"))
    monkeypatch.setattr(settings.shutil, "which", lambda name: "/usr/sbin/setquota" if name == "setquota" else None)
    monkeypatch.setattr(settings, "_run", lambda args, **kwargs: calls.append(args))

    result = settings.admin_user_quota("alice", settings.UserQuota(soft_mb=1024), SimpleNamespace(client=None), SimpleNamespace(username="admin"))

    assert result["ok"] is True
    assert calls == [["/usr/sbin/setquota", "-u", "alice", "1048576", "1048576", "0", "0", "/"]]
