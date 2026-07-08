from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import file_task_manager, rsync_tasks
from app.services.file_task_manager import FileTask, FileTaskManager, TaskStatus


def test_parse_progress2_line():
    parsed = rsync_tasks.parse_progress_line("      1,024  50%    1.00MB/s    0:00:02 (xfr#1, to-chk=1/2)")

    assert parsed["bytes_transferred"] == 1024
    assert parsed["progress_percent"] == 50
    assert parsed["speed_bps"] == 1024 * 1024
    assert parsed["eta_seconds"] == 2


def test_missing_rsync_returns_clear_error(monkeypatch):
    monkeypatch.setattr(rsync_tasks, "get_config", lambda: SimpleNamespace(file_tasks=SimpleNamespace(rsync_path=None)))
    monkeypatch.setattr(rsync_tasks.shutil, "which", lambda name: None)

    with pytest.raises(HTTPException) as exc:
        rsync_tasks.find_rsync()

    assert exc.value.status_code == 503
    assert "rsync" in exc.value.detail


def test_create_copy_task_is_queued(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager()
    task = manager.create_transfer("alice", "copy", [str(tmp_path / "a")], str(tmp_path / "b"))

    assert task.id
    assert task.type == "copy"
    assert task.status == TaskStatus.queued


def test_create_move_task_is_queued(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager()
    task = manager.create_transfer("alice", "move", [str(tmp_path / "a")], str(tmp_path / "b"))

    assert task.id
    assert task.type == "move"
    assert task.status == TaskStatus.queued


def test_rejects_move_directory_into_itself(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    source = tmp_path / "source"
    source.mkdir()
    manager = FileTaskManager()

    with pytest.raises(HTTPException):
        manager.create_transfer("alice", "move", [str(source)], str(source))


def test_rejects_move_directory_into_child(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    source = tmp_path / "source"
    child = source / "child"
    child.mkdir(parents=True)
    manager = FileTaskManager()

    with pytest.raises(HTTPException):
        manager.create_transfer("alice", "move", [str(source)], str(child))


def test_persists_transfer_history(monkeypatch, tmp_path: Path):
    cfg = SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path)), file_tasks=SimpleNamespace(max_parallel=2, max_parallel_per_user=1, log_tail_lines=80))
    monkeypatch.setattr(file_task_manager, "get_config", lambda: cfg)
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager()
    task = manager.create_transfer("alice", "copy", [str(tmp_path / "a")], str(tmp_path / "b"), priority=4)
    task.status = TaskStatus.completed
    manager._persist(task)

    loaded = FileTaskManager()

    assert loaded.get("alice", task.id) is not None
    assert loaded.get("alice", task.id).priority == 4


def test_retry_creates_new_queued_task(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager()
    task = manager.create_transfer("alice", "copy", [str(tmp_path / "a")], str(tmp_path / "b"))
    task.status = TaskStatus.failed

    retry = manager.retry("alice", task.id)

    assert retry is not None
    assert retry.id != task.id
    assert retry.status == TaskStatus.queued
    assert retry.retry_count == 1


def test_cancel_queued_task(tmp_path: Path):
    manager = FileTaskManager()
    task = FileTask(id="task1", username="alice", type="copy", source_paths=[str(tmp_path / "a")], destination_path=str(tmp_path / "b"))
    manager._tasks[task.id] = task

    assert manager.cancel("alice", task.id) is True
    assert task.status == TaskStatus.cancelled


def test_completed_status_after_success(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    task = FileTask(id="task1", username="alice", type="copy", source_paths=[str(source)], destination_path=str(dest))
    manager = FileTaskManager()

    class FakeProcess:
        stdout = iter(["hello\n", "          5 100%    1.00kB/s    0:00:00\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(file_task_manager, "build_rsync_command", lambda sources, destination: ["rsync"])
    monkeypatch.setattr(file_task_manager, "start_rsync", lambda username, cmd: FakeProcess())

    manager._run_rsync(task)

    assert task.status == TaskStatus.completed
    assert task.progress_percent == 100


def test_failed_status_after_rsync_error(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    task = FileTask(id="task1", username="alice", type="copy", source_paths=[str(source)], destination_path=str(dest))
    manager = FileTaskManager()

    class FakeProcess:
        stdout = iter(["Permission denied\n"])

        def wait(self):
            return 23

    monkeypatch.setattr(file_task_manager, "build_rsync_command", lambda sources, destination: ["rsync"])
    monkeypatch.setattr(file_task_manager, "start_rsync", lambda username, cmd: FakeProcess())

    manager._run_rsync(task)

    assert task.status == TaskStatus.failed
    assert "permission denied" in task.error_message.lower()


def test_move_does_not_remove_source_on_failure(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    task = FileTask(id="task1", username="alice", type="move", source_paths=[str(source)], destination_path=str(tmp_path / "dest"))
    manager = FileTaskManager()
    removed = []

    class FakeProcess:
        stdout = iter(["error\n"])

        def wait(self):
            return 11

    monkeypatch.setattr(file_task_manager, "build_rsync_command", lambda sources, destination: ["rsync"])
    monkeypatch.setattr(file_task_manager, "start_rsync", lambda username, cmd: FakeProcess())
    monkeypatch.setattr(file_task_manager, "remove_sources_after_move", lambda username, sources, on_error: removed.extend(sources))

    manager._run_rsync(task)

    assert task.status == TaskStatus.failed
    assert removed == []
    assert source.exists()


def test_move_removes_source_after_success(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    task = FileTask(id="task1", username="alice", type="move", source_paths=[str(source)], destination_path=str(tmp_path / "dest"))
    manager = FileTaskManager()
    removed = []

    class FakeProcess:
        stdout = iter(["          5 100%    1.00kB/s    0:00:00\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(file_task_manager, "build_rsync_command", lambda sources, destination: ["rsync"])
    monkeypatch.setattr(file_task_manager, "start_rsync", lambda username, cmd: FakeProcess())
    monkeypatch.setattr(file_task_manager, "remove_sources_after_move", lambda username, sources, on_error: removed.extend(sources))

    manager._run_rsync(task)

    assert task.status == TaskStatus.completed
    assert removed == [source]
