from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.files.api import router as main


def test_batch_delete_creates_one_task_per_validated_path(monkeypatch):
    created: list[str] = []
    monkeypatch.setattr(main, "resolve_user_path", lambda username, path: Path(path))
    monkeypatch.setattr(main, "assert_write_allowed", lambda path: None)

    def create(username, operation, payload):
        created.append(payload["path"])
        return SimpleNamespace(id=f"task-{len(created)}")

    monkeypatch.setattr(main.task_store, "create", create)
    result = main.delete(main.DeleteRequest(paths=["/home/alice/a", "/home/alice/b"]), user=SimpleNamespace(username="alice"))

    assert created == [str(Path("/home/alice/a")), str(Path("/home/alice/b"))]
    assert result == {"task_id": "task-1", "task_ids": ["task-1", "task-2"]}


def test_batch_delete_rejects_an_empty_request():
    with pytest.raises(HTTPException) as error:
        main.delete(main.DeleteRequest(), user=SimpleNamespace(username="alice"))
    assert error.value.status_code == 400
