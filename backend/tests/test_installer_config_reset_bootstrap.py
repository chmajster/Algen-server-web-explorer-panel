from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
HELPER = REPOSITORY / "scripts" / "consume_local_bootstrap.py"


def _load_helper(monkeypatch: pytest.MonkeyPatch):
    app_module = types.ModuleType("app")
    app_module.__path__ = []  # type: ignore[attr-defined]
    local_auth_module = types.ModuleType("app.local_auth")
    local_auth_module.LocalAuthRepository = object
    local_auth_module._hash_password_unchecked = lambda password: f"hashed:{password}"
    local_auth_module.bootstrap_initial_admin = lambda username, password: (None, "")
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.local_auth", local_auth_module)

    spec = importlib.util.spec_from_file_location("consume_local_bootstrap_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_installer_state(root: Path, config: Path, action: str = "update") -> Path:
    backup = root / "20260831-010000-update.test"
    backup.mkdir(parents=True)
    state = backup / "installer-state"
    state.write_text(
        f"action={action}\nconfig_file={config}\ninstall_dir=/opt/webnas\n",
        encoding="utf-8",
    )
    return state


def test_detects_config_regeneration_after_update_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    helper = _load_helper(monkeypatch)
    config = tmp_path / "config.yaml"
    backups = tmp_path / "backups"
    config.write_text("server:\n  port: 5000\n", encoding="utf-8")
    state = _write_installer_state(backups, config)

    baseline = max(config.stat().st_mtime_ns, state.stat().st_mtime_ns) + 10_000_000
    os.utime(state, ns=(baseline, baseline))
    os.utime(config, ns=(baseline + 10_000_000, baseline + 10_000_000))
    monkeypatch.setenv("WEBNAS_CONFIG", str(config))
    monkeypatch.setenv("WEBNAS_BACKUP_ROOT", str(backups))

    assert helper._configuration_was_regenerated() is True


def test_preserved_config_does_not_trigger_account_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    helper = _load_helper(monkeypatch)
    config = tmp_path / "config.yaml"
    backups = tmp_path / "backups"
    config.write_text("server:\n  port: 5000\n", encoding="utf-8")
    state = _write_installer_state(backups, config)

    baseline = max(config.stat().st_mtime_ns, state.stat().st_mtime_ns) + 10_000_000
    os.utime(config, ns=(baseline, baseline))
    os.utime(state, ns=(baseline + 10_000_000, baseline + 10_000_000))
    monkeypatch.setenv("WEBNAS_CONFIG", str(config))
    monkeypatch.setenv("WEBNAS_BACKUP_ROOT", str(backups))

    assert helper._configuration_was_regenerated() is False


def test_restore_existing_default_admin_resets_password_role_and_auth_mode(monkeypatch: pytest.MonkeyPatch):
    helper = _load_helper(monkeypatch)

    class Connection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, statement: str, parameters: tuple[object, ...]):
            self.calls.append((statement, parameters))

    class Repository:
        def __init__(self) -> None:
            self.connection = Connection()
            self.mode: tuple[str, str] | None = None

        def user(self, username: str):
            return {"username": username, "role": "user", "enabled": False}

        def connect(self):
            return self.connection

        def set_auth_mode(self, mode: str, actor: str):
            self.mode = (mode, actor)
            return mode

    repository = Repository()
    monkeypatch.setattr(helper, "LocalAuthRepository", lambda: repository)
    monkeypatch.setattr(helper, "_hash_password_unchecked", lambda password: "new-default-hash")

    user = helper._restore_default_admin("chris", "1")

    assert user["username"] == "chris"
    assert len(repository.connection.calls) == 1
    statement, parameters = repository.connection.calls[0]
    assert "role='admin'" in statement
    assert "enabled=1" in statement
    assert parameters[0] == "new-default-hash"
    assert parameters[-1] == "chris"
    assert repository.mode == ("local", "installer-config-reset")


def test_restore_missing_default_admin_creates_it_without_deleting_other_users(monkeypatch: pytest.MonkeyPatch):
    helper = _load_helper(monkeypatch)

    class Repository:
        def __init__(self) -> None:
            self.created: tuple[object, ...] | None = None
            self.mode: tuple[str, str] | None = None

        def user(self, username: str):
            return None

        def create_user(self, username: str, password: str, **kwargs):
            self.created = (username, password, kwargs)
            return {"username": username, "role": "admin", "enabled": True}

        def set_auth_mode(self, mode: str, actor: str):
            self.mode = (mode, actor)
            return mode

    repository = Repository()
    monkeypatch.setattr(helper, "LocalAuthRepository", lambda: repository)

    user = helper._restore_default_admin("chris", "1")

    assert user == {"username": "chris", "role": "admin", "enabled": True}
    assert repository.created is not None
    username, password, kwargs = repository.created
    assert username == "chris"
    assert password == "1"
    assert kwargs["role"] == "admin"
    assert kwargs["_allow_short_password"] is True
    assert repository.mode == ("local", "installer-config-reset")
