from __future__ import annotations

import base64
import asyncio
import json
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .activity import ActivityCategory, ActivityStatus, record_activity
from .audit import logger
from .auth import authenticate, normalize_username, user_home
from .config import get_config
from .file_ops import download_response, list_dir, mime_for, run_user_op, save_upload, tree_dir
from .identity.permissions import authorize
from .path_policy import ensure_parent_allowed, resolve_user_path
from .security import clear_session, create_session, get_session_user, rate_limiter, require_csrf
from .tasks import task_store
from .update_coordination import read_update_request, transient_operation
from .uploads import append_upload, cancel_upload, start_upload
from .write_policy import assert_write_allowed

router = APIRouter()


async def frontend_cache_policy(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/"):
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@router.get("/api/health")
def health():
    deployment_phase = None
    update_id = None
    try:
        request_state = read_update_request()
        if request_state.get("state") in {"preparing", "running"} and request_state.get("phase") in {"switching", "draining"}:
            deployment_phase = request_state.get("phase")
            update_id = request_state.get("id") or None
    except OSError:
        pass
    return {"status": "ok", "service": "webnas", "deployment_phase": deployment_phase, "update_id": update_id}


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class PathRequest(BaseModel):
    path: str


class DeleteRequest(BaseModel):
    path: str | None = None
    paths: list[str] | None = None


class UploadStartRequest(BaseModel):
    path: str
    filename: str
    size: int


class CopyMoveRequest(BaseModel):
    src: str | None = None
    srcs: list[str] | None = None
    dst: str
    priority: int = 0


class PriorityRequest(BaseModel):
    priority: int


class RenameRequest(BaseModel):
    src: str
    dst: str


class ChmodRequest(BaseModel):
    path: str
    mode: str


class SearchRequest(BaseModel):
    path: str
    query: str


class TextFileWriteRequest(BaseModel):
    path: str
    content: str = Field(max_length=1024 * 1024)
    # Nanosecond timestamps exceed JavaScript's safe integer range, so the API
    # carries the optimistic-lock version as a decimal string.
    expected_mtime_ns: str | None = Field(default=None, pattern=r"^\d+$")


def current_user(request: Request):
    return get_session_user(request)


def csrf_user(request: Request):
    user = get_session_user(request)
    require_csrf(request, user)
    return user


def _task_payload(task):
    return task.to_dict() if hasattr(task, "to_dict") else task.__dict__


def _resolve_sources(username: str, payload: CopyMoveRequest) -> list[Path]:
    raw_sources = payload.srcs or ([payload.src] if payload.src else [])
    if not raw_sources:
        raise HTTPException(400, "At least one source path is required")
    sources = [resolve_user_path(username, source) for source in raw_sources]
    for source in sources:
        if not source.exists():
            raise HTTPException(404, f"Source does not exist: {source.name}")
    return sources


def _resolve_destination(username: str, payload: CopyMoveRequest) -> Path:
    destination = ensure_parent_allowed(username, payload.dst)
    assert_write_allowed(destination)
    return destination


def _reject_destination_conflicts(sources: list[Path], destination: Path) -> None:
    if len(sources) > 1 and (not destination.exists() or not destination.is_dir()):
        raise HTTPException(400, "Multiple sources require an existing destination directory")
    for source in sources:
        target = destination / source.name if destination.exists() and destination.is_dir() else destination
        if target.exists():
            raise HTTPException(409, f"Destination already exists: {target.name}")


@router.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    username = normalize_username(payload.username)
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{username}"
    try:
        rate_limiter.check(key)
        authenticate(username, payload.password)
    except HTTPException as error:
        record_activity(
            ActivityCategory.login,
            "login",
            username or "unknown",
            status=ActivityStatus.failure,
            details={"client": client, "status_code": error.status_code},
            source="auth",
        )
        raise
    csrf = create_session(response, username, remember_me=payload.remember_me)
    logger.info("login user=%s", username)
    record_activity(ActivityCategory.login, "login", username, details={"client": client, "persistent": payload.remember_me}, source="auth")
    return {"username": username, "home": user_home(username), "csrf_token": csrf}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response, user=Depends(csrf_user)):
    logger.info("logout user=%s", user.username)
    record_activity(ActivityCategory.login, "logout", user.username, source="auth")
    clear_session(response, request)
    return {"ok": True}


@router.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"username": user.username, "home": user_home(user.username), "csrf_token": user.csrf_token}


