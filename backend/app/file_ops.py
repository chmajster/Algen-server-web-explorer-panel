from __future__ import annotations

import base64
import json
import mimetypes
import os
import pwd
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse

from .auth import current_process_can_impersonate
from .config import get_config
from .path_policy import resolve_user_path


def ensure_temp_dir() -> Path:
    tmp_dir = Path(get_config().paths.temp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(tmp_dir, 0o1777)
    return tmp_dir


def _encode(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def run_user_op(username: str, op: str, payload: dict) -> object:
    if not current_process_can_impersonate():
        raise HTTPException(503, "File operations require the service to run as root for per-user impersonation")
    cmd = [sys.executable, "-m", "app.worker", "--user", username, "--op", op, "--payload", _encode(payload)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip() or "File operation failed")
    return json.loads(result.stdout or "{}")


def list_dir(username: str, path: str | None) -> list[dict]:
    target = resolve_user_path(username, path)
    return run_user_op(username, "list", {"path": str(target)})  # type: ignore[return-value]


async def save_upload(username: str, dest_dir: str, upload: UploadFile) -> dict:
    cfg = get_config()
    directory = resolve_user_path(username, dest_dir)
    filename = Path(upload.filename or "upload.bin").name
    dest = resolve_user_path(username, str(directory / filename))
    tmp_dir = ensure_temp_dir()
    tmp = tmp_dir / f"{uuid4().hex}.upload"
    limit = cfg.security.max_upload_size_mb * 1024 * 1024
    size = 0
    with tmp.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "Upload is too large")
            handle.write(chunk)
    try:
        pw = pwd.getpwnam(username)
        os.chown(tmp, pw.pw_uid, pw.pw_gid)
        os.chmod(tmp, 0o600)
        run_user_op(username, "import_upload", {"tmp": str(tmp), "dst": str(dest)})
        return {"ok": True, "path": str(dest), "size": size}
    finally:
        tmp.unlink(missing_ok=True)


def download_response(username: str, path: str) -> FileResponse:
    target = resolve_user_path(username, path)
    tmp_dir = ensure_temp_dir()
    tmp = tmp_dir / f"{uuid4().hex}.download"
    run_user_op(username, "export_download", {"src": str(target), "tmp": str(tmp)})
    return FileResponse(tmp, filename=target.name, background=BackgroundTask(lambda: tmp.unlink(missing_ok=True)))


def mime_for(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"
