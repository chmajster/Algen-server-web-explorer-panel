from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any


SESSION_ID_RE = re.compile(r"^[a-f0-9]{24}$")
DETACHED_UPDATE_OPERATIONS = frozenset({"upgrade_all", "upgrade_security"})
UPDATE_SESSION_DIRECTORY = "linux-update-sessions"


def detached_update_session(plan: dict[str, Any]) -> str | None:
    """Return the server-generated screen session id for a durable Linux update."""
    if plan.get("module_id") != "linux-updates" or plan.get("action") != "manage":
        return None
    payload = plan.get("payload")
    if not isinstance(payload, dict) or payload.get("operation") not in DETACHED_UPDATE_OPERATIONS:
        return None
    session_id = payload.get("screen_session")
    return session_id if isinstance(session_id, str) and SESSION_ID_RE.fullmatch(session_id) else None


def update_session_directory(data_root: Path, session_id: str) -> Path:
    if not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("Invalid Linux update session identifier")
    return data_root / UPDATE_SESSION_DIRECTORY / session_id


def read_update_state(directory: Path) -> dict[str, Any] | None:
    path = directory / "status.json"
    try:
        if path.stat().st_size > 64 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("status") not in {"launching", "running", "completed", "failed"}:
        return None
    return value


def write_update_state(directory: Path, value: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    temporary = directory / f".status-webnas-{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({**value, "updated_at": time.time()}, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / "status.json")
        os.chmod(directory / "status.json", 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
