from __future__ import annotations

import base64
import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import worker


def _invoke(monkeypatch, capsys, op: str, payload: dict) -> dict:
    monkeypatch.setattr(sys, "argv", ["worker", "--user", "test", "--op", op, "--payload", "unused"])
    monkeypatch.setattr(worker, "_decode_request", lambda _args: ("test", op, payload))
    monkeypatch.setattr(worker, "drop_privileges", lambda _username: None)
    worker.main()
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("direction, expected", [("asc", [0, 1, 17]), ("desc", [17, 1, 0])])
@pytest.mark.parametrize("paginate", [False, True])
def test_zero_size_is_sorted_as_a_number(tmp_path, direction, expected, paginate):
    for size in [17, 0, 1]:
        (tmp_path / f"file-{size}").write_bytes(b"x" * size)
    if paginate:
        result = worker.list_directory({"path": str(tmp_path), "paginate": True, "sort": "size", "direction": direction})
        items = result["items"]
    else:
        items = [worker.info(path) for path in tmp_path.iterdir()]
        worker._sort_items(items, "size", direction, True)
    assert [item["size"] for item in items] == expected


@pytest.mark.parametrize("sort", ["modified", "mtime"])
def test_epoch_mtime_is_not_replaced_by_a_fallback(sort):
    assert worker._sort_value({"mtime": 0, "modified": 123}, sort) == (0, 0.0, "")


@pytest.mark.parametrize("missing", ["owner", "group", "both"])
@pytest.mark.parametrize("operation", ["info", "list", "search"])
def test_unmapped_owner_and_group_do_not_break_file_metadata(monkeypatch, tmp_path, missing, operation):
    path = tmp_path / "match.txt"
    path.write_text("test", encoding="utf-8")
    details = path.stat()
    expected_owner = str(details.st_uid) if missing in {"owner", "both"} else worker.pwd.getpwuid(details.st_uid).pw_name
    expected_group = str(details.st_gid) if missing in {"group", "both"} else worker.grp.getgrgid(details.st_gid).gr_name

    def not_found(_identifier):
        raise KeyError("unmapped filesystem identifier")

    if missing in {"owner", "both"}:
        monkeypatch.setattr(worker.pwd, "getpwuid", not_found)
    if missing in {"group", "both"}:
        monkeypatch.setattr(worker.grp, "getgrgid", not_found)
    if operation == "info":
        items = [worker.info(path)]
    elif operation == "list":
        items = worker.list_directory({"path": str(tmp_path), "paginate": True, "sort": "owner"})["items"]
    else:
        items = worker.search_directory({"path": str(tmp_path), "query": "match"})
    assert len(items) == 1
    assert items[0]["owner"] == expected_owner
    assert items[0]["group"] == expected_group


@pytest.mark.parametrize("limit", [0, 7, 1024 * 1024, 2 * 1024 * 1024, -1])
def test_preview_never_reads_the_entire_file(monkeypatch, capsys, tmp_path, limit):
    path = tmp_path / "large.bin"
    with path.open("wb") as handle:
        handle.truncate(3 * 1024 * 1024)
    expected = max(0, min(limit, 1024 * 1024))
    real_fdopen = worker.os.fdopen
    read_sizes = []

    class TrackedReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, size=-1):
            read_sizes.append(size)
            assert 0 <= size <= expected, "preview issued an unbounded read"
            return self.handle.read(size)

    def tracked_fdopen(*args, **kwargs):
        return TrackedReader(real_fdopen(*args, **kwargs))

    def forbidden_read_bytes(_path):
        pytest.fail("preview must not call Path.read_bytes() before slicing")

    monkeypatch.setattr(worker.os, "fdopen", tracked_fdopen)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    result = _invoke(monkeypatch, capsys, "preview", {"path": str(path), "limit": limit})
    assert len(base64.b64decode(result["content"])) == expected
    assert read_sizes == [expected]


def test_default_preview_limit_is_one_mebibyte(monkeypatch, capsys, tmp_path):
    path = tmp_path / "large.bin"
    with path.open("wb") as handle:
        handle.truncate(2 * 1024 * 1024)
    result = _invoke(monkeypatch, capsys, "preview", {"path": str(path)})
    assert len(base64.b64decode(result["content"])) == 1024 * 1024


