from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import file_ops
from app.services import file_task_manager as file_task_module
from app.services import rsync_tasks
from app.services.file_task_manager import FileTaskManager
from app.sqlite_utils import ClosingConnection


def test_local_file_worker_invalid_json_is_normalized(monkeypatch):
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(
        file_ops.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", ""),
    )

    with pytest.raises(HTTPException) as caught:
        file_ops.run_user_op("alice", "list", {})

    assert caught.value.status_code == 500
    assert caught.value.detail == "File worker returned an invalid response"
    assert "not-json" not in str(caught.value.detail)


def test_stored_status_ignores_corrupt_database_value(tmp_path):
    database = tmp_path / "transfers.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE file_tasks (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        connection.execute("INSERT INTO file_tasks (id, status) VALUES (?, ?)", ("task-1", "definitely-invalid"))

    manager = object.__new__(FileTaskManager)
    manager._connect = lambda: sqlite3.connect(database, factory=ClosingConnection)  # type: ignore[method-assign]

    assert manager._stored_status("task-1") is None


def test_transfer_database_fallback_is_private(monkeypatch, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    fallback_parent = tmp_path / "fallback"
    fallback_parent.mkdir()
    monkeypatch.setattr(file_task_module.tempfile, "gettempdir", lambda: str(fallback_parent))

    manager = object.__new__(FileTaskManager)
    manager._db_path = blocker / "transfers.sqlite3"
    connection = manager._connect()
    database_path = manager._db_path
    connection.close()

    fallback_root = database_path.parent
    assert fallback_root.parent == fallback_parent
    assert stat.S_IMODE(fallback_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    expected_suffix = str(os.getuid()) if hasattr(os, "getuid") else str(os.getpid())
    assert fallback_root.name == f"webnas-{expected_suffix}"


def test_partial_cleanup_revalidates_persisted_destination(monkeypatch, tmp_path):
    calls: list[Path] = []

    def reject(path, *args, **kwargs):
        calls.append(Path(path))
        raise HTTPException(403, "blocked")

    monkeypatch.setattr(rsync_tasks, "assert_path_allowed", reject)
    monkeypatch.setattr(
        rsync_tasks.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("rm must not run")),
    )

    with pytest.raises(HTTPException) as caught:
        rsync_tasks.cleanup_partial_files("alice", tmp_path / "outside", lambda _line: None)

    assert caught.value.status_code == 403
    assert calls == [tmp_path / "outside"]
