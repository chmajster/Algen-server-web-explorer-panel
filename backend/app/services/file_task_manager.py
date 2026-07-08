from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from ..config import get_config
from ..file_ops import run_user_op
from .rsync_tasks import (
    build_rsync_command,
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
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class FileTask:
    id: str
    username: str
    type: str
    source_paths: list[str]
    destination_path: str
    status: TaskStatus = TaskStatus.queued
    started_at: float | None = None
    finished_at: float | None = None
    bytes_transferred: int = 0
    total_bytes: int = 0
    progress_percent: int = 0
    speed_bps: float = 0
    speed_human: str = "0 B/s"
    eta_seconds: int | None = None
    eta_human: str = ""
    current_file: str = ""
    files_done: int = 0
    files_total: int = 0
    rsync_exit_code: int | None = None
    error_message: str = ""
    log_tail: list[str] = field(default_factory=list)
    result: object | None = None
    cancel_requested: bool = False
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
        self.log_tail.append(line[-1000:])
        limit = get_config().file_tasks.log_tail_lines
        if len(self.log_tail) > limit:
            self.log_tail = self.log_tail[-limit:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "op": self.type,
            "status": self.status.value,
            "source_paths": self.source_paths,
            "destination_path": self.destination_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "bytes_transferred": self.bytes_transferred,
            "total_bytes": self.total_bytes,
            "progress_percent": self.progress_percent,
            "progress": self.progress_percent,
            "speed_bps": self.speed_bps,
            "speed_human": self.speed_human,
            "eta_seconds": self.eta_seconds,
            "eta_human": self.eta_human,
            "current_file": self.current_file,
            "files_done": self.files_done,
            "files_total": self.files_total,
            "rsync_exit_code": self.rsync_exit_code,
            "error_message": self.error_message,
            "errors": self.errors,
            "log_tail": self.log_tail,
            "result": self.result,
            "cancel_requested": self.cancel_requested,
        }


class FileTaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, FileTask] = {}
        self._queue: deque[FileTask] = deque()
        self._running = 0
        self._lock = threading.RLock()

    def create(self, username: str, op: str, payload: dict) -> FileTask:
        if op in {"copy", "move"}:
            sources = payload.get("srcs") or payload.get("source_paths") or [payload["src"]]
            destination = payload.get("dst") or payload.get("destination_path")
            return self.create_transfer(username, op, [str(source) for source in sources], str(destination))
        task = FileTask(id=uuid4().hex, username=username, type=op, source_paths=[payload.get("path", "")], destination_path="")
        with self._lock:
            self._tasks[task.id] = task
            self._queue.append(task)
        self._schedule()
        return task

    def create_transfer(self, username: str, transfer_type: str, source_paths: list[str], destination_path: str) -> FileTask:
        if transfer_type not in {"copy", "move"}:
            raise HTTPException(400, "Unsupported transfer type")
        if not source_paths:
            raise HTTPException(400, "At least one source path is required")
        task = FileTask(
            id=uuid4().hex,
            username=username,
            type=transfer_type,
            source_paths=source_paths,
            destination_path=destination_path,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._queue.append(task)
        self._schedule()
        return task

    def _schedule(self) -> None:
        with self._lock:
            while self._queue and self._running < get_config().file_tasks.max_parallel:
                task = self._queue.popleft()
                if task.cancel_requested:
                    task.status = TaskStatus.cancelled
                    task.finished_at = now()
                    continue
                self._running += 1
                threading.Thread(target=self._run, args=(task,), daemon=True).start()

    def _run(self, task: FileTask) -> None:
        try:
            task.status = TaskStatus.running
            task.started_at = now()
            if task.type in {"copy", "move"}:
                self._run_rsync(task)
            else:
                task.result = run_user_op(task.username, task.type, {"path": task.source_paths[0]})
                task.progress_percent = 100
                task.status = TaskStatus.completed
        except Exception as exc:  # noqa: BLE001
            if task.status != TaskStatus.cancelled:
                task.status = TaskStatus.failed
                task.error_message = str(exc)
                task.append_log(str(exc))
        finally:
            task.finished_at = now()
            with self._lock:
                self._running = max(0, self._running - 1)
            self._schedule()

    def _run_rsync(self, task: FileTask) -> None:
        sources = [Path(source) for source in task.source_paths]
        destination = Path(task.destination_path)
        task.total_bytes, task.files_total = count_sources(sources, task.append_log)
        task.speed_human = human_bytes(0) + "/s"
        cmd = build_rsync_command(sources, destination)
        task.append_log(" ".join(json.dumps(part) for part in cmd))
        process = start_rsync(task.username, cmd)
        task.process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            if task.cancel_requested:
                terminate_process(process)
                task.status = TaskStatus.cancelled
                task.error_message = "Transfer cancelled by user"
                return
            for line in raw_line.replace("\r", "\n").splitlines():
                self._apply_rsync_line(task, line.strip())
        exit_code = process.wait()
        task.rsync_exit_code = exit_code
        if task.cancel_requested:
            task.status = TaskStatus.cancelled
            task.error_message = "Transfer cancelled by user"
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

    def list_for(self, username: str) -> list[FileTask]:
        with self._lock:
            return [task for task in self._tasks.values() if task.username == username]

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
        if task.status == TaskStatus.queued:
            task.status = TaskStatus.cancelled
            task.finished_at = now()
            return True
        if task.status == TaskStatus.running and task.process is not None:
            terminate_process(task.process)
            task.status = TaskStatus.cancelled
            task.finished_at = now()
            task.error_message = "Transfer cancelled by user"
        return True


task_store = FileTaskManager()
