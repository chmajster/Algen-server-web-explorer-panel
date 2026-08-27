import pytest
from fastapi import HTTPException

from app import resource_processes
from app.security import SessionUser


def test_system_processes_requires_status_permission_and_requests_full_list(monkeypatch):
    calls = []
    user = SessionUser(username="root", csrf_token="token")
    monkeypatch.setattr(resource_processes, "authorize", lambda current, permission: calls.append((current.username, permission)))
    monkeypatch.setattr(resource_processes, "access_profile", lambda username: {"is_admin": True})
    monkeypatch.setattr(resource_processes, "top_processes", lambda limit: [{"pid": 1, "limit": limit}])

    result = resource_processes.system_processes(user)

    assert calls == [("root", "system.status")]
    assert result == [{"pid": 1, "limit": None}]


def test_system_processes_rejects_non_admin(monkeypatch):
    user = SessionUser(username="alice", csrf_token="token")
    monkeypatch.setattr(resource_processes, "authorize", lambda current, permission: None)
    monkeypatch.setattr(resource_processes, "access_profile", lambda username: {"is_admin": False})

    with pytest.raises(HTTPException) as error:
        resource_processes.system_processes(user)

    assert error.value.status_code == 403
