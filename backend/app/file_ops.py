from __future__ import annotations

import base64
import json
import math
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
from .proxmox_guard import assert_path_allowed


MUTATING_OPS = {"mkdir", "create", "delete", "trash", "chmod", "import_upload"}
SORT_FIELDS = {"name", "size", "type", "owner", "group", "permissions", "modified", "mtime"}


def ensure_temp_dir() -> Path:
    tmp_dir = Path(get_config().paths.temp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(tmp_dir, 0o1777)
    return tmp_dir


def _encode(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def run_user_op(username: str, op: str, payload: dict) -> object:
    for key in ("path", "src", "dst", "tmp"):
        if key in payload and key != "tmp":
            assert_path_allowed(payload[key], op, include_parent=op in MUTATING_OPS)
            if op in MUTATING_OPS or op in {"rename"} or key == "dst":
                from .network_mounts import assert_write_allowed

                assert_write_allowed(payload[key])
    if not current_process_can_impersonate():
        raise HTTPException(503, "File operations require the service to run as root for per-user impersonation")
    cmd = [sys.executable, "-m", "app.worker", "--user", username, "--op", op, "--payload", _encode(payload)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip() or "File operation failed")
    return json.loads(result.stdout or "{}")


def _item_sort_value(item: dict, sort: str) -> object:
    if sort in {"modified", "mtime"}:
        return float(item.get("mtime") or item.get("modified") or 0)
    value = item.get(sort) or ""
    return value.lower() if isinstance(value, str) else value


def _filter_items(items: list[dict], query: str | None) -> list[dict]:
    if not query:
        return items
    needle = query.lower()
    return [
        item
        for item in items
        if needle in str(item.get("name", "")).lower()
        or needle in str(item.get("type", "")).lower()
        or needle in Path(str(item.get("name", ""))).suffix.lower().lstrip(".")
    ]


def list_dir(
    username: str,
    path: str | None,
    *,
    sort: str | None = "name",
    direction: str = "asc",
    page: int = 1,
    page_size: int = 20,
    folders_first: bool = True,
    filter_text: str | None = None,
) -> dict:
    target = resolve_user_path(username, path)
    if sort and sort not in SORT_FIELDS:
        raise HTTPException(400, "Invalid sort field")
    if direction not in {"asc", "desc"}:
        raise HTTPException(400, "Invalid sort direction")
    page = max(1, page)
    page_size = min(max(1, page_size), 20)
    raw_items = run_user_op(username, "list", {"path": str(target)})  # type: ignore[assignment]
    items = _filter_items(list(raw_items), filter_text)
    reverse = direction == "desc"
    if sort:
        items.sort(key=lambda item: _item_sort_value(item, sort), reverse=reverse)
    if folders_first:
        items.sort(key=lambda item: not item.get("is_dir", False))
    total_items = len(items)
    total_pages = max(1, math.ceil(total_items / page_size))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    parent = str(target.parent) if target.parent != target else None
    can_write = os.access(target, os.W_OK)
    return {
        "items": items[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "sort": sort,
        "direction": direction,
        "current_path": str(target),
        "parent_path": parent,
        "can_write": can_write,
        "can_upload": can_write,
        "can_delete": can_write,
    }


def tree_dir(username: str, path: str | None) -> dict:
    target = resolve_user_path(username, path)
    raw_items = run_user_op(username, "list", {"path": str(target)})  # type: ignore[assignment]
    directories = [item for item in raw_items if item.get("is_dir")]
    directories.sort(key=lambda item: str(item.get("name", "")).lower())
    return {"path": str(target), "items": directories}


async def save_upload(username: str, dest_dir: str, upload: UploadFile) -> dict:
    cfg = get_config()
    directory = resolve_user_path(username, dest_dir)
    assert_path_allowed(directory, "upload", include_parent=True)
    filename = Path(upload.filename or "upload.bin").name
    dest = resolve_user_path(username, str(directory / filename))
    assert_path_allowed(dest, "upload", include_parent=True)
    from .network_mounts import assert_write_allowed

    assert_write_allowed(dest)
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
    assert_path_allowed(target, "download")
    tmp_dir = ensure_temp_dir()
    tmp = tmp_dir / f"{uuid4().hex}.download"
    run_user_op(username, "export_download", {"src": str(target), "tmp": str(tmp)})
    return FileResponse(tmp, filename=target.name, background=BackgroundTask(lambda: tmp.unlink(missing_ok=True)))


def mime_for(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"
