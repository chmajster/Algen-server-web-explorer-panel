from __future__ import annotations

import os
import pwd
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from .config import get_config
from .file_ops import ensure_temp_dir, run_user_op
from .path_policy import resolve_user_path
from .proxmox_guard import assert_path_allowed
from .update_coordination import operation_admission
from .write_policy import assert_write_allowed


MAX_CHUNK_SIZE = 4 * 1024 * 1024


@dataclass
class UploadSession:
    username: str
    destination: Path
    temporary: Path
    size: int
    received: int = 0
    created_at: float = 0


_sessions: dict[str, UploadSession] = {}
_lock = RLock()


def start_upload(username: str, destination_dir: str, filename: str, size: int) -> dict:
    _cleanup_expired()
    limit = get_config().security.max_upload_size_mb * 1024 * 1024
    if size < 0 or size > limit:
        raise HTTPException(413, "Upload is too large")
    directory = resolve_user_path(username, destination_dir)
    safe_name = Path(filename or "upload.bin").name
    destination = resolve_user_path(username, str(directory / safe_name))
    assert_path_allowed(destination, "upload", include_parent=True)
    assert_write_allowed(destination)
    with operation_admission():
        temporary = ensure_temp_dir() / f"{uuid4().hex}.upload"
        temporary.touch(mode=0o600, exist_ok=False)
        upload_id = uuid4().hex
        with _lock:
            _sessions[upload_id] = UploadSession(username=username, destination=destination, temporary=temporary, size=size, created_at=time.time())
        if size == 0:
            _complete(upload_id, _sessions[upload_id])
    return {"upload_id": upload_id, "offset": 0, "size": size, "path": str(destination), "completed": size == 0}


def active_uploads() -> list[dict]:
    _cleanup_expired()
    with _lock:
        sessions = list(_sessions.items())
    return [
        {
            "id": upload_id,
            "type": "upload",
            "status": "running",
            "created_at": session.created_at,
            "finished_at": None,
            "progress": round(session.received * 100 / session.size) if session.size else 100,
            "description": session.destination.name,
            "user_id": session.username,
        }
        for upload_id, session in sessions
    ]


def append_upload(username: str, upload_id: str, offset: int, chunk: bytes) -> dict:
    if len(chunk) > MAX_CHUNK_SIZE:
        raise HTTPException(413, "Upload chunk is too large")
    with _lock:
        session = _owned_session(username, upload_id)
        if offset != session.received:
            raise HTTPException(409, f"Upload offset mismatch; expected {session.received}")
        if session.received + len(chunk) > session.size:
            raise HTTPException(413, "Upload exceeds declared size")
        with session.temporary.open("ab") as handle:
            handle.write(chunk)
        session.received += len(chunk)
        completed = session.received == session.size
        received = session.received
        if completed:
            _complete(upload_id, session)
    return {"upload_id": upload_id, "offset": received, "size": session.size, "path": str(session.destination), "completed": completed}


def cancel_upload(username: str, upload_id: str) -> None:
    with _lock:
        session = _owned_session(username, upload_id)
        _sessions.pop(upload_id, None)
    session.temporary.unlink(missing_ok=True)


def _owned_session(username: str, upload_id: str) -> UploadSession:
    session = _sessions.get(upload_id)
    if not session:
        raise HTTPException(404, "Upload session not found")
    if session.username != username:
        raise HTTPException(403, "Upload session belongs to another user")
    return session


def _complete(upload_id: str, session: UploadSession) -> None:
    try:
        account = pwd.getpwnam(session.username)
        os.chown(session.temporary, account.pw_uid, account.pw_gid)
        os.chmod(session.temporary, 0o600)
        run_user_op(session.username, "import_upload", {"tmp": str(session.temporary), "dst": str(session.destination)})
    finally:
        _sessions.pop(upload_id, None)
        session.temporary.unlink(missing_ok=True)


def _cleanup_expired(max_age_seconds: int = 24 * 60 * 60) -> None:
    threshold = time.time() - max_age_seconds
    with _lock:
        expired = [(upload_id, session) for upload_id, session in _sessions.items() if session.created_at < threshold]
        for upload_id, _session in expired:
            _sessions.pop(upload_id, None)
    for _upload_id, session in expired:
        session.temporary.unlink(missing_ok=True)
