from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import file_task_manager, rsync_tasks
from app.services.file_task_manager import FileTask, FileTaskManager, TaskStatus


@pytest.fixture(autouse=True)
def isolated_transfer_database(monkeypatch, tmp_path: Path):
    """Prevent persisted queued tasks from another test starting in new managers."""
    original = file_task_manager.get_config()
    isolated = original.model_copy(deep=True)
    isolated.paths.data_dir = str(tmp_path / "state")
    monkeypatch.setattr(file_task_manager, "get_config", lambda: isolated)


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


def test_global_transfer_listing_includes_multiple_users(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager()
    alice = manager.create_transfer("alice", "copy", [str(tmp_path / "alice")], str(tmp_path / "target-a"))
    bob = manager.create_transfer("bob", "copy", [str(tmp_path / "bob")], str(tmp_path / "target-b"))

    assert {task.id for task in manager.list_all()} == {alice.id, bob.id}
    assert [task.id for task in manager.list_for("alice")] == [alice.id]


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


def test_running_task_is_failed_after_restart(monkeypatch, tmp_path: Path):
    cfg = SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path)), file_tasks=SimpleNamespace(max_parallel=2, max_parallel_per_user=1, log_tail_lines=80))
    monkeypatch.setattr(file_task_manager, "get_config", lambda: cfg)
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager()
    task = manager.create_transfer("alice", "copy", [str(tmp_path / "a")], str(tmp_path / "b"), priority=4)
    task.status = TaskStatus.running
    task.started_at = 123.0
    manager._persist(task)

    loaded = FileTaskManager()
    restored = loaded.get("alice", task.id)

    assert restored is not None
    assert restored.status == TaskStatus.failed
    assert restored.started_at == 123.0
    assert restored.finished_at is not None
    assert "restarted" in restored.error_message.lower()
    assert "explicit retry" in "\n".join(restored.log_tail).lower()


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


class RecordingJobService:
    def __init__(self) -> None:
        self.submissions = []
        self.jobs = {}

    def submit_callable(self, **kwargs):
        job = SimpleNamespace(id=f"job-{len(self.submissions) + 1}", status=SimpleNamespace(value="queued"))
        self.submissions.append(kwargs)
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is not None:
            job.status = SimpleNamespace(value="cancelled")
        return job


def test_scheduler_submits_transfer_through_global_job_service(monkeypatch, tmp_path: Path):
    operations = RecordingJobService()
    original_schedule = FileTaskManager._schedule
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    manager = FileTaskManager(operations=operations)
    task = manager.create_transfer("alice", "copy", [str(tmp_path / "a")], str(tmp_path / "b"), priority=5)
    monkeypatch.setattr(FileTaskManager, "_schedule", original_schedule)

    manager._schedule()

    assert task.status == TaskStatus.running
    assert len(operations.submissions) == 1
    submission = operations.submissions[0]
    assert submission["job_type"] == "file.copy"
    assert submission["module"] == "files"
    assert submission["created_by"] == "alice"
    assert submission["metadata"] == {"file_task_id": task.id, "operation": "copy", "items": 1}
    assert submission["cancellable"] is True
    assert submission["retryable"] is False


def test_two_managers_claim_same_persisted_transfer_only_once(monkeypatch, tmp_path: Path):
    first_operations = RecordingJobService()
    second_operations = RecordingJobService()
    original_schedule = FileTaskManager._schedule
    monkeypatch.setattr(FileTaskManager, "_schedule", lambda self: None)
    first = FileTaskManager(operations=first_operations)
    task = first.create_transfer("alice", "move", [str(tmp_path / "a")], str(tmp_path / "b"))
    second = FileTaskManager(operations=second_operations)
    monkeypatch.setattr(FileTaskManager, "_schedule", original_schedule)

    first._schedule()
    second._schedule()

    assert task.status == TaskStatus.running
    assert len(first_operations.submissions) + len(second_operations.submissions) == 1
