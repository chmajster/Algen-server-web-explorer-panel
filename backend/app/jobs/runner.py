from __future__ import annotations

import itertools
import os
import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from .models import JobPriority

_PRIORITY = {
    JobPriority.critical: 0,
    JobPriority.high: 10,
    JobPriority.normal: 20,
    JobPriority.low: 30,
}


class JobRunner:
    """Small in-process priority executor used by all WebNAS module jobs."""

    def __init__(self, max_workers: int | None = None) -> None:
        configured = max_workers if max_workers is not None else int(os.environ.get("WEBNAS_JOB_WORKERS", "4"))
        self.max_workers = min(max(configured, 1), 16)
        self._queue: queue.PriorityQueue[tuple[int, int, str, Callable[[], None], Future[None]]] = queue.PriorityQueue()
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count()
        self._shutdown = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="webnas-job")
        self._worker_futures = [self._executor.submit(self._worker) for _ in range(self.max_workers)]

    def submit(self, job_id: str, target: Callable[[], None], priority: JobPriority = JobPriority.normal) -> Future[None]:
        future: Future[None] = Future()
        with self._lock:
            self._futures[job_id] = future
        self._queue.put((_PRIORITY[priority], next(self._counter), job_id, target, future))
        return future

    def cancel_queued(self, job_id: str) -> bool:
        with self._lock:
            future = self._futures.get(job_id)
        return bool(future and future.cancel())

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                _priority, _sequence, job_id, target, future = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        target()
                    except BaseException as error:  # noqa: BLE001
                        future.set_exception(error)
                    else:
                        future.set_result(None)
            finally:
                with self._lock:
                    self._futures.pop(job_id, None)
                self._queue.task_done()

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._lock:
            futures = list(self._futures.values())
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
