from pathlib import Path

import pytest
from fastapi import HTTPException

from app import file_ops


def item(name: str, *, size: int = 0, modified: float = 0, is_dir: bool = False, type_: str = "file") -> dict:
    return {
        "name": name,
        "path": f"/home/alice/{name}",
        "type": "folder" if is_dir else type_,
        "is_dir": is_dir,
        "size": size,
        "owner": "alice",
        "group": "alice",
        "permissions": "0o644",
        "modified": modified,
        "mtime": modified,
    }


def patch_listing(monkeypatch, tmp_path: Path, items: list[dict]) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setattr(file_ops, "resolve_user_path", lambda username, path: root)
    monkeypatch.setattr(file_ops, "allowed_roots", lambda username: [root])
    monkeypatch.setattr(file_ops, "run_user_op", lambda username, op, payload: items)
    return root


def test_page_size_is_capped_at_20(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item(f"file-{index}") for index in range(30)])

    result = file_ops.list_dir("alice", "/", page_size=100)

    assert result["page_size"] == 20
    assert len(result["items"]) == 20


def test_paginates_large_directory(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item(f"file-{index:02d}") for index in range(25)])

    result = file_ops.list_dir("alice", "/", page=2, page_size=20)

    assert result["page"] == 2
    assert result["total_pages"] == 2
    assert len(result["items"]) == 5


def test_sort_by_name(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item("b.txt"), item("a.txt")])

    result = file_ops.list_dir("alice", "/", sort="name", direction="asc")

    assert [entry["name"] for entry in result["items"]] == ["a.txt", "b.txt"]


def test_sort_by_size(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item("2-kb", size=2_048), item("10-mb", size=10_485_760), item("900-b", size=900)])

    result = file_ops.list_dir("alice", "/", sort="size", direction="desc")

    assert [entry["name"] for entry in result["items"]] == ["10-mb", "2-kb", "900-b"]


def test_sort_by_modified(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item("old", modified=1), item("new", modified=2)])

    result = file_ops.list_dir("alice", "/", sort="modified", direction="desc")

    assert [entry["name"] for entry in result["items"]] == ["new", "old"]


def test_folders_first(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item("z.txt"), item("docs", is_dir=True)])

    result = file_ops.list_dir("alice", "/", sort="name", folders_first=True)

    assert result["items"][0]["name"] == "docs"


def test_filtering(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item("photo.jpg", type_="jpg"), item("notes.txt", type_="txt")])

    result = file_ops.list_dir("alice", "/", filter_text="jpg")

    assert [entry["name"] for entry in result["items"]] == ["photo.jpg"]


def test_invalid_sort_parameter(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [])

    with pytest.raises(HTTPException) as exc:
        file_ops.list_dir("alice", "/", sort="not_allowed")

    assert exc.value.status_code == 400


def test_tree_endpoint_returns_only_directories(monkeypatch, tmp_path):
    patch_listing(monkeypatch, tmp_path, [item("docs", is_dir=True), item("file.txt")])

    result = file_ops.tree_dir("alice", "/")

    assert [entry["name"] for entry in result["items"]] == ["docs"]


def test_empty_directory(monkeypatch, tmp_path):
    root = patch_listing(monkeypatch, tmp_path, [])

    result = file_ops.list_dir("alice", "/")

    assert result["items"] == []
    assert result["total_items"] == 0
    assert result["total_pages"] == 1
    assert result["current_path"] == str(root)
    assert result["parent_path"] is None


def test_child_directory_has_parent_within_allowed_root(monkeypatch, tmp_path):
    root = tmp_path / "home"
    child = root / "documents"
    child.mkdir(parents=True)
    monkeypatch.setattr(file_ops, "resolve_user_path", lambda username, path: child)
    monkeypatch.setattr(file_ops, "allowed_roots", lambda username: [root])
    monkeypatch.setattr(file_ops, "run_user_op", lambda username, op, payload: [])

    result = file_ops.list_dir("alice", str(child))

    assert result["parent_path"] == str(root)