@router.get("/api/files/list")
def files_list(
    path: str | None = None,
    sort: str | None = "name",
    direction: str = "asc",
    page: int = 1,
    page_size: int = 20,
    folders_first: bool = True,
    filter: str | None = None,
    show_hidden: bool = False,
    user=Depends(current_user),
):
    authorize(user, "files.view")
    payload = list_dir(
        user.username,
        path,
        sort=sort,
        direction=direction,
        page=page,
        page_size=page_size,
        folders_first=folders_first,
        filter_text=filter,
        show_hidden=show_hidden,
    )
    payload["path"] = payload["current_path"]
    return payload


@router.get("/api/files/tree")
def files_tree(path: str | None = None, user=Depends(current_user)):
    authorize(user, "files.view")
    return tree_dir(user.username, path)


@router.post("/api/files/mkdir")
def mkdir(payload: PathRequest, user=Depends(csrf_user)):
    authorize(user, "files.create")
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    with transient_operation("file.mkdir", description=target.name, user_id=user.username):
        result = run_user_op(user.username, "mkdir", {"path": str(target)})
    record_activity(ActivityCategory.file, "mkdir", user.username, target=str(target), source="files")
    return result


@router.post("/api/files/create")
def create(payload: PathRequest, user=Depends(csrf_user)):
    authorize(user, "files.create")
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    with transient_operation("file.create", description=target.name, user_id=user.username):
        result = run_user_op(user.username, "create", {"path": str(target)})
    record_activity(ActivityCategory.file, "create", user.username, target=str(target), source="files")
    return result


@router.post("/api/files/copy")
def copy(payload: CopyMoveRequest, user=Depends(csrf_user)):
    authorize(user, "files.copy")
    authorize(user, "transfers.create")
    srcs = _resolve_sources(user.username, payload)
    dst = _resolve_destination(user.username, payload)
    _reject_destination_conflicts(srcs, dst)
    task = task_store.create(user.username, "copy", {"srcs": [str(src) for src in srcs], "dst": str(dst), "priority": payload.priority})
    record_activity(ActivityCategory.file, "copy", user.username, target=str(dst), status=ActivityStatus.queued, details={"sources": len(srcs), "task_id": task.id}, source="files")
    return {"task_id": task.id}


@router.post("/api/files/move")
def move(payload: CopyMoveRequest, user=Depends(csrf_user)):
    authorize(user, "files.move")
    authorize(user, "transfers.create")
    srcs = _resolve_sources(user.username, payload)
    for source in srcs:
        assert_write_allowed(source)
    dst = _resolve_destination(user.username, payload)
    _reject_destination_conflicts(srcs, dst)
    task = task_store.create(user.username, "move", {"srcs": [str(src) for src in srcs], "dst": str(dst), "priority": payload.priority})
    record_activity(ActivityCategory.file, "move", user.username, target=str(dst), status=ActivityStatus.queued, details={"sources": len(srcs), "task_id": task.id}, source="files")
    return {"task_id": task.id}


@router.post("/api/files/rename")
def rename(payload: RenameRequest, user=Depends(csrf_user)):
    authorize(user, "files.rename")
    src = resolve_user_path(user.username, payload.src)
    dst = resolve_user_path(user.username, payload.dst)
    assert_write_allowed(src)
    assert_write_allowed(dst)
    with transient_operation("file.rename", description=src.name, user_id=user.username):
        result = run_user_op(user.username, "rename", {"src": str(src), "dst": str(dst)})
    record_activity(ActivityCategory.file, "rename", user.username, target=str(dst), details={"source": str(src)}, source="files")
    return result


@router.post("/api/files/delete")
def delete(payload: DeleteRequest, user=Depends(csrf_user)):
    authorize(user, "files.delete")
    raw_paths = payload.paths or ([payload.path] if payload.path else [])
    if not raw_paths:
        raise HTTPException(400, "At least one path is required")
    if len(raw_paths) > 500:
        raise HTTPException(400, "A maximum of 500 paths can be deleted at once")
    targets = [resolve_user_path(user.username, path) for path in raw_paths]
    for target in targets:
        assert_write_allowed(target)
    tasks = [task_store.create(user.username, "delete", {"path": str(target)}) for target in targets]
    record_activity(ActivityCategory.file, "delete", user.username, target=str(targets[0]), status=ActivityStatus.queued, details={"items": len(targets), "task_ids": [task.id for task in tasks]}, source="files")
    return {"task_id": tasks[0].id, "task_ids": [task.id for task in tasks]}


