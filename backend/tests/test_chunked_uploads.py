from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import uploads


def configure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(uploads, "get_config", lambda: SimpleNamespace(security=SimpleNamespace(max_upload_size_mb=20)))
    monkeypatch.setattr(uploads, "resolve_user_path", lambda username, path: Path(path))
    monkeypatch.setattr(uploads, "assert_path_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(uploads, "assert_write_allowed", lambda path: None)
    monkeypatch.setattr(uploads, "ensure_temp_dir", lambda: tmp_path)
    monkeypatch.setattr(uploads.pwd, "getpwnam", lambda username: SimpleNamespace(pw_uid=1000, pw_gid=1000))
    monkeypatch.setattr(uploads.os, "chown", lambda *args: None, raising=False)
    imported: list[dict] = []
    monkeypatch.setattr(uploads, "run_user_op", lambda username, operation, payload: imported.append(payload) or {"ok": True})
    return imported


def test_chunked_upload_resumes_from_the_reported_offset(monkeypatch, tmp_path):
    imported = configure(monkeypatch, tmp_path)
    started = uploads.start_upload("alice", "/home/alice", "report.txt", 6)
    upload_id = started["upload_id"]

    first = uploads.append_upload("alice", upload_id, 0, b"abc")
    assert first["offset"] == 3
    assert first["completed"] is False

    finished = uploads.append_upload("alice", upload_id, 3, b"def")
    assert finished["offset"] == 6
    assert finished["completed"] is True
    assert imported[0]["dst"] == str(Path("/home/alice/report.txt"))
    assert not list(tmp_path.glob("*.upload"))


def test_chunked_upload_rejects_an_incorrect_offset(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    started = uploads.start_upload("alice", "/home/alice", "report.txt", 6)
    with pytest.raises(HTTPException) as error:
        uploads.append_upload("alice", started["upload_id"], 2, b"abc")
    assert error.value.status_code == 409
    uploads.cancel_upload("alice", started["upload_id"])


def test_upload_session_is_private_to_its_owner(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    started = uploads.start_upload("alice", "/home/alice", "report.txt", 3)
    with pytest.raises(HTTPException) as error:
        uploads.append_upload("bob", started["upload_id"], 0, b"abc")
    assert error.value.status_code == 403
    uploads.cancel_upload("alice", started["upload_id"])
