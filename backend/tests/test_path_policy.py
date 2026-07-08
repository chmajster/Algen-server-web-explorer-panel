from pathlib import Path

import pytest
from fastapi import HTTPException

from app import path_policy


def test_rejects_parent_traversal(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(path_policy, "user_home", lambda username: str(home))

    with pytest.raises(HTTPException):
        path_policy.resolve_user_path("alice", "../etc/passwd")


def test_allows_file_inside_home(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(path_policy, "user_home", lambda username: str(home))

    resolved = path_policy.resolve_user_path("alice", "docs/file.txt")

    assert resolved == (home / "docs/file.txt").resolve(strict=False)
