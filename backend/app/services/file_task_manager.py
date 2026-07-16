from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..config import get_config
from ..file_ops import run_user_op
from ..proxmox_guard import assert_path_allowed
from .rsync_tasks import (
    build_rsync_command,
    cleanup_partial_files,
    count_sources,
    human_bytes,
    now,
    parse_progress_line,
    remove_sources_after_move,
    start_rsync,
    terminate_process,
)


class TaskStatus(StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES = {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}


@dataclass
class FileTask:
    id: str
    username: str
    type: str
    source_paths: list[str]
    destination_path: str
    status: TaskStatus = TaskStatus.queued
    priority: int = 0
    created_at: float = field(default_factory=now)
    started_at: float | None = None
    finished_at: float | None = None
    paused_at: float | None = None
    bytes_transferred: int = 0
    total_bytes: int = 0
    progress_percent: int = 0
    speed_bps: float = 0
    speed_human: str = "0 B/s"
    average_speed_bps: float = 0
    average_speed_human: str = "0 B/s"
    eta_seconds: int | None = None
    eta_human: str = ""
    current_file: str = ""
    files_done: int = 0
    files_total: int = 0
    rsync_exit_code: int | None = None
    error_message: str = ""
    log_tail: list[str] = field(default_factory=list)
    stderr_tail: list[str] = field(default_factory=list)
    command_preview: list[str] = field(default_factory=list)
    retry_count: int = 0
    result: object | None = None
    cancel_requested: bool = False
    pause_requested: bool = False
    process: Any | None = field(default=None, repr=False)

    @property
    def op(self) -> str:
        return self.type

    @property
    def progress(self) -> int:
        return self.progress_percent

    @property
    def errors(self) -> list[str]:
        return [self.error_message] if self.error_message else []

    def append_log(self, line: str) -> None:
        if not line:
            return
        clipped = line[-1000:]
        self.log_tail.append(clipped)
        if any(token in line.lower() for token in ("error", "failed", "denied", "no such", "rsync:")):
            self.stderr_tail.append(clipped)
        limit = get_config().file_tasks.log_tail_lines
        self.log_tail = self.log_tail[-limit:]
        self.stderr_tail = self.stderr_tail[-limit:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "type": self.type,
            "op": self.type,
            "status": self.status.value,
            "priority": self.priority,
            "created_at": self.created_at,
            "source_paths": self.source_paths,
            "destination_path": self.destination_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "paused_at": self.paused_at,
            "bytes_transferred": self.bytes_transferred,
            "total_bytes": self.total_bytes,
            "progress_percent": self.progress_percent,
            "progress": self.progress_percent,
            "speed_bps": self.speed_bps,
            "speed_human": self.speed_human,
            "average_speed_bps": self.average_speed_bps,
            "average_speed_human": self.average_speed_human,
            "eta_seconds": self.eta_seconds,
            "eta_human": self.eta_human,
            "current_file": self.current_file,
            "files_done": self.files_done,
            "files_total": self.files_total,
            "rsync_exit_code": self.rsync_exit_code,
            "error_message": self.error_message,
            "errors": self.errors,
            "log_tail": self.log_tail,
            "stderr_tail": self.stderr_tail,
            "command_preview": self.command_preview,
            "retry_count": self.retry_count,
            "result": self.result,
            "cancel_requested": self.cancel_requested,
        }


class FileTaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, FileTask] = {}
        self._lock = threading.RLock()
        self._db_path = Path(get_config().paths.data_dir) / "transfers.sqlite3"
        self._init_db()
        self._load_tasks()
        self._schedule()

    def _connect(self) -> sqlite3.Connection:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._db_path = Path(tempfile.gettempdir()) / "webnas" / "transfers.sqlite3"
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_tasks (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source_paths TEXT NOT NULL,
                    destination_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL
                )
                """
            )

    def _load_tasks(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload,username,type,source_paths,destination_path,status,priority FROM file_tasks").fetchall()
        with self._lock:
            for row in rows:
                payload = json.loads(row["payload"])
                # Older WebNAS versions omitted these required fields from the
                # JSON payload. The normalized table columns are the migration
                # source of truth and let upgrades start without losing history.
                payload.setdefault("username", row["username"])
                payload.setdefault("type", row["type"])
                payload.setdefault("source_paths", json.loads(row["source_paths"]))
                payload.setdefault("destination_path", row["destination_path"])
                payload.setdefault("status", row["status"])
                payload.setdefault("priority", row["priority"])
                task = self._task_from_payload(payload)
                if task.status == TaskStatus.running:
                    task.status = TaskStatus.queued
                    task.started_at = None
                    task.finished_at = None
                    task.error_message = ""
                    task.cancel_requested = False
                    task.pause_requested = False
                    task.append_log("Task was interrupted by service restart and queued again")
                self._tasks[task.id] = task
            self._persist_all()

    def _task_from_payload(self, payload: dict) -> FileTask:
        payload = dict(payload)
        allowed = {item.name for item in fields(FileTask)}
        payload = {key: value for key, value in payload.items() if key in allowed and key != "process"}
        payload["status"] = TaskStatus(payload.get("status", "queued"))
        return FileTask(**payload)

    def _persist(self, task: FileTask) -> None:
        payload = task.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO file_tasks (id, username, type, source_paths, destination_path, status, priority, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username=excluded.username,
                    type=excluded.type,
                    source_paths=excluded.source_paths,
                    destination_path=excluded.destination_path,
                    status=excluded.status,
                    priority=excluded.priority,
                    payload=excluded.payload
                """,
                (
                    task.id,
                    task.username,
                    task.type,
                    json.dumps(task.source_paths),
                    task.destination_path,
                    task.status.value,
                    task.priority,
                    json.dumps(payload),
                ),
            )

    def _persist_all(self) -> None:
        for task in self._tasks.values():
            self._persist(task)

    def create(self, username: str, op: str, payload: dict) -> FileTask:
        if op in {"copy", "move"}:
            sources = payload.get("srcs") or payload.get("source_paths") or [payload["src"]]
            destination = payload.get("dst") or payload.get("destination_path")
            return self.create_transfer(username, op, [str(source) for source in sources], str(destination), int(payload.get("priority", 0)))
        task = FileTask(id=uuid4().hex, username=username, type=op, source_paths=[payload.get("path", "")], destination_path="")
        with self._lock:
            self._tasks[task.id] = task
            self._persist(task)
        self._schedule()
        return task

    def create_transfer(self, username: str, transfer_type: str, source_paths: list[str], destination_path: str, priority: int = 0) -> FileTask:
        if transfer_type not in {"copy", "move"}:
            raise HTTPException(400, "Unsupported transfer type")
        if not source_paths:
            raise HTTPException(400, "At least one source path is required")
        for source in source_paths:
            assert_path_allowed(source, transfer_type, include_parent=True)
        assert_path_allowed(destination_path, transfer_type, include_parent=True)
        if transfer_type == "move":
            self._reject_self_or_child_move([Path(source).resolve(strict=False) for source in source_paths], Path(destination_path).resolve(strict=False))
        task = FileTask(
            id=uuid4().hex,
            username=username,
            type=transfer_type,
            source_paths=source_paths,
            destination_path=destination_path,
            priority=priority,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._persist(task)
        self._schedule()
        return task

    def _reject_self_or_child_move(self, sources: list[Path], destination: Path) -> None:
        for source in sources:
            target = destination / source.name if destination.exists() and destination.is_dir() else destination
            if target == source:
                raise HTTPException(400, "Cannot move a directory into itself")
            try:
                target.relative_to(source)
                raise HTTPException(400, "Cannot move a directory into its own subdirectory")
            except ValueError:
                pass

    def _running_counts(self) -> tuple[int, dict[str, int]]:
        running = [task for task in self._tasks.values() if task.status == TaskStatus.running]
        per_user: dict[str, int] = {}
        for task in running:
            per_user[task.username] = per_user.get(task.username, 0) + 1
        return len(running), per_user

    def _schedule(self) -> None:
        with self._lock:
            cfg = get_config().file_tasks
            total_running, per_user = self._running_counts()
            candidates = sorted(
                [task for task in self._tasks.values() if task.status == TaskStatus.queued],
                key=lambda task: (-task.priority, task.created_at),
            )
            for task in candidates:
                if total_running >= cfg.max_parallel:
                    break
                if per_user.get(task.username, 0) >= cfg.max_parallel_per_user:
                    continue
                total_running += 1
                per_user[task.username] = per_user.get(task.username, 0) + 1
                task.status = TaskStatus.running
                self._persist(task)
                threading.Thread(target=self._run, args=(task,), daemon=True).start()

    def _run(self, task: FileTask) -> None:
        try:
            task.status = TaskStatus.running
            task.started_at = task.started_at or now()
            task.finished_at = None
            task.paused_at = None
            task.cancel_requested = False
            task.pause_requested = False
            self._persist(task)
            if task.type in {"copy", "move"}:
                self._run_rsync(task)
            else:
                task.result = run_user_op(task.username, task.type, {"path": task.source_paths[0]})
                task.progress_percent = 100
                task.status = TaskStatus.completed
        except Exception as exc:  # noqa: BLE001
            if task.status not in {TaskStatus.cancelled, TaskStatus.paused}:
                task.status = TaskStatus.failed
                task.error_message = str(exc)
                task.append_log(str(exc))
        finally:
            if task.status in TERMINAL_STATUSES:
                task.finished_at = now()
            task.process = None
            self._update_average_speed(task)
            self._persist(task)
            if task.status in TERMINAL_STATUSES:
                activity_status = {
                    TaskStatus.completed: ActivityStatus.success,
                    TaskStatus.failed: ActivityStatus.failure,
                    TaskStatus.cancelled: ActivityStatus.cancelled,
                }[task.status]
                record_activity(
                    ActivityCategory.file,
                    task.type,
                    task.username,
                    target=task.destination_path or (task.source_paths[0] if task.source_paths else ""),
                    status=activity_status,
                    summary=task.error_message,
                    details={"task_id": task.id, "items": len(task.source_paths), "bytes": task.bytes_transferred},
                    source="file-tasks",
                )
            self._schedule()

    def _run_rsync(self, task: FileTask) -> None:
        sources = [Path(source) for source in task.source_paths]
        destination = Path(task.destination_path)
        task.total_bytes, task.files_total = count_sources(sources, task.append_log)
        task.speed_human = human_bytes(0) + "/s"
        cmd = build_rsync_command(sources, destination)
        task.command_preview = cmd
        task.append_log(" ".join(json.dumps(part) for part in cmd))
        self._persist(task)
        process = start_rsync(task.username, cmd)
        task.process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            if task.cancel_requested or task.pause_requested:
                terminate_process(process)
                if task.cancel_requested:
                    cleanup_partial_files(task.username, destination, task.append_log)
                    task.status = TaskStatus.cancelled
                    task.error_message = "Transfer cancelled by user"
                else:
                    task.status = TaskStatus.paused
                    task.paused_at = now()
                    task.error_message = "Transfer paused"
                return
            for line in raw_line.replace("\r", "\n").splitlines():
                self._apply_rsync_line(task, line.strip())
            self._update_average_speed(task)
            self._persist(task)
        exit_code = process.wait()
        task.rsync_exit_code = exit_code
        if task.cancel_requested:
            cleanup_partial_files(task.username, destination, task.append_log)
            task.status = TaskStatus.cancelled
            task.error_message = "Transfer cancelled by user"
            return
        if task.pause_requested:
            task.status = TaskStatus.paused
            task.paused_at = now()
            task.error_message = "Transfer paused"
            return
        if exit_code != 0:
            task.status = TaskStatus.failed
            task.error_message = self._rsync_error(exit_code, task.log_tail)
            return
        if task.type == "move":
            remove_sources_after_move(task.username, sources, task.append_log)
        task.bytes_transferred = max(task.bytes_transferred, task.total_bytes)
        task.progress_percent = 100
        task.files_done = task.files_total
        task.status = TaskStatus.completed
        task.result = {"ok": True}

    def _update_average_speed(self, task: FileTask) -> None:
        if not task.started_at:
            return
        elapsed = max(0.001, (task.finished_at or now()) - task.started_at)
        task.average_speed_bps = task.bytes_transferred / elapsed
        task.average_speed_human = human_bytes(task.average_speed_bps) + "/s"

    def _apply_rsync_line(self, task: FileTask, line: str) -> None:
        if not line:
            return
        task.append_log(line)
        parsed = parse_progress_line(line)
        if parsed:
            task.bytes_transferred = int(parsed["bytes_transferred"])
            task.progress_percent = int(parsed["progress_percent"])
            task.speed_bps = float(parsed["speed_bps"])
            task.speed_human = str(parsed["speed_human"])
            task.eta_seconds = parsed["eta_seconds"]
            task.eta_human = str(parsed["eta_human"])
            return
        if not line.startswith(("Number of ", "Total ", "sent ", "received ")):
            task.current_file = line
            task.files_done = min(task.files_total, task.files_done + 1) if task.files_total else task.files_done

    def _rsync_error(self, exit_code: int, log_tail: list[str]) -> str:
        joined = "\n".join(log_tail[-8:]).lower()
        if "no space left" in joined:
            return "Transfer failed: no space left on device"
        if "permission denied" in joined:
            return "Transfer failed: permission denied"
        if "no such file" in joined:
            return "Transfer failed: source file or directory does not exist"
        return f"rsync failed with exit code {exit_code}"

    def list_for(self, username: str, status_filter: str | None = None) -> list[FileTask]:
        with self._lock:
            tasks = [task for task in self._tasks.values() if task.username == username]
        return self._filter_and_sort(tasks, status_filter)

    def list_all(self, status_filter: str | None = None) -> list[FileTask]:
        """Return all users' transfers after the API has authorized global access."""
        with self._lock:
            tasks = list(self._tasks.values())
        return self._filter_and_sort(tasks, status_filter)

    @staticmethod
    def _filter_and_sort(tasks: list[FileTask], status_filter: str | None) -> list[FileTask]:
        if status_filter == "active":
            tasks = [task for task in tasks if task.status in {TaskStatus.queued, TaskStatus.running, TaskStatus.paused}]
        elif status_filter == "finished":
            tasks = [task for task in tasks if task.status == TaskStatus.completed]
        elif status_filter == "failed":
            tasks = [task for task in tasks if task.status == TaskStatus.failed]
        elif status_filter == "cancelled":
            tasks = [task for task in tasks if task.status == TaskStatus.cancelled]
        return sorted(tasks, key=lambda task: (task.status not in {TaskStatus.running, TaskStatus.queued}, -task.created_at))

    def get(self, username: str, task_id: str) -> FileTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.username != username:
                return None
            return task

    def cancel(self, username: str, task_id: str) -> bool:
        task = self.get(username, task_id)
        if not task:
            return False
        task.cancel_requested = True
        if task.status in {TaskStatus.queued, TaskStatus.paused, TaskStatus.failed}:
            if task.type in {"copy", "move"}:
                cleanup_partial_files(task.username, Path(task.destination_path), task.append_log)
            task.status = TaskStatus.cancelled
            task.finished_at = now()
            task.error_message = "Transfer cancelled by user"
            self._persist(task)
            self._schedule()
            return True
        if task.status == TaskStatus.running and task.process is not None:
            terminate_process(task.process)
        self._persist(task)
        return True

    def pause(self, username: str, task_id: str) -> bool:
        task = self.get(username, task_id)
        if not task:
            return False
        if task.status == TaskStatus.queued:
            task.status = TaskStatus.paused
            task.paused_at = now()
            task.error_message = "Transfer paused"
            self._persist(task)
            return True
        if task.status == TaskStatus.running:
            task.pause_requested = True
            if task.process is not None:
                terminate_process(task.process)
            self._persist(task)
            return True
        return False

    def resume(self, username: str, task_id: str) -> bool:
        task = self.get(username, task_id)
        if not task:
            return False
        if task.status not in {TaskStatus.paused, TaskStatus.failed}:
            return False
        task.status = TaskStatus.queued
        task.error_message = ""
        task.pause_requested = False
        task.cancel_requested = False
        task.finished_at = None
        self._persist(task)
        self._schedule()
        return True

    def retry(self, username: str, task_id: str) -> FileTask | None:
        task = self.get(username, task_id)
        if not task:
            return None
        if task.status not in {TaskStatus.failed, TaskStatus.cancelled}:
            raise HTTPException(400, "Only failed or cancelled transfers can be retried")
        retry = FileTask(
            id=uuid4().hex,
            username=task.username,
            type=task.type,
            source_paths=list(task.source_paths),
            destination_path=task.destination_path,
            priority=task.priority,
            retry_count=task.retry_count + 1,
        )
        with self._lock:
            self._tasks[retry.id] = retry
            self._persist(retry)
        self._schedule()
        return retry

    def set_priority(self, username: str, task_id: str, priority: int) -> bool:
        task = self.get(username, task_id)
        if not task:
            return False
        task.priority = priority
        self._persist(task)
        self._schedule()
        return True


task_store = FileTaskManager()
