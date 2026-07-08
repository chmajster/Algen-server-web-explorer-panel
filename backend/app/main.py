from __future__ import annotations

import base64
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audit import configure_logging, logger
from .auth import authenticate, user_home
from .config import get_config
from .file_ops import download_response, list_dir, mime_for, run_user_op, save_upload
from .path_policy import resolve_user_path
from .security import clear_session, create_session, get_session_user, rate_limiter, require_csrf
from .settings import router as settings_router
from .tasks import task_store

configure_logging()
app = FastAPI(title="WebNAS", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(settings_router)


class LoginRequest(BaseModel):
    username: str
    password: str


class PathRequest(BaseModel):
    path: str


class CopyMoveRequest(BaseModel):
    src: str
    dst: str


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


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    key = f"{request.client.host if request.client else 'unknown'}:{payload.username}"
    rate_limiter.check(key)
    authenticate(payload.username, payload.password)
    csrf = create_session(response, payload.username)
    logger.info("login user=%s", payload.username)
    return {"username": payload.username, "home": user_home(payload.username), "csrf_token": csrf}


@app.post("/api/auth/logout")
def logout(response: Response, user=Depends(csrf_user)):
    logger.info("logout user=%s", user.username)
    clear_session(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"username": user.username, "home": user_home(user.username), "csrf_token": user.csrf_token}


@app.get("/api/files/list")
def files_list(path: str | None = None, user=Depends(current_user)):
    return {"path": str(resolve_user_path(user.username, path)), "items": list_dir(user.username, path)}


@app.post("/api/files/mkdir")
def mkdir(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    return run_user_op(user.username, "mkdir", {"path": str(target)})


@app.post("/api/files/create")
def create(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    return run_user_op(user.username, "create", {"path": str(target)})


@app.post("/api/files/copy")
def copy(payload: CopyMoveRequest, user=Depends(csrf_user)):
    src = resolve_user_path(user.username, payload.src)
    dst = resolve_user_path(user.username, payload.dst)
    task = task_store.create(user.username, "copy", {"src": str(src), "dst": str(dst)})
    return {"task_id": task.id}


@app.post("/api/files/move")
def move(payload: CopyMoveRequest, user=Depends(csrf_user)):
    src = resolve_user_path(user.username, payload.src)
    dst = resolve_user_path(user.username, payload.dst)
    task = task_store.create(user.username, "move", {"src": str(src), "dst": str(dst)})
    return {"task_id": task.id}


@app.post("/api/files/rename")
def rename(payload: RenameRequest, user=Depends(csrf_user)):
    src = resolve_user_path(user.username, payload.src)
    dst = resolve_user_path(user.username, payload.dst)
    return run_user_op(user.username, "rename", {"src": str(src), "dst": str(dst)})


@app.post("/api/files/delete")
def delete(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
    task = task_store.create(user.username, "delete", {"path": str(target)})
    return {"task_id": task.id}


@app.post("/api/files/trash")
def trash(payload: PathRequest, user=Depends(csrf_user)):
    target = resolve_user_path(user.username, payload.path)
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
    result = run_user_op(user.username, "preview", {"path": str(target)})
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
    return run_user_op(user.username, "chmod", {"path": str(target), "mode": payload.mode})


@app.get("/api/tasks")
def tasks(user=Depends(current_user)):
    return [task.__dict__ for task in task_store.list_for(user.username)]


@app.get("/api/tasks/{task_id}")
def task(task_id: str, user=Depends(current_user)):
    found = task_store.get(user.username, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return found.__dict__


@app.delete("/api/tasks/{task_id}")
def cancel_task(task_id: str, user=Depends(csrf_user)):
    if not task_store.cancel(user.username, task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
