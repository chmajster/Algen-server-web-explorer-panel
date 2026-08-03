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


def test_transfer_destination_allows_network_share_root(monkeypatch, tmp_path: Path):
    share_root = tmp_path / "mnt" / "media"
    share_root.mkdir(parents=True)
    monkeypatch.setattr(path_policy, "allowed_roots", lambda username: [share_root])

    resolved = path_policy.ensure_parent_allowed("alice", str(share_root))

    assert resolved == share_root.resolve(strict=False)


def test_transfer_destination_requires_allowed_parent_for_new_path(monkeypatch, tmp_path: Path):
    share_root = tmp_path / "mnt" / "media"
    share_root.mkdir(parents=True)
    monkeypatch.setattr(path_policy, "allowed_roots", lambda username: [share_root])

    resolved = path_policy.ensure_parent_allowed("alice", str(share_root / "new-name.txt"))

    assert resolved == (share_root / "new-name.txt").resolve(strict=False)
