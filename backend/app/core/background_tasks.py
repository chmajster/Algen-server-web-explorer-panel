from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Own asyncio tasks created by the application composition root.

    Tasks are tracked until completion and are cancelled and awaited during
    shutdown so the process cannot leave orphaned pending coroutines behind.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def create(self, coroutine: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "background_task_failed task=%s",
                task.get_name(),
                exc_info=(type(error), error, error.__traceback__),
            )

    async def cancel_all(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def active_count(self) -> int:
        return sum(not task.done() for task in self._tasks)
