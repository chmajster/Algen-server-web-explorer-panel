from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from .config import get_config

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux production uses fcntl.
    fcntl = None  # type: ignore[assignment]


ACTIVE_OPERATION_STATUSES = {"queued", "running"}
BLOCKING_UPDATE_STATES = {"waiting", "preparing", "running"}
UPDATE_BLOCKED_MESSAGE = "Trwa aktualizacja systemu. Nowe operacje są tymczasowo zablokowane."

OperationProvider = Callable[[], Iterable[Mapping[str, Any]]]
ResumeCallback = Callable[[], None]

_process_lock = threading.RLock()
_local = threading.local()
_registry_lock = threading.RLock()
_providers: dict[str, tuple[OperationProvider, ResumeCallback | None]] = {}
_transient_lock = threading.RLock()
_transient_operations: dict[str, dict[str, Any]] = {}

# This is the single canonical order used by the API, installer coordination,
# recovery code and frontend.  Labels live in the frontend locale files.
UPDATE_STEPS = (
    "prepare",
    "check_operations",
    "check_update",
    "download_repository",
    "download_version",
    "verify_files",
    "install_backend_dependencies",
    "install_frontend_dependencies",
    "build_frontend",
    "update_configuration",
    "switch_version",
    "restart_services",
    "health_check",
    "complete",
)
UPDATE_STEP_STATUSES = {"pending", "running", "success", "failed", "skipped"}


