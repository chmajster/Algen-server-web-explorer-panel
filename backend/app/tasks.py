from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from .file_ops import run_user_op


class TaskStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class Task:
    id: str
    username: str
    op: str
    payload: dict
    status: TaskStatus = TaskStatus.queued
    progress: int = 0
    result: object | None = None
    errors: list[str] = field(default_factory=list)
    cancel_requested: bool = False


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(self, username: str, op: str, payload: dict) -> Task:
        task = Task(id=uuid4().hex, username=username, op=op, payload=payload)
        with self._lock:
            self._tasks[task.id] = task
        thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        thread.start()
        return task

    def _run(self, task: Task) -> None:
        task.status = TaskStatus.running
        try:
            if task.cancel_requested:
                task.status = TaskStatus.cancelled
                return
            task.result = run_user_op(task.username, task.op, task.payload)
            task.progress = 100
            task.status = TaskStatus.completed
        except Exception as exc:  # noqa: BLE001
            task.status = TaskStatus.failed
            task.errors.append(str(exc))

    def list_for(self, username: str) -> list[Task]:
        return [task for task in self._tasks.values() if task.username == username]

    def get(self, username: str, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if not task or task.username != username:
            return None
        return task

    def cancel(self, username: str, task_id: str) -> bool:
        task = self.get(username, task_id)
        if not task:
            return False
        task.cancel_requested = True
        if task.status in {TaskStatus.queued, TaskStatus.running}:
            task.status = TaskStatus.cancelled
        return True


task_store = TaskStore()