@router.post("/api/files/trash")
def trash(payload: PathRequest, user=Depends(csrf_user)):
    authorize(user, "files.delete")
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    with transient_operation("file.trash", description=target.name, user_id=user.username):
        result = run_user_op(user.username, "trash", {"path": str(target)})
    record_activity(ActivityCategory.file, "trash", user.username, target=str(target), source="files")
    return result


@router.post("/api/files/upload")
async def upload(path: str = Form(...), file: UploadFile = File(...), user=Depends(csrf_user)):
    authorize(user, "files.upload")
    with transient_operation("upload", description=Path(file.filename or "upload.bin").name, user_id=user.username):
        result = await save_upload(user.username, path, file)
    record_activity(ActivityCategory.file, "upload", user.username, target=str(result.get("path", path)), details={"filename": file.filename or ""}, source="files")
    return result


@router.post("/api/files/uploads")
def upload_start(payload: UploadStartRequest, user=Depends(csrf_user)):
    authorize(user, "files.upload")
    result = start_upload(user.username, payload.path, payload.filename, payload.size)
    record_activity(ActivityCategory.file, "upload", user.username, target=str(result.get("path", payload.path)), status=ActivityStatus.queued, details={"upload_id": result.get("upload_id"), "size": payload.size}, source="files")
    return result


