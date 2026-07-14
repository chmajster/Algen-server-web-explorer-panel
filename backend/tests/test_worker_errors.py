from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import file_ops


@pytest.mark.parametrize(
    ("code", "status"),
    [("already_exists", 409), ("not_found", 404), ("permission_denied", 403), ("no_space", 507)],
)
def test_worker_errors_are_mapped_to_safe_api_responses(monkeypatch, code, status):
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        file_ops.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=f'{{"error":"{code}"}}', stdout=""),
    )

    with pytest.raises(HTTPException) as exc:
        file_ops.run_user_op("alice", "stat", {"path": "/home/alice/item"})

    assert exc.value.status_code == status
    assert exc.value.detail["code"] == code
    assert "Traceback" not in exc.value.detail["message"]


def test_raw_worker_traceback_is_not_exposed(monkeypatch):
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        file_ops.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="Traceback: sensitive internal path", stdout=""),
    )

    with pytest.raises(HTTPException) as exc:
        file_ops.run_user_op("alice", "stat", {"path": "/home/alice/item"})

    assert exc.value.detail == {"code": "operation_failed", "message": "File operation failed"}
