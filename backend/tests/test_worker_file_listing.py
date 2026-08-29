from __future__ import annotations

from pathlib import Path

from app import worker


def _create_files(root: Path, count: int) -> None:
    for index in range(count):
        (root / f"file-{index:05d}.txt").write_text("x", encoding="utf-8")


def test_name_sorted_pagination_expands_metadata_only_for_page(monkeypatch, tmp_path: Path):
    _create_files(tmp_path, 1_000)
    real_info = worker.info
    calls: list[Path] = []

    def counted_info(path: Path) -> dict:
        calls.append(path)
        return real_info(path)

    monkeypatch.setattr(worker, "info", counted_info)
    result = worker.list_directory(
        {
            "path": str(tmp_path),
            "paginate": True,
            "sort": "name",
            "direction": "asc",
            "page": 2,
            "page_size": 20,
            "folders_first": True,
            "filter": None,
            "show_hidden": False,
        }
    )

    assert result["pagination"]["total_items"] == 1_000
    assert result["pagination"]["metadata_items"] == 20
    assert len(result["items"]) == 20
    # 20 page entries plus one directory metadata record.
    assert len(calls) == 21
    assert result["items"][0]["name"] == "file-00020.txt"


def test_metadata_sort_expands_all_candidates_for_correct_order(monkeypatch, tmp_path: Path):
    _create_files(tmp_path, 100)
    real_info = worker.info
    calls: list[Path] = []

    def counted_info(path: Path) -> dict:
        calls.append(path)
        return real_info(path)

    monkeypatch.setattr(worker, "info", counted_info)
    result = worker.list_directory(
        {
            "path": str(tmp_path),
            "paginate": True,
            "sort": "size",
            "direction": "desc",
            "page": 1,
            "page_size": 20,
            "folders_first": True,
        }
    )

    assert result["pagination"]["metadata_items"] == 100
    assert len(calls) == 101
    assert len(result["items"]) == 20


def test_filter_and_hidden_semantics_are_preserved(tmp_path: Path):
    (tmp_path / "photo.jpg").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".secret.jpg").write_text("x", encoding="utf-8")

    hidden = worker.list_directory(
        {
            "path": str(tmp_path),
            "paginate": True,
            "sort": "name",
            "direction": "asc",
            "page": 1,
            "page_size": 20,
            "folders_first": True,
            "filter": "jpg",
            "show_hidden": False,
        }
    )
    shown = worker.list_directory(
        {
            "path": str(tmp_path),
            "paginate": True,
            "sort": "name",
            "direction": "asc",
            "page": 1,
            "page_size": 20,
            "folders_first": True,
            "filter": "jpg",
            "show_hidden": True,
        }
    )

    assert [item["name"] for item in hidden["items"]] == ["photo.jpg"]
    assert {item["name"] for item in shown["items"]} == {"photo.jpg", ".secret.jpg"}


def test_large_directory_page_stays_bounded(tmp_path: Path):
    _create_files(tmp_path, 10_000)

    result = worker.list_directory(
        {
            "path": str(tmp_path),
            "paginate": True,
            "sort": "name",
            "direction": "asc",
            "page": 500,
            "page_size": 20,
            "folders_first": True,
        }
    )

    assert result["pagination"]["total_items"] == 10_000
    assert result["pagination"]["total_pages"] == 500
    assert result["pagination"]["metadata_items"] == 20
    assert len(result["items"]) == 20


def test_search_is_bounded_and_does_not_follow_directory_symlinks(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    for index in range(20):
        (nested / f"match-{index}.txt").write_text("x", encoding="utf-8")
    (root / "loop").symlink_to(root, target_is_directory=True)

    result = worker.search_directory(
        {
            "path": str(root),
            "query": "match",
            "limit": 7,
            "max_entries": 100,
            "timeout_seconds": 5,
        }
    )

    assert len(result) == 7
    assert all("match-" in item["name"] for item in result)
