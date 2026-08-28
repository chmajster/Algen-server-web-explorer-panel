from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable


class JobRunner:
    def __init__(self, max_workers: int | None = None) -> None:
        configured = max_workers if max_workers is not None else int(os.environ.get("WEBNAS_JOB_WORKERS", "4"))
        self.max_workers = min(max(configured, 1), 16)
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="webnas-job")
        self._futures: dict[str, Future[None]] = {}
        self._lock = Lock()

    def submit(self, job_id: str, target: Callable[[], None]) -> Future[None]:
        future = self._executor.submit(target)
        with self._lock:
            self._futures[job_id] = future
        future.add_done_callback(lambda _future: self._forget(job_id))
        return future

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
