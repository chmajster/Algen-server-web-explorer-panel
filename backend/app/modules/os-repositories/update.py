#!/usr/bin/env python3.14
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_DATA", "/var/lib/webnas/os-repositories"))


def main() -> None:
    stamp = int(time.time())
    backup = ROOT / "backups" / f"pre-update-{stamp}.sqlite3"
    source = ROOT / "repositories.sqlite3"
    config = Path("/etc/webnas/os-repositories.yaml")
    unit = Path("/etc/systemd/system/webnas-repository-server.service")
    config_backup = ROOT / "backups" / f"pre-update-{stamp}.yaml"
    unit_backup = ROOT / "backups" / f"pre-update-{stamp}.service"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        with closing(sqlite3.connect(source)) as current, closing(sqlite3.connect(backup)) as target:
            current.backup(target)
            target.commit()
        os.chmod(backup, 0o600)
    if config.exists():
        shutil.copy2(config, config_backup)
    if unit.exists():
        shutil.copy2(unit, unit_backup)
    install = Path(__file__).with_name("install.py")
    result = subprocess.run(
        [shutil.which("python3.14") or "/usr/bin/python3.14", str(install)],
        check=False,
        shell=False,
        timeout=900,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        if backup.exists():
            os.replace(backup, source)
        if config_backup.exists():
            shutil.copy2(config_backup, config)
        if unit_backup.exists():
            shutil.copy2(unit_backup, unit)
        subprocess.run(["systemctl", "daemon-reload"], check=False, shell=False, timeout=30)
        subprocess.run(["systemctl", "restart", "webnas-repository-server.service"], check=False, shell=False, timeout=60)
        raise RuntimeError("os-repositories update failed and database was restored")
    print("os-repositories updated")


if __name__ == "__main__":
    main()
