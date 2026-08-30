#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from app.local_auth import (
    LocalAuthRepository,
    _hash_password_unchecked,
    bootstrap_initial_admin,
)


def _read_installer_state(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    state: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key:
            state[key] = value
    return state


def _configuration_was_regenerated() -> bool:
    config = Path(os.environ.get("WEBNAS_CONFIG", "/etc/webnas/config.yaml"))
    backup_root = Path(os.environ.get("WEBNAS_BACKUP_ROOT", "/var/backups/webnas"))
    if not config.is_file() or not backup_root.is_dir():
        return False

    candidates: list[tuple[int, Path]] = []
    try:
        states = backup_root.glob("*/installer-state")
        for state_file in states:
            metadata = _read_installer_state(state_file)
            if metadata.get("action") not in {"update", "reinstall"}:
                continue
            configured_path = metadata.get("config_file", "")
            if configured_path and Path(configured_path) != config:
                continue
            try:
                candidates.append((state_file.stat().st_mtime_ns, state_file))
            except OSError:
                continue
    except OSError:
        return False

    if not candidates:
        return False

    state_mtime_ns, _ = max(candidates, key=lambda item: item[0])
    try:
        return config.stat().st_mtime_ns > state_mtime_ns
    except OSError:
        return False


def _restore_default_admin(username: str, password: str) -> dict[str, object]:
    repository = LocalAuthRepository()
    current = repository.user(username)
    if current is None:
        user = repository.create_user(
            username,
            password,
            role="admin",
            display_name="WebNAS Administrator",
            _allow_short_password=True,
        )
    else:
        now = time.time()
        encoded = _hash_password_unchecked(password)
        with repository.connect() as connection:
            connection.execute(
                """
                UPDATE local_users
                   SET password_hash=?,
                       role='admin',
                       enabled=1,
                       display_name='WebNAS Administrator',
                       updated_at=?,
                       password_changed_at=?
                 WHERE username_key=?
                """,
                (encoded, now, now, username.casefold()),
            )
        user = repository.user(username)
        if user is None:
            raise RuntimeError("Restored local administrator is unavailable")

    repository.set_auth_mode("local", actor="installer-config-reset")
    return user


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    args = parser.parse_args()

    if _configuration_was_regenerated():
        user = _restore_default_admin(args.username, args.password)
        print("Configuration reset detected; default local administrator restored:")
        print(f"Username: {user['username']}")
        print("IMPORTANT: change the default installer password immediately after the first login.")
        return 0

    user, _ = bootstrap_initial_admin(args.username, args.password)
    if user is None:
        print("Local user database already initialized; existing accounts preserved.")
        return 0
    print("Default local administrator created:")
    print(f"Username: {user['username']}")
    print("IMPORTANT: change the default installer password immediately after the first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
