from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import path_policy, proxmox_guard
from app.config import AppConfig
from app.services import rsync_tasks


def proxmox_cfg(**kwargs):
    data = {
        "proxmox": {
            "detect": False,
            "safe_mode": True,
            "protected_paths": [
                "/etc/pve",
                "/var/lib/vz",
                "/mnt/pve",
                "/root",
            ],
            **kwargs.pop("proxmox", {}),
        },
        **kwargs,
    }
    return AppConfig.model_validate(data)


@pytest.fixture()
def safe_cfg(monkeypatch):
    cfg = proxmox_cfg()
    monkeypatch.setattr(proxmox_guard, "get_config", lambda: cfg)
    monkeypatch.setattr(path_policy, "get_config", lambda: cfg)
    monkeypatch.setattr(path_policy, "user_home", lambda username: f"/home/{username}")
    monkeypatch.setattr(proxmox_guard, "user_home", lambda username: f"/home/{username}")
    return cfg


def test_detects_proxmox_by_etc_pve(monkeypatch):
    monkeypatch.setattr(proxmox_guard.Path, "exists", lambda self: str(self) == "/etc/pve")
    monkeypatch.setattr(proxmox_guard.shutil, "which", lambda name: None)
    monkeypatch.setattr(proxmox_guard.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))

    status = proxmox_guard.detect_proxmox()

    assert status.is_proxmox is True


@pytest.mark.parametrize("path", ["/etc/pve", "/var/lib/vz", "/mnt/pve", "/root", "/"])
def test_blocks_protected_paths(safe_cfg, path):
    with pytest.raises(HTTPException) as exc:
        proxmox_guard.assert_path_allowed(path, "delete", include_parent=True)

    assert exc.value.status_code == 403


def test_blocks_symlink_to_protected_path(monkeypatch, tmp_path: Path):
    protected = tmp_path / "etc-pve"
    protected.mkdir()
    home = tmp_path / "home" / "testuser"
    home.mkdir(parents=True)
    link = home / "link"
    link.symlink_to(protected, target_is_directory=True)
    cfg = proxmox_cfg(proxmox={"protected_paths": [str(protected)], "allow_only_home_roots_on_proxmox": False})
    monkeypatch.setattr(proxmox_guard, "get_config", lambda: cfg)
    monkeypatch.setattr(path_policy, "get_config", lambda: cfg)
    monkeypatch.setattr(path_policy, "user_home", lambda username: str(home))
    monkeypatch.setattr(proxmox_guard, "user_home", lambda username: str(home))

    with pytest.raises(HTTPException):
        path_policy.resolve_user_path("testuser", str(link))


@pytest.mark.parametrize("operation", ["move", "copy", "delete", "chmod", "chown"])
def test_blocks_file_operations_on_protected_paths(safe_cfg, operation):
    with pytest.raises(HTTPException):
        proxmox_guard.assert_path_allowed("/etc/pve/nodes", operation, include_parent=True)


def test_allows_home_operation_on_proxmox(safe_cfg):
    resolved = path_policy.resolve_user_path("testuser", "/home/testuser/docs/file.txt")

    assert str(resolved) == "/home/testuser/docs/file.txt"


@pytest.mark.parametrize("root", ["/", "/etc"])
def test_blocks_system_allowed_roots_on_proxmox(monkeypatch, root):
    cfg = proxmox_cfg(paths={"allowed_roots": [root]})
    monkeypatch.setattr(path_policy, "get_config", lambda: cfg)
    monkeypatch.setattr(proxmox_guard, "get_config", lambda: cfg)
    monkeypatch.setattr(path_policy, "user_home", lambda username: "/home/testuser")
    monkeypatch.setattr(proxmox_guard, "user_home", lambda username: "/home/testuser")

    with pytest.raises(HTTPException):
        path_policy.allowed_roots("testuser")


def test_allows_home_allowed_root_on_proxmox(monkeypatch):
    cfg = proxmox_cfg(paths={"allowed_roots": ["/home/{username}"]})
    monkeypatch.setattr(path_policy, "get_config", lambda: cfg)
    monkeypatch.setattr(proxmox_guard, "get_config", lambda: cfg)
    monkeypatch.setattr(path_policy, "user_home", lambda username: "/home/testuser")
    monkeypatch.setattr(proxmox_guard, "user_home", lambda username: "/home/testuser")

    assert path_policy.allowed_roots("testuser") == [Path("/home/testuser")]


def test_blocks_unsafe_rsync_extra_args(monkeypatch):
    cfg = proxmox_cfg(file_tasks={"rsync_extra_args": ["--delete"]})
    monkeypatch.setattr(proxmox_guard, "get_config", lambda: cfg)
    monkeypatch.setattr(rsync_tasks, "get_config", lambda: cfg)

    with pytest.raises(HTTPException):
        rsync_tasks.build_rsync_command([Path("/home/testuser/a")], Path("/home/testuser/b"))