@pytest.mark.parametrize("operation", ["read_text", "write_text", "preview"])
def test_fifo_is_rejected_without_waiting_for_another_process(tmp_path, operation):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    backend = str(Path(worker.__file__).resolve().parents[1])
    code = """
import json, sys
from app import worker
op, path = sys.argv[1:]
worker.drop_privileges = lambda _username: None
worker._decode_request = lambda _args: ('test', op, {'path': path, 'content': 'x'})
sys.argv = ['worker', '--user', 'test', '--op', op, '--payload', 'unused']
try:
    worker.main()
except worker.WorkerError as error:
    print(json.dumps({'error': error.code}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, operation, str(fifo)],
        env={**os.environ, "PYTHONPATH": backend + os.pathsep + os.environ.get("PYTHONPATH", "")},
        capture_output=True, text=True, timeout=2, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"error": "not_regular_file"}


@pytest.mark.parametrize("operation", ["read_text", "write_text", "preview"])
def test_non_regular_file_is_rejected_before_open(monkeypatch, capsys, tmp_path, operation):
    path = tmp_path / "pipe"
    os.mkfifo(path)

    def forbidden_open(*_args, **_kwargs):
        pytest.fail("a known non-regular file must not be opened")

    monkeypatch.setattr(worker.os, "open", forbidden_open)
    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(worker.WorkerError, match="not_regular_file"):
        _invoke(monkeypatch, capsys, operation, {"path": str(path), "content": "x"})


class _ShortWriter:
    def __init__(self, handle, chunk_size):
        self.handle = handle
        self.chunk_size = chunk_size

    def __enter__(self):
        self.handle.__enter__()
        return self

    def __exit__(self, *args):
        return self.handle.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def write(self, data):
        if self.chunk_size is None:
            return None
        if self.chunk_size == 0:
            return 0
        return self.handle.write(data[:self.chunk_size])


@pytest.mark.parametrize("chunk_size", [1, 3, 16])
def test_text_save_retries_short_unbuffered_writes(monkeypatch, tmp_path, chunk_size):
    path = tmp_path / "text.txt"
    path.write_text("old contents to replace completely", encoding="utf-8")
    real_fdopen = worker.os.fdopen
    monkeypatch.setattr(worker.os, "fdopen", lambda *args, **kwargs: _ShortWriter(real_fdopen(*args, **kwargs), chunk_size))
    text = "Zażółć gęślą jaźń\nsecond line\n"
    result = worker.write_text_file(path, text, None)
    assert path.read_text(encoding="utf-8") == text
    assert result["size"] == len(text.encode("utf-8"))
    assert result["mtime_ns"] == path.stat().st_mtime_ns


@pytest.mark.parametrize("progress", [None, 0])
def test_text_save_does_not_report_success_or_truncate_on_zero_progress(monkeypatch, tmp_path, progress):
    path = tmp_path / "text.txt"
    original = "keep the original when no bytes were written"
    path.write_text(original, encoding="utf-8")
    real_fdopen = worker.os.fdopen
    monkeypatch.setattr(worker.os, "fdopen", lambda *args, **kwargs: _ShortWriter(real_fdopen(*args, **kwargs), progress))
    with pytest.raises(OSError) as error:
        worker.write_text_file(path, "new contents", None)
    assert error.value.errno == errno.EIO
    assert path.read_text(encoding="utf-8") == original


def test_text_round_trip_and_empty_save(tmp_path):
    path = tmp_path / "text.txt"
    path.write_text("Zażółć gęślą jaźń", encoding="utf-8")
    before = worker.read_text_file(path)
    assert before["content"] == "Zażółć gęślą jaźń"
    result = worker.write_text_file(path, "", before["mtime_ns"])
    assert result["size"] == 0
    assert path.read_bytes() == b""


def test_text_version_conflict_preserves_original(tmp_path):
    path = tmp_path / "text.txt"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(worker.WorkerError, match="changed_on_disk"):
        worker.write_text_file(path, "new", path.stat().st_mtime_ns - 1)
    assert path.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("content", [b"a\x00b", b"\xff\xfe"])
def test_binary_editor_input_is_still_rejected(tmp_path, content):
    path = tmp_path / "binary"
    path.write_bytes(content)
    with pytest.raises(worker.WorkerError, match="binary_file"):
        worker.read_text_file(path)


def test_oversized_editor_input_is_still_rejected(tmp_path):
    path = tmp_path / "big.txt"
    with path.open("wb") as handle:
        handle.truncate(worker.MAX_TEXT_FILE_BYTES + 1)
    with pytest.raises(worker.WorkerError, match="file_too_large"):
        worker.read_text_file(path)


def test_symlink_target_is_not_modified_by_the_editor(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("original", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises((worker.WorkerError, OSError)):
        worker.write_text_file(link, "replacement", None)
    assert target.read_text(encoding="utf-8") == "original"
