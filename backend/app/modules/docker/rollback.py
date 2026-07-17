from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"}
ROLLBACK_STATE = Path("/var/lib/webnas/docker-manager/engine-rollback.json")
DOCKER_PACKAGES = ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin")


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


if not ROLLBACK_STATE.is_file():
    raise RuntimeError("Docker package rollback state is unavailable")
state = json.loads(ROLLBACK_STATE.read_text(encoding="utf-8"))
manager = state.get("manager")
previous = [str(item) for item in state.get("previous") or []]
conflicts = [str(item) for item in state.get("conflicts") or []]
if manager not in {"apt-get", "dnf", "yum"}:
    raise RuntimeError("Docker package rollback state is invalid")

if manager == "apt-get":
    run([manager, "update"])
    if previous:
        run([manager, "install", "-y", "--allow-downgrades", "--no-install-recommends", *previous])
    else:
        run([manager, "remove", "-y", *DOCKER_PACKAGES], required=False)
        if conflicts:
            run([manager, "install", "-y", "--no-install-recommends", *conflicts])
else:
    if previous and not run([manager, "downgrade", "-y", *previous], required=False):
        run([manager, "install", "-y", *previous])
    elif not previous:
        run([manager, "remove", "-y", *DOCKER_PACKAGES], required=False)
        if conflicts:
            run([manager, "install", "-y", *conflicts])

run(["systemctl", "daemon-reload"], required=False)
if previous:
    run(["systemctl", "enable", "docker"], required=False)
    run(["systemctl", "restart", "docker"], required=False)
ROLLBACK_STATE.unlink(missing_ok=True)
print("Previous Docker package state restored")
