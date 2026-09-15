from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import file_ops


@pytest.mark.parametrize("direction, expected", [("asc", [0, 1, 17]), ("desc", [17, 1, 0])])
def test_legacy_sort_keeps_zero_size_numeric(direction, expected):
    items, page, total, pages = file_ops._legacy_paginate(
        [{"name": str(size), "size": size} for size in [17, 0, 1]],
        sort="size", direction=direction, page=1, page_size=20,
        folders_first=True, filter_text=None, show_hidden=False,
    )
    assert [item["size"] for item in items] == expected
    assert (page, total, pages) == (1, 3, 1)


@pytest.mark.parametrize("sort", ["modified", "mtime"])
def test_legacy_epoch_mtime_is_not_replaced_by_fallback(sort):
    assert file_ops._item_sort_value({"mtime": 0, "modified": 123}, sort) == (0, 0.0, "")


@pytest.fixture
def download_environment(monkeypatch, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    spool = tmp_path / "spool"
    spool.mkdir()
    monkeypatch.setattr(file_ops, "resolve_user_path", lambda _username, _path: source)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(file_ops, "ensure_temp_dir", lambda: spool)
    return source, spool


def test_failed_download_removes_partial_export(monkeypatch, download_environment):
    source, spool = download_environment
    failure = HTTPException(507, "disk full")

    def failed_export(_username, op, payload):
        assert op == "export_download"
        Path(payload["tmp"]).write_bytes(b"partial sensitive contents")
        raise failure

    monkeypatch.setattr(file_ops, "run_user_op", failed_export)
    with pytest.raises(HTTPException) as error:
        file_ops.download_response("test", str(source))
    assert error.value is failure
    assert list(spool.iterdir()) == []


def test_failed_response_construction_removes_export(monkeypatch, download_environment):
    source, spool = download_environment
    failure = RuntimeError("response construction failed")

    def successful_export(_username, _op, payload):
        Path(payload["tmp"]).write_bytes(b"contents")

    def failed_response(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(file_ops, "run_user_op", successful_export)
    monkeypatch.setattr(file_ops, "FileResponse", failed_response)
    with pytest.raises(RuntimeError) as error:
        file_ops.download_response("test", str(source))
    assert error.value is failure
    assert list(spool.iterdir()) == []


def test_cleanup_failure_does_not_replace_original_download_error(monkeypatch, download_environment):
    source, spool = download_environment
    failure = HTTPException(503, "worker unavailable")
    unlink_calls = []

    def failed_export(_username, _op, payload):
        Path(payload["tmp"]).write_bytes(b"partial")
        raise failure

    def denied_unlink(path, **_kwargs):
        unlink_calls.append(path)
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(file_ops, "run_user_op", failed_export)
    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", denied_unlink)
        with pytest.raises(HTTPException) as error:
            file_ops.download_response("test", str(source))
    assert error.value is failure
    assert len(unlink_calls) == 1
    assert unlink_calls[0].parent == spool


def test_successful_download_keeps_file_until_background_cleanup(monkeypatch, download_environment):
    source, spool = download_environment

    def successful_export(_username, _op, payload):
        Path(payload["tmp"]).write_bytes(b"contents")

    monkeypatch.setattr(file_ops, "run_user_op", successful_export)
    response = file_ops.download_response("test", str(source))
    assert len(list(spool.iterdir())) == 1
    assert Path(response.path).read_bytes() == b"contents"
    assert response.filename == "source.txt"
    assert response.background is not None
    asyncio.run(response.background())
    assert list(spool.iterdir()) == []


@pytest.mark.parametrize("op, seconds", [("search", 30.0), ("list", 3600.0)])
def test_worker_timeout_is_a_controlled_http_error(monkeypatch, op, seconds):
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *_args, **_kwargs: None)

    def timeout(cmd, **kwargs):
        assert kwargs["timeout"] == seconds
        raise subprocess.TimeoutExpired(cmd, seconds, output="private worker output")

    monkeypatch.setattr(file_ops.subprocess, "run", timeout)
    with pytest.raises(HTTPException) as error:
        file_ops.run_user_op("test", op, {"path": "/allowed"})
    assert error.value.status_code == 504
    assert error.value.detail["code"] == "file_worker_timeout"
    assert "private worker output" not in str(error.value.detail)


def test_worker_exit_error_mapping_is_preserved(monkeypatch):
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(file_ops.subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", '{"error":"not_found"}'))
    with pytest.raises(HTTPException) as error:
        file_ops.run_user_op("test", "list", {"path": "/allowed"})
    assert error.value.status_code == 404


def test_worker_success_response_is_preserved(monkeypatch):
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(file_ops.subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, '{"items":[]}', ""))
    assert file_ops.run_user_op("test", "list", {"path": "/allowed"}) == {"items": []}