def _redact_update_text(value: str) -> str:
    text = re.sub(r"(?i)(authorization|cookie|set-cookie|token|password|secret|api[_-]?key)(\s*[:=]\s*|\s+)\S+", r"\1\2***", value)
    return re.sub(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+@", r"\1***@", text)


def default_update_steps() -> list[dict[str, Any]]:
    return [
        {"id": step_id, "status": "pending", "message": "", "started_at": None, "finished_at": None, "error": None}
        for step_id in UPDATE_STEPS
    ]


def _normalize_steps(value: Any) -> list[dict[str, Any]]:
    supplied = {str(item.get("id")): item for item in value if isinstance(item, dict) and item.get("id")} if isinstance(value, list) else {}
    result = default_update_steps()
    for item in result:
        legacy = supplied.get(item["id"])
        if not legacy:
            continue
        status = str(legacy.get("status") or "pending")
        item.update(
            {
                "status": status if status in UPDATE_STEP_STATUSES else "pending",
                "message": _redact_update_text(str(legacy.get("message") or ""))[:1000],
                "started_at": legacy.get("started_at"),
                "finished_at": legacy.get("finished_at"),
                "error": _redact_update_text(str(legacy.get("error") or ""))[:4000] or None,
            }
        )
    return result


def _settings_directory() -> Path:
    directory = Path(get_config().paths.data_dir) / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def update_request_path() -> Path:
    return _settings_directory() / "update_request.json"


def _coordination_lock_path() -> Path:
    return _settings_directory() / "update-coordination.lock"


@contextmanager
def coordination_lock() -> Iterator[None]:
    """Serialize update transitions and task admission across workers/processes."""
    with _process_lock:
        depth = int(getattr(_local, "depth", 0))
        if depth:
            _local.depth = depth + 1
            try:
                yield
            finally:
                _local.depth -= 1
            return

        lock_path = _coordination_lock_path()
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        _local.depth = 1
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            _local.depth = 0
            os.close(descriptor)


def default_update_request() -> dict[str, Any]:
    return {
        "id": "",
        "state": "idle",
        "phase": "idle",
        "failed_phase": None,
        "actor": "",
        "requested_at": None,
        "started_at": None,
        "finished_at": None,
        "update_config": False,
        "previous_version": None,
        "target_version": None,
        "current_version": None,
        "commit_revision": None,
        "commit_date": None,
        "message": "",
        "progress": 0,
        "steps": default_update_steps(),
        "trigger": "manual",
        "updated_at": None,
        "acknowledged_users": [],
    }


def read_update_request() -> dict[str, Any]:
    path = update_request_path()
    if not path.exists():
        return default_update_request()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_update_request()
    if not isinstance(value, dict):
        return default_update_request()
    state = {**default_update_request(), **value}
    state["steps"] = _normalize_steps(value.get("steps"))
    return state


def write_update_request(value: Mapping[str, Any]) -> dict[str, Any]:
    state = {**default_update_request(), **dict(value)}
    state["steps"] = _normalize_steps(state.get("steps"))
    state["updated_at"] = time.time()
    path = update_request_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return state


def _transition_update_step(step_id: str, status: str, *, message: str | None = None, error: str | None = None) -> dict[str, Any]:
    if step_id not in UPDATE_STEPS:
        raise ValueError(f"Unknown update step: {step_id}")
    if status not in UPDATE_STEP_STATUSES:
        raise ValueError(f"Unknown update step status: {status}")
    with coordination_lock():
        state = read_update_request()
        now = time.time()
        steps = _normalize_steps(state.get("steps"))
        step = next(item for item in steps if item["id"] == step_id)
        if status == "running":
            step["started_at"] = step.get("started_at") or now
            step["finished_at"] = None
            step["error"] = None
            next_state = state.get("state") if state.get("state") == "waiting" and step_id in {"prepare", "check_operations"} else "running"
            state.update({"state": next_state, "phase": step_id, "failed_phase": None})
        elif status in {"success", "failed", "skipped"}:
            step["started_at"] = step.get("started_at") or now
            step["finished_at"] = now
            if status == "failed":
                step["error"] = _redact_update_text(error or message or "Update step failed")[:4000]
                state.update({"state": "failed", "phase": "failed", "failed_phase": step_id, "finished_at": now})
        step["status"] = status
        if message is not None:
            safe_message = _redact_update_text(message)[:1000]
            step["message"] = safe_message
            state["message"] = safe_message
        completed = sum(item["status"] in {"success", "skipped"} for item in steps)
        state["progress"] = round(completed * 100 / len(steps))
        state["steps"] = steps
        return write_update_request(state)


def start_update_step(step_id: str, message: str | None = None) -> dict[str, Any]:
    return _transition_update_step(step_id, "running", message=message)


def complete_update_step(step_id: str, message: str | None = None) -> dict[str, Any]:
    return _transition_update_step(step_id, "success", message=message)


def fail_update_step(step_id: str, error: str) -> dict[str, Any]:
    return _transition_update_step(step_id, "failed", message=error, error=error)


def skip_update_step(step_id: str, reason: str | None = None) -> dict[str, Any]:
    return _transition_update_step(step_id, "skipped", message=reason)


def skip_remaining_update_steps(*, reason: str, after: str | None = None) -> dict[str, Any]:
    with coordination_lock():
        state = read_update_request()
        started = after is None
        for step in state["steps"]:
            if step["id"] == after:
                started = True
                continue
            if started and step["status"] == "pending":
                now = time.time()
                step.update({"status": "skipped", "message": reason, "started_at": now, "finished_at": now})
        state["progress"] = round(sum(item["status"] in {"success", "skipped"} for item in state["steps"]) * 100 / len(UPDATE_STEPS))
        return write_update_request(state)


def register_operation_provider(name: str, provider: OperationProvider, resume: ResumeCallback | None = None) -> None:
    with _registry_lock:
        _providers[name] = (provider, resume)


def clear_operation_providers() -> None:
    """Test helper; application code registers providers once during startup."""
    with _registry_lock:
        _providers.clear()
    with _transient_lock:
        _transient_operations.clear()


def active_transient_operations() -> list[dict[str, Any]]:
    with _transient_lock:
        return [dict(value) for value in _transient_operations.values()]


def begin_transient_operation(operation_type: str, *, description: str = "", user_id: str = "") -> str:
    operation_id = uuid4().hex
    with operation_admission():
        with _transient_lock:
            _transient_operations[operation_id] = {
                "id": operation_id,
                "type": operation_type,
                "status": "running",
                "started_at": time.time(),
                "finished_at": None,
                "progress": None,
                "description": description,
                "user_id": user_id,
            }
    return operation_id


def finish_transient_operation(operation_id: str) -> None:
    with _transient_lock:
        _transient_operations.pop(operation_id, None)


@contextmanager
def transient_operation(operation_type: str, *, description: str = "", user_id: str = "") -> Iterator[None]:
    operation_id = begin_transient_operation(operation_type, description=description, user_id=user_id)
    try:
        yield
    finally:
        finish_transient_operation(operation_id)


def _normalize_operation(provider: str, value: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(value.get("status") or "")
    if status not in ACTIVE_OPERATION_STATUSES:
        return None
    started_at = value.get("started_at")
    return {
        "id": str(value.get("id") or f"{provider}-unknown"),
        "type": str(value.get("type") or value.get("operation") or value.get("action") or provider),
        "status": status,
        "started_at": float(started_at) if started_at is not None else None,
        "finished_at": float(value["finished_at"]) if value.get("finished_at") is not None else None,
        "progress": int(value["progress"]) if value.get("progress") is not None else None,
        "description": str(value.get("description") or value.get("current_step") or value.get("stage") or ""),
        "user_id": str(value.get("user_id") or value.get("username") or value.get("created_by") or value.get("requested_by") or ""),
        "source": provider,
    }


def active_operations() -> list[dict[str, Any]]:
    with _registry_lock:
        providers = list(_providers.items())
    result: list[dict[str, Any]] = []
    for name, (provider, _resume) in providers:
        try:
            values = provider()
            for value in values:
                normalized = _normalize_operation(name, value)
                if normalized:
                    result.append(normalized)
        except Exception:  # noqa: BLE001 - registry failures must fail closed.
            result.append({
                "id": f"{name}-registry-unavailable",
                "type": f"{name}.registry",
                "status": "running",
                "started_at": time.time(),
                "finished_at": None,
                "progress": None,
                "description": "Nie można potwierdzić stanu zadań tego modułu.",
                "user_id": "",
                "source": name,
            })
    return sorted(result, key=lambda item: (item["started_at"] or 0, item["source"], item["id"]))


def update_blocks_operations() -> bool:
    return str(read_update_request().get("state") or "") in BLOCKING_UPDATE_STATES


@contextmanager
def operation_admission() -> Iterator[None]:
    """Atomically admit a new durable operation or reject it during an update."""
    with coordination_lock():
        state = read_update_request()
        if str(state.get("state") or "") in BLOCKING_UPDATE_STATES:
            raise HTTPException(
                409,
                {
                    "code": "UPDATE_IN_PROGRESS",
                    "message": UPDATE_BLOCKED_MESSAGE,
                    "update_id": state.get("id") or None,
                },
            )
        yield


def resume_registered_operations() -> None:
    with _registry_lock:
        callbacks = [resume for _provider, resume in _providers.values() if resume is not None]
    for callback in callbacks:
        try:
            callback()
        except Exception:
            continue