@router.patch("/api/files/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = Header(..., alias="Upload-Offset"), user=Depends(csrf_user)):
    authorize(user, "files.upload")
    result = append_upload(user.username, upload_id, offset, await request.body())
    if result.get("completed"):
        record_activity(ActivityCategory.file, "upload", user.username, target=str(result.get("path", "")), details={"upload_id": upload_id, "size": result.get("size")}, source="files")
    return result


@router.delete("/api/files/uploads/{upload_id}")
def upload_cancel(upload_id: str, user=Depends(csrf_user)):
    authorize(user, "files.upload")
    cancel_upload(user.username, upload_id)
    record_activity(ActivityCategory.file, "upload_cancel", user.username, status=ActivityStatus.cancelled, details={"upload_id": upload_id}, source="files")
    return {"ok": True}


@router.get("/api/files/download")
def download(path: str, user=Depends(current_user)):
    authorize(user, "files.download")
    response = download_response(user.username, path)
    record_activity(ActivityCategory.file, "download", user.username, target=path, source="files")
    return response


@router.get("/api/files/preview")
def preview(path: str, user=Depends(current_user)):
    authorize(user, "files.read")
    target = resolve_user_path(user.username, path)
    result = cast(dict[str, str], run_user_op(user.username, "preview", {"path": str(target)}))
    content = base64.b64decode(result["content"])
    return {"path": str(target), "mime": mime_for(str(target)), "content_base64": base64.b64encode(content).decode("ascii")}


@router.get("/api/files/text")
def read_text_file(path: str, user=Depends(current_user)):
    authorize(user, "files.read")
    target = resolve_user_path(user.username, path)
    result = cast(dict[str, object], run_user_op(user.username, "read_text", {"path": str(target)}))
    result["mtime_ns"] = str(result["mtime_ns"])
    return {"path": str(target), **result}


@router.put("/api/files/text")
def write_text_file(payload: TextFileWriteRequest, user=Depends(csrf_user)):
    authorize(user, "files.edit")
    if len(payload.content.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(413, {"code": "file_too_large", "message": "This file is too large for the text editor"})
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    with transient_operation("file.write", description=target.name, user_id=user.username):
        result = cast(
            dict[str, object],
            run_user_op(
                user.username,
                "write_text",
                {
                    "path": str(target),
                    "content": payload.content,
                    "expected_mtime_ns": int(payload.expected_mtime_ns) if payload.expected_mtime_ns is not None else None,
                },
            ),
        )
    result["mtime_ns"] = str(result["mtime_ns"])
    record_activity(ActivityCategory.file, "write_text", user.username, target=str(target), details={"size": len(payload.content.encode("utf-8"))}, source="files")
    return {"path": str(target), **result}


@router.get("/api/files/search")
def search(path: str, query: str, user=Depends(current_user)):
    authorize(user, "files.read")
    target = resolve_user_path(user.username, path)
    return {"items": run_user_op(user.username, "search", {"path": str(target), "query": query})}


@router.get("/api/files/stat")
def stat(path: str, user=Depends(current_user)):
    authorize(user, "files.view")
    target = resolve_user_path(user.username, path)
    return run_user_op(user.username, "stat", {"path": str(target)})


@router.post("/api/files/chmod")
def chmod(payload: ChmodRequest, user=Depends(csrf_user)):
    authorize(user, "files.chmod")
    if not get_config().security.allow_chmod:
        raise HTTPException(403, "chmod is disabled")
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    with transient_operation("file.chmod", description=target.name, user_id=user.username):
        result = run_user_op(user.username, "chmod", {"path": str(target), "mode": payload.mode})
    record_activity(ActivityCategory.file, "chmod", user.username, target=str(target), details={"mode": payload.mode}, source="files")
    return result


@router.get("/api/tasks")
def tasks(status: str | None = None, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    return [_task_payload(task) for task in task_store.list_for(user.username, status)]


@router.get("/api/admin/transfers")
def all_tasks(status: str | None = None, user=Depends(current_user)):
    authorize(user, "transfers.view_all")
    return [_task_payload(task) for task in task_store.list_all(status)]


@router.get("/api/tasks/{task_id}")
def task(task_id: str, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    found = task_store.get(user.username, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return _task_payload(found)


@router.delete("/api/tasks/{task_id}")
def cancel_task(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.cancel")
    if not task_store.cancel(user.username, task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@router.get("/api/files/tasks")
def file_tasks(status: str | None = None, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    return [_task_payload(task) for task in task_store.list_for(user.username, status)]


@router.get("/api/files/tasks/{task_id}")
def file_task(task_id: str, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    found = task_store.get(user.username, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return _task_payload(found)


@router.post("/api/files/tasks/{task_id}/cancel")
def file_task_cancel(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.cancel")
    if not task_store.cancel(user.username, task_id):
        raise HTTPException(404, "Task not found")
    record_activity(ActivityCategory.file, "task_cancel", user.username, status=ActivityStatus.cancelled, details={"task_id": task_id}, source="files")
    return {"ok": True}


@router.post("/api/files/tasks/{task_id}/pause")
def file_task_pause(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.pause")
    if not task_store.pause(user.username, task_id):
        raise HTTPException(404, "Task not found or cannot be paused")
    record_activity(ActivityCategory.file, "task_pause", user.username, status=ActivityStatus.info, details={"task_id": task_id}, source="files")
    return {"ok": True}


@router.post("/api/files/tasks/{task_id}/resume")
def file_task_resume(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.resume")
    if not task_store.resume(user.username, task_id):
        raise HTTPException(404, "Task not found or cannot be resumed")
    record_activity(ActivityCategory.file, "task_resume", user.username, status=ActivityStatus.queued, details={"task_id": task_id}, source="files")
    return {"ok": True}


@router.post("/api/files/tasks/{task_id}/retry")
def file_task_retry(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.retry")
    task = task_store.retry(user.username, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    record_activity(ActivityCategory.file, "task_retry", user.username, status=ActivityStatus.queued, details={"task_id": task.id, "retry_of": task_id}, source="files")
    return {"task_id": task.id}


@router.patch("/api/files/tasks/{task_id}/priority")
def file_task_priority(task_id: str, payload: PriorityRequest, user=Depends(csrf_user)):
    authorize(user, "transfers.change_priority")
    if not task_store.set_priority(user.username, task_id, payload.priority):
        raise HTTPException(404, "Task not found")
    record_activity(ActivityCategory.file, "task_priority", user.username, status=ActivityStatus.info, details={"task_id": task_id, "priority": payload.priority}, source="files")
    return {"ok": True}


@router.get("/api/files/tasks/{task_id}/events")
async def file_task_events(task_id: str, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    if not get_config().file_tasks.enable_sse:
        raise HTTPException(404, "Task event streaming is disabled")

    async def events():
        last = ""
        while True:
            found = task_store.get(user.username, task_id)
            if not found:
                yield "event: error\ndata: {\"error\":\"Task not found\"}\n\n"
                return
            payload = json.dumps(_task_payload(found), ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if found.status in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream")


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@router.get("/update-status", include_in_schema=False)
def update_status_frontend():
    index = frontend_dist / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Frontend build is unavailable")
    return FileResponse(index)
