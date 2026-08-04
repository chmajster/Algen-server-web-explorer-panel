from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ....activity import ActivityCategory, ActivityStatus, record_activity
from ....auth_api import csrf_user, current_user
from ....config import get_config
from ....identity.permissions import authorize
from ....tasks import task_store

router = APIRouter(tags=["transfers"])


class PriorityRequest(BaseModel):
    priority: int


def _task_payload(task):
    return task.to_dict() if hasattr(task, "to_dict") else task.__dict__


@router.get("/api/tasks")
@router.get("/api/files/tasks")
def tasks(status: str | None = None, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    return [_task_payload(task) for task in task_store.list_for(user.username, status)]


@router.get("/api/admin/transfers")
def all_tasks(status: str | None = None, user=Depends(current_user)):
    authorize(user, "transfers.view_all")
    return [_task_payload(task) for task in task_store.list_all(status)]


@router.get("/api/tasks/{task_id}")
@router.get("/api/files/tasks/{task_id}")
def task(task_id: str, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    found = task_store.get(user.username, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return _task_payload(found)


@router.delete("/api/tasks/{task_id}")
@router.post("/api/files/tasks/{task_id}/cancel")
def cancel_task(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.cancel")
    if not task_store.cancel(user.username, task_id):
        raise HTTPException(404, "Task not found")
    record_activity(ActivityCategory.file, "task_cancel", user.username, status=ActivityStatus.cancelled, details={"task_id": task_id}, source="transfers")
    return {"ok": True}


@router.post("/api/files/tasks/{task_id}/pause")
def pause_task(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.pause")
    if not task_store.pause(user.username, task_id):
        raise HTTPException(404, "Task not found or cannot be paused")
    record_activity(ActivityCategory.file, "task_pause", user.username, status=ActivityStatus.info, details={"task_id": task_id}, source="transfers")
    return {"ok": True}


@router.post("/api/files/tasks/{task_id}/resume")
def resume_task(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.resume")
    if not task_store.resume(user.username, task_id):
        raise HTTPException(404, "Task not found or cannot be resumed")
    record_activity(ActivityCategory.file, "task_resume", user.username, status=ActivityStatus.queued, details={"task_id": task_id}, source="transfers")
    return {"ok": True}


@router.post("/api/files/tasks/{task_id}/retry")
def retry_task(task_id: str, user=Depends(csrf_user)):
    authorize(user, "transfers.retry")
    retried = task_store.retry(user.username, task_id)
    if not retried:
        raise HTTPException(404, "Task not found")
    record_activity(ActivityCategory.file, "task_retry", user.username, status=ActivityStatus.queued, details={"task_id": retried.id, "retry_of": task_id}, source="transfers")
    return {"task_id": retried.id}


@router.patch("/api/files/tasks/{task_id}/priority")
def set_priority(task_id: str, payload: PriorityRequest, user=Depends(csrf_user)):
    authorize(user, "transfers.change_priority")
    if not task_store.set_priority(user.username, task_id, payload.priority):
        raise HTTPException(404, "Task not found")
    record_activity(ActivityCategory.file, "task_priority", user.username, status=ActivityStatus.info, details={"task_id": task_id, "priority": payload.priority}, source="transfers")
    return {"ok": True}


@router.get("/api/files/tasks/{task_id}/events")
async def task_events(task_id: str, user=Depends(current_user)):
    authorize(user, "transfers.view_own")
    if not get_config().file_tasks.enable_sse:
        raise HTTPException(404, "Task event streaming is disabled")

    async def events():
        last = ""
        while True:
            found = task_store.get(user.username, task_id)
            if not found:
                yield 'event: error\ndata: {"error":"Task not found"}\n\n'
                return
            payload = json.dumps(_task_payload(found), ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if found.status in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream")
