#!/usr/bin/env python3.14
from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    subprocess.run(["systemctl", "disable", "--now", "webnas-repository-server.service"], check=False, shell=False, timeout=60)
    Path("/etc/systemd/system/webnas-repository-server.service").unlink(missing_ok=True)
    # The empty bind-mount target is integration state, not repository data.
    try:
        Path("/srv/webnas-repositories").rmdir()
    except OSError:
        pass
    subprocess.run(["systemctl", "daemon-reload"], check=False, shell=False, timeout=30)
    print("os-repositories uninstalled; private data was preserved")


if __name__ == "__main__":
    main()
