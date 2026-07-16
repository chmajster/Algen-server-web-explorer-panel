from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def package_manager() -> str:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        text = ""
    return "redis-server" if any(item in text for item in ("id=debian", "id=ubuntu", "id=raspbian", "id_like=debian")) else "redis"


def main() -> None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise SystemExit("systemctl is required")
    service = package_manager()
    for action in ("enable", "start"):
        result = subprocess.run([systemctl, action, service], capture_output=True, text=True, timeout=120, check=False, shell=False)
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or f"Could not {action} {service}")


if __name__ == "__main__":
    main()
