from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import file_ops, main, worker, write_policy


def test_reads_utf8_text_with_version(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("Zażółć\nline two", encoding="utf-8")

    result = worker.read_text_file(path)

    assert result["content"] == "Zażółć\nline two"
    assert result["encoding"] == "utf-8"
    assert result["size"] == len("Zażółć\nline two".encode("utf-8"))
    assert result["mtime_ns"] == path.stat().st_mtime_ns


@pytest.mark.parametrize("content", [b"text\x00binary", b"\xff\xfe\x00"])
def test_rejects_binary_or_non_utf8_files(tmp_path: Path, content: bytes):
    path = tmp_path / "binary.dat"
    path.write_bytes(content)

    with pytest.raises(worker.WorkerError) as error:
        worker.read_text_file(path)

    assert error.value.code == "binary_file"


def test_rejects_file_larger_than_editor_limit(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_bytes(b"a" * 11)

    with pytest.raises(worker.WorkerError) as error:
        worker.read_text_file(path, max_bytes=10)

    assert error.value.code == "file_too_large"


def test_writes_text_and_preserves_existing_file_mode(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o640)
    version = path.stat().st_mtime_ns

    result = worker.write_text_file(path, "new\ncontent", version)

    assert path.read_text(encoding="utf-8") == "new\ncontent"
    assert path.stat().st_mode & 0o777 == 0o640
    assert result["size"] == len(b"new\ncontent")
    assert result["mtime_ns"] == path.stat().st_mtime_ns


def test_does_not_overwrite_file_changed_on_disk(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("current", encoding="utf-8")

    with pytest.raises(worker.WorkerError) as error:
        worker.write_text_file(path, "replacement", path.stat().st_mtime_ns + 1)

    assert error.value.code == "changed_on_disk"
    assert path.read_text(encoding="utf-8") == "current"


def test_editor_content_is_sent_to_worker_over_stdin(monkeypatch):
    captured = {}
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(write_policy, "assert_write_allowed", lambda path: None)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(file_ops.subprocess, "run", fake_run)

    result = file_ops.run_user_op("alice", "write_text", {"path": "/home/alice/notes.txt", "content": "private note"})

    assert result == {"ok": True}
    assert captured["command"][-1] == "-"
    assert "private note" not in " ".join(captured["command"])
    assert captured["input"]


def test_write_endpoint_rejects_utf8_payload_over_limit(monkeypatch):
    monkeypatch.setattr(main, "resolve_user_path", lambda username, path: Path(path))

    with pytest.raises(HTTPException) as error:
        main.write_text_file(
            main.TextFileWriteRequest(path="/home/alice/notes.txt", content="ą" * 600_000),
            user=SimpleNamespace(username="alice"),
        )

    assert error.value.status_code == 413
    assert error.value.detail["code"] == "file_too_large"


def test_read_endpoint_returns_resolved_path(monkeypatch, tmp_path: Path):
    path = tmp_path / "notes.txt"
    monkeypatch.setattr(main, "resolve_user_path", lambda username, requested: path)
    monkeypatch.setattr(main, "run_user_op", lambda username, op, payload: {"content": "hello", "encoding": "utf-8", "size": 5, "mtime_ns": 10})

    result = main.read_text_file(str(path), user=SimpleNamespace(username="alice"))

    assert result == {"path": str(path), "content": "hello", "encoding": "utf-8", "size": 5, "mtime_ns": "10"}


def test_write_endpoint_converts_version_without_javascript_precision_loss(monkeypatch, tmp_path: Path):
    path = tmp_path / "notes.txt"
    captured = {}
    monkeypatch.setattr(main, "resolve_user_path", lambda username, requested: path)
    monkeypatch.setattr(main, "assert_write_allowed", lambda target: None)

    def run_user_op(username, op, payload):
        captured.update(payload)
        return {"ok": True, "encoding": "utf-8", "size": 5, "mtime_ns": 1_800_000_000_000_000_123}

    monkeypatch.setattr(main, "run_user_op", run_user_op)

    result = main.write_text_file(
        main.TextFileWriteRequest(path=str(path), content="hello", expected_mtime_ns="1800000000000000000"),
        user=SimpleNamespace(username="alice"),
    )

    assert captured["expected_mtime_ns"] == 1_800_000_000_000_000_000
    assert result["mtime_ns"] == "1800000000000000123"
