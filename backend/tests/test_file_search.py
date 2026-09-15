from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import worker
from app.privileged_broker import file_worker_policy
from app.privileged_broker.policy import PolicyError
from app.privileged_broker.protocol import BrokerRequest, Operation


def search(root: Path, query: str = "*", **options) -> dict:
    result = worker.search_directory({"path": str(root), "query": query, "match_mode": "glob", "include_summary": True, **options})
    assert isinstance(result, dict)
    return result


@pytest.fixture
def tree(tmp_path):
    for name in ["Reports/Annual.TXT", "Reports/photo.jpg", "notes.txt", ".private/secret.txt", ".hidden.txt"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    return tmp_path


def test_search_filters_nested_names_types_case_and_hidden_entries(tree):
    visible = search(tree, "*.txt", item_type="files", show_hidden=False)
    assert {item["name"] for item in visible["items"]} == {"Annual.TXT", "notes.txt"}
    assert visible["truncated"] is False
    assert visible["skipped"] == 0
    assert [item["name"] for item in search(tree, "*.txt", case_sensitive=True, show_hidden=False)["items"]] == ["notes.txt"]
    assert {item["name"] for item in search(tree, "*.txt", show_hidden=True)["items"]} == {"Annual.TXT", "notes.txt", "secret.txt", ".hidden.txt"}
    assert [item["name"] for item in search(tree, "port", match_mode="contains", item_type="folders", show_hidden=False)["items"]] == ["Reports"]
    assert not search(tree, "Reports", item_type="files")["items"]


def test_search_casefolds_unicode_and_treats_contains_as_literal(tmp_path):
    (tmp_path / "Straße.txt").touch()
    (tmp_path / "literal*.txt").touch()
    assert [item["name"] for item in search(tmp_path, "STRASSE", match_mode="contains")["items"]] == ["Straße.txt"]
    assert [item["name"] for item in search(tmp_path, "*", match_mode="contains")["items"]] == ["literal*.txt"]


def test_search_does_not_descend_into_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").touch()
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    (root / "loop").symlink_to(root, target_is_directory=True)
    result = search(root, "*.txt")
    assert result["items"] == []
    assert result["scanned"] == 2
    assert result["truncated"] is False


def test_search_reports_truncation_only_when_an_extra_result_exists(tmp_path):
    (tmp_path / "one.txt").touch()
    complete = search(tmp_path, limit=1)
    assert len(complete["items"]) == 1
    assert complete["truncated"] is False
    (tmp_path / "two.txt").touch()
    partial = search(tmp_path, limit=1)
    assert len(partial["items"]) == 1
    assert partial["reason"] == "limit"
    assert partial["truncated"] is True


def test_search_exposes_entry_and_time_budgets(tmp_path, monkeypatch):
    (tmp_path / "a.txt").touch()
    (tmp_path / "b.txt").touch()
    result = search(tmp_path, "absent", max_entries=1)
    assert result["items"] == []
    assert result["scanned"] == 1
    assert result["reason"] == "entries"
    clock = iter([0, 0, 0, 2])
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock))
    result = search(tmp_path, timeout_seconds=1)
    assert result["scanned"] == 1
    assert result["reason"] == "timeout"


@pytest.mark.parametrize("error", [PermissionError, FileNotFoundError, NotADirectoryError])
def test_search_root_errors_are_not_disguised_as_empty_results(tmp_path, monkeypatch, error):
    def inaccessible(_path):
        raise error("root unavailable")

    monkeypatch.setattr(worker.os, "scandir", inaccessible)
    with pytest.raises(error):
        search(tmp_path)


def test_search_reports_unreadable_subfolders_and_keeps_accessible_results(tree, monkeypatch):
    real_scandir = worker.os.scandir

    def scandir(path):
        if Path(path).name == "Reports":
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(worker.os, "scandir", scandir)
    result = search(tree, "*.txt", show_hidden=False)
    assert [item["name"] for item in result["items"]] == ["notes.txt"]
    assert result["skipped"] == 1
    assert result["truncated"] is False


@pytest.fixture
def search_api(monkeypatch, tmp_path):
    module = importlib.import_module("app.modules.files.api.router")
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.current_user] = lambda: SimpleNamespace(username="alice")
    monkeypatch.setattr(module, "authorize", lambda *_args: None)
    monkeypatch.setattr(module, "resolve_user_path", lambda *_args: tmp_path)
    calls = []

    def run_user_op(username, operation, payload):
        calls.append((username, operation, payload))
        return worker.search_directory(payload)

    monkeypatch.setattr(module, "run_user_op", run_user_op)
    with TestClient(app) as client:
        yield client, module, calls, tmp_path


def test_search_api_applies_filters_and_returns_summary(search_api):
    client, _module, calls, root = search_api
    (root / "Report.TXT").touch()
    (root / ".secret.TXT").touch()
    response = client.get("/api/files/search", params={"path": str(root), "query": "*.TXT", "match_mode": "glob", "item_type": "files", "case_sensitive": "true"})
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["Report.TXT"]
    assert response.json()["truncated"] is False
    username, operation, payload = calls[0]
    assert (username, operation) == ("alice", "search")
    assert payload["show_hidden"] is False
    assert payload["case_sensitive"] is True


@pytest.mark.parametrize("params", [{"query": ""}, {"query": "   "}, {"query": "x" * 257}, {"match_mode": "regex"}, {"item_type": "device"}, {"case_sensitive": "invalid"}])
def test_search_api_rejects_invalid_input_before_running_worker(search_api, params):
    client, _module, calls, root = search_api
    response = client.get("/api/files/search", params={"path": str(root), "query": "test", **params})
    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("boundary", ["authorize", "resolve_user_path"])
def test_search_api_keeps_authorization_and_path_policy(search_api, monkeypatch, boundary):
    client, module, calls, root = search_api

    def denied(*_args):
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(module, boundary, denied)
    response = client.get("/api/files/search", params={"path": str(root), "query": "test"})
    assert response.status_code == 403
    assert calls == []


def test_search_api_supports_legacy_worker_response(search_api, monkeypatch):
    client, module, _calls, root = search_api
    monkeypatch.setattr(module, "run_user_op", lambda *_args: [])
    assert client.get("/api/files/search", params={"path": str(root), "query": "test"}).json() == {"items": []}


def test_broker_accepts_search_options_without_accepting_extra_parameters(monkeypatch, tmp_path):
    user = SimpleNamespace(pw_uid=1000, pw_gid=1000)
    monkeypatch.setattr(file_worker_policy.pwd, "getpwnam", lambda _name: user)
    monkeypatch.setattr(file_worker_policy, "resolve_user_path", lambda _user, path: Path(path))
    payload = {"path": str(tmp_path), "query": "*.txt", "match_mode": "glob", "item_type": "files", "case_sensitive": False, "show_hidden": False, "include_summary": True}
    request = BrokerRequest(request_id="a" * 32, actor="alice", operation=Operation.FILE_WORKER, payload={"username": "alice", "op": "search", "payload": payload})
    assert file_worker_policy._validate_request(request)[2] == payload
    request.payload["payload"]["shell"] = True
    with pytest.raises(PolicyError, match="unsupported search parameters"):
        file_worker_policy._validate_request(request)
