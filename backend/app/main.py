from __future__ import annotations

import base64
import asyncio
import json
from pathlib import Path
from typing import cast

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audit import configure_logging, logger
from .apps import router as apps_router
from .auth import authenticate, normalize_username, user_home
from .config import get_config
from .file_ops import download_response, list_dir, mime_for, run_user_op, save_upload, tree_dir
from .network_mounts import assert_write_allowed, router as mounts_router
from .path_policy import resolve_user_path
from .security import clear_session, create_session, get_session_user, rate_limiter, require_csrf
from .settings import router as settings_router
from .tasks import task_store

configure_logging()
app = FastAPI(title="WebNAS", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(settings_router)
app.include_router(apps_router)
app.include_router(mounts_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "webnas"}


class LoginRequest(BaseModel):
    username: str
    password: str


class PathRequest(BaseModel):
    path: str


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
    destination = resolve_user_path(username, payload.dst)
    resolve_user_path(username, str(destination.parent))
    assert_write_allowed(destination)
    return destination


def _reject_destination_conflicts(sources: list[Path], destination: Path) -> None:
    if len(sources) > 1 and (not destination.exists() or not destination.is_dir()):
        raise HTTPException(400, "Multiple sources require an existing destination directory")
    for source in sources:
        target = destination / source.name if destination.exists() and destination.is_dir() else destination
        if target.exists():
            raise HTTPException(409, f"Destination already exists: {target.name}")


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    username = normalize_username(payload.username)
    key = f"{request.client.host if request.client else 'unknown'}:{username}"
    rate_limiter.check(key)
    authenticate(username, payload.password)
    csrf = create_session(response, username)
    logger.info("login user=%s", username)
    return {"username": username, "home": user_home(username), "csrf_token": csrf}


@app.post("/api/auth/logout")
def logout(response: Response, user=Depends(csrf_user)):
    logger.info("logout user=%s", user.username)
    clear_session(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"username": user.username, "home": user_home(user.username), "csrf_token": user.csrf_token}


@app.get("/api/files/list")
def files_list(
    path: str | None = None,
    sort: str | None = "name",
    direction: str = "asc",
    page: int = 1,
    page_size: int = 20,
    folders_first: bool = True,
    filter: str | None = None,
    user=Depends(current_user),
):
    payload = list_dir(user.username, path, sort=sort, direction=direction, page=page, page_size=page_size, folders_first=folders_first, filter_text=filter)
    payload["path"] = payload["current_path"]
    return payload


@app.get("/api/files/tree")
def files_tree(path: str | None = None, user=Depends(current_user)):
    return tree_dir(user.username, path)


@app.post("/api/files/mkdir")
def mkdir(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    return run_user_op(user.username, "mkdir", {"path": str(target)})


@app.post("/api/files/create")
def create(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    return run_user_op(user.username, "create", {"path": str(target)})


@app.post("/api/files/copy")
def copy(payload: CopyMoveRequest, user=Depends(csrf_user)):
    srcs = _resolve_sources(user.username, payload)
    dst = _resolve_destination(user.username, payload)
    _reject_destination_conflicts(srcs, dst)
    task = task_store.create(user.username, "copy", {"srcs": [str(src) for src in srcs], "dst": str(dst), "priority": payload.priority})
    return {"task_id": task.id}


@app.post("/api/files/move")
def move(payload: CopyMoveRequest, user=Depends(csrf_user)):
    srcs = _resolve_sources(user.username, payload)
    dst = _resolve_destination(user.username, payload)
    _reject_destination_conflicts(srcs, dst)
    task = task_store.create(user.username, "move", {"srcs": [str(src) for src in srcs], "dst": str(dst), "priority": payload.priority})
    return {"task_id": task.id}


@app.post("/api/files/rename")
def rename(payload: RenameRequest, user=Depends(csrf_user)):
    src = resolve_user_path(user.username, payload.src)
    dst = resolve_user_path(user.username, payload.dst)
    assert_write_allowed(src)
    assert_write_allowed(dst)
    return run_user_op(user.username, "rename", {"src": str(src), "dst": str(dst)})


@app.post("/api/files/delete")
def delete(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    task = task_store.create(user.username, "delete", {"path": str(target)})
    return {"task_id": task.id}


@app.post("/api/files/trash")
def trash(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    return run_user_op(user.username, "trash", {"path": str(target)})


@app.post("/api/files/upload")
async def upload(path: str = Form(...), file: UploadFile = File(...), user=Depends(csrf_user)):
    return await save_upload(user.username, path, file)


@app.get("/api/files/download")
def download(path: str, user=Depends(current_user)):
    return download_response(user.username, path)


@app.get("/api/files/preview")
def preview(path: str, user=Depends(current_user)):
    target = resolve_user_path(user.username, path)
    result = cast(dict[str, str], run_user_op(user.username, "preview", {"path": str(target)}))
    content = base64.b64decode(result["content"])
    return {"path": str(target), "mime": mime_for(str(target)), "content_base64": base64.b64encode(content).decode("ascii")}


@app.get("/api/files/search")
def search(path: str, query: str, user=Depends(current_user)):
    target = resolve_user_path(user.username, path)
    return {"items": run_user_op(user.username, "search", {"path": str(target), "query": query})}


@app.get("/api/files/stat")
def stat(path: str, user=Depends(current_user)):
    target = resolve_user_path(user.username, path)
    return run_user_op(user.username, "stat", {"path": str(target)})


@app.post("/api/files/chmod")
def chmod(payload: ChmodRequest, user=Depends(csrf_user)):
    if not get_config().security.allow_chmod:
        raise HTTPException(403, "chmod is disabled")
    target = resolve_user_path(user.username, payload.path)
    assert_write_allowed(target)
    return run_user_op(user.username, "chmod", {"path": str(target), "mode": payload.mode})


@app.get("/api/tasks")
def tasks(status: str | None = None, user=Depends(current_user)):
    return [_task_payload(task) for task in task_store.list_for(user.username, status)]


@app.get("/api/tasks/{task_id}")
def task(task_id: str, user=Depends(current_user)):
    found = task_store.get(user.username, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return _task_payload(found)


@app.delete("/api/tasks/{task_id}")
def cancel_task(task_id: str, user=Depends(csrf_user)):
    if not task_store.cancel(user.username, task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@app.get("/api/files/tasks")
def file_tasks(status: str | None = None, user=Depends(current_user)):
    return [_task_payload(task) for task in task_store.list_for(user.username, status)]


@app.get("/api/files/tasks/{task_id}")
def file_task(task_id: str, user=Depends(current_user)):
    found = task_store.get(user.username, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return _task_payload(found)


@app.post("/api/files/tasks/{task_id}/cancel")
def file_task_cancel(task_id: str, user=Depends(csrf_user)):
    if not task_store.cancel(user.username, task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@app.post("/api/files/tasks/{task_id}/pause")
def file_task_pause(task_id: str, user=Depends(csrf_user)):
    if not task_store.pause(user.username, task_id):
        raise HTTPException(404, "Task not found or cannot be paused")
    return {"ok": True}


@app.post("/api/files/tasks/{task_id}/resume")
def file_task_resume(task_id: str, user=Depends(csrf_user)):
    if not task_store.resume(user.username, task_id):
        raise HTTPException(404, "Task not found or cannot be resumed")
    return {"ok": True}


@app.post("/api/files/tasks/{task_id}/retry")
def file_task_retry(task_id: str, user=Depends(csrf_user)):
    task = task_store.retry(user.username, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task_id": task.id}


@app.patch("/api/files/tasks/{task_id}/priority")
def file_task_priority(task_id: str, payload: PriorityRequest, user=Depends(csrf_user)):
    if not task_store.set_priority(user.username, task_id, payload.priority):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@app.get("/api/files/tasks/{task_id}/events")
async def file_task_events(task_id: str, user=Depends(current_user)):
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
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
