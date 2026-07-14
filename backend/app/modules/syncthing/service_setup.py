from __future__ import annotations

import os
import pwd
from pathlib import Path

DATA_DIR = Path("/var/lib/webnas/syncthing")
UNIT_PATH = Path("/etc/systemd/system/webnas-syncthing.service")
UNIT = """[Unit]
Description=Syncthing managed by WebNAS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=webnas
Group=webnas
ExecStart=/usr/bin/syncthing serve --no-browser --no-restart --home=/var/lib/webnas/syncthing
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/webnas/syncthing

[Install]
WantedBy=multi-user.target
"""


def install_service() -> None:
    try:
        account = pwd.getpwnam("webnas")
    except KeyError as error:
        raise SystemExit("The WebNAS service account is required for Syncthing") from error
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(DATA_DIR, account.pw_uid, account.pw_gid)
    temporary = UNIT_PATH.with_suffix(".service.tmp")
    temporary.write_text(UNIT, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(UNIT_PATH)
    print(f"Installed restricted Syncthing unit: {UNIT_PATH}")


def uninstall_service() -> None:
    UNIT_PATH.unlink(missing_ok=True)
    print(f"Removed Syncthing unit; preserved data in {DATA_DIR}")
