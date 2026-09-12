from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"}
ROLLBACK_STATE = Path("/var/lib/webnas/docker-manager/engine-rollback.json")
DOCKER_PACKAGES = ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin")
_ALLOWED_MANAGERS = {"apt-get", "dnf", "yum"}


def run(args: list[str], *, required: bool = True) -> bool:
    executable = shutil.which(args[0])
    if not executable:
        if required:
            raise RuntimeError(f"Required rollback executable is unavailable: {args[0]}")
        return False
    result = subprocess.run([executable, *args[1:]], check=False, shell=False, env=SAFE_ENV)
    if required and result.returncode != 0:
        raise RuntimeError(f"Docker package rollback command failed: {args[0]}")
    return result.returncode == 0


def _package_specs(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError("Docker package rollback state is invalid")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RuntimeError("Docker package rollback state is invalid")
        candidate = item.strip()
        if not candidate or candidate.startswith("-") or any(character.isspace() or ord(character) < 32 for character in candidate):
            raise RuntimeError("Docker package rollback state is invalid")
        result.append(candidate)
    return result


def load_state() -> tuple[str, list[str], list[str]]:
    if not ROLLBACK_STATE.is_file():
        raise RuntimeError("Docker package rollback state is unavailable")
    try:
        state = json.loads(ROLLBACK_STATE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Docker package rollback state is invalid") from error
    if not isinstance(state, dict):
        raise RuntimeError("Docker package rollback state is invalid")
    manager = state.get("manager")
    if manager not in _ALLOWED_MANAGERS:
        raise RuntimeError("Docker package rollback state is invalid")
    return manager, _package_specs(state.get("previous", [])), _package_specs(state.get("conflicts", []))


def rollback() -> None:
    manager, previous, conflicts = load_state()

    if manager == "apt-get":
        run([manager, "update"])
        # Remove the attempted Docker package set first. Otherwise packages that were
        # newly introduced by the failed install remain after restoring old versions.
        run([manager, "remove", "-y", *DOCKER_PACKAGES], required=False)
        if previous:
            run([manager, "install", "-y", "--allow-downgrades", "--no-install-recommends", *previous])
        if conflicts:
            run([manager, "install", "-y", "--no-install-recommends", *conflicts])
    else:
        run([manager, "remove", "-y", *DOCKER_PACKAGES], required=False)
        if previous:
            run([manager, "install", "-y", *previous])
        if conflicts:
            run([manager, "install", "-y", *conflicts])

    run(["systemctl", "daemon-reload"], required=False)
    if previous or conflicts:
        run(["systemctl", "enable", "docker"], required=False)
        run(["systemctl", "restart", "docker"], required=False)
    ROLLBACK_STATE.unlink(missing_ok=True)
    print("Previous Docker package state restored")


if __name__ == "__main__":
    rollback()
