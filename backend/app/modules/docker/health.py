from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


docker = shutil.which("docker")
if not docker:
    raise RuntimeError("Docker CLI was not installed")
for args in ([docker, "version"], [docker, "info"], [docker, "compose", "version"], [docker, "run", "--rm", "hello-world"]):
    result = subprocess.run(args, capture_output=True, text=True, timeout=300, check=False, shell=False)
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or "Docker installation verification failed"
        rollback = subprocess.run([sys.executable, str(Path(__file__).with_name("rollback.py"))], capture_output=True, text=True, timeout=1800, check=False, shell=False)
        if rollback.returncode == 0:
            raise RuntimeError(f"{reason}; previous Docker package state was restored")
        raise RuntimeError(f"{reason}; automatic package rollback failed: {rollback.stderr.strip() or rollback.stdout.strip()}")
Path("/var/lib/webnas/docker-manager/engine-rollback.json").unlink(missing_ok=True)
print("Docker Engine, daemon info, Compose and hello-world verification passed")
