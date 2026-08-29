from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .config import get_config
from .security import SessionUser, get_session_user


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    revision: int
    type: str
    data: dict[str, Any]


class RuntimeEventBroker:
    """Small process-local pub/sub used to fan out lightweight invalidation events."""

    def __init__(self, *, queue_size: int = 128) -> None:
        self._queue_size = max(8, queue_size)
        self._revision = 0
        self._lock = threading.RLock()
        self._subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue[RuntimeEvent]]] = {}

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def subscribe(self) -> asyncio.Queue[RuntimeEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers[id(queue)] = (loop, queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RuntimeEvent]) -> None:
        with self._lock:
            self._subscribers.pop(id(queue), None)

    @staticmethod
    def _offer(queue: asyncio.Queue[RuntimeEvent], event: RuntimeEvent) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> int:
        with self._lock:
            self._revision += 1
            event = RuntimeEvent(self._revision, event_type, data or {})
            subscribers = tuple(self._subscribers.values())
        for loop, queue in subscribers:
            if loop.is_closed():
                continue
            loop.call_soon_threadsafe(self._offer, queue, event)
        return event.revision


runtime_events = RuntimeEventBroker()
router = APIRouter(prefix="/api/events", tags=["runtime-events"])


def publish_runtime_event(event_type: str, data: dict[str, Any] | None = None) -> int:
    return runtime_events.publish(event_type, data)


@router.get("")
async def stream_runtime_events(_user: SessionUser = Depends(get_session_user)) -> StreamingResponse:
    queue = runtime_events.subscribe()

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                payload = json.dumps(
                    {"type": event.type, "revision": event.revision, "data": event.data},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"id: {event.revision}\ndata: {payload}\n\n"
        finally:
            runtime_events.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _fingerprint(paths: tuple[Path, ...]) -> tuple[tuple[int, int] | None, ...]:
    values: list[tuple[int, int] | None] = []
    for path in paths:
        try:
            file_stat = path.stat()
            values.append((file_stat.st_mtime_ns, file_stat.st_size))
        except OSError:
            values.append(None)
    return tuple(values)


def _tree_fingerprint(path: Path) -> tuple[int, int, int]:
    """Return a cheap recursive fingerprint that notices updates to existing transaction files."""

    latest_mtime = 0
    total_size = 0
    entries = 0
    try:
        candidates = (path, *path.rglob("*"))
    except OSError:
        return (0, 0, 0)
    for candidate in candidates:
        try:
            file_stat = candidate.stat()
        except OSError:
            continue
        entries += 1
        latest_mtime = max(latest_mtime, file_stat.st_mtime_ns)
        if candidate.is_file():
            total_size += file_stat.st_size
    return (latest_mtime, total_size, entries)


async def watch_update_progress() -> None:
    """Translate mutable runtime files into one shared browser invalidation stream."""

    data_dir = Path(get_config().paths.data_dir)
    watched: dict[str, tuple[Path, ...]] = {
        "update.progress": (data_dir / "settings" / "update_progress.json",),
        "task.updated": (data_dir / "transfers.sqlite3", data_dir / "transfers.sqlite3-wal"),
        "job.updated": (data_dir / "jobs.sqlite3", data_dir / "jobs.sqlite3-wal"),
        "module.updated": (data_dir / "package-center.sqlite3", data_dir / "package-center.sqlite3-wal"),
        "mount.updated": (
            data_dir / "mounts" / "network_mounts.sqlite3",
            data_dir / "mounts" / "network_mounts.sqlite3-wal",
        ),
    }
    network_transactions = data_dir / "network-management" / "transactions"
    previous = {event_type: _fingerprint(paths) for event_type, paths in watched.items()}
    previous_network_transactions = _tree_fingerprint(network_transactions)
    while True:
        for event_type, paths in watched.items():
            current = _fingerprint(paths)
            if current != previous[event_type]:
                previous[event_type] = current
                publish_runtime_event(event_type)
        current_network_transactions = _tree_fingerprint(network_transactions)
        if current_network_transactions != previous_network_transactions:
            previous_network_transactions = current_network_transactions
            publish_runtime_event("network.transaction.updated")
        await asyncio.sleep(0.5)
