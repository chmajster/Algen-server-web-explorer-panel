#!/usr/bin/env python3.14
from __future__ import annotations

import os
import socket
import sqlite3
from pathlib import Path

root = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_DATA", "/var/lib/webnas/os-repositories"))
database = root / "repositories.sqlite3"
if database.exists():
    with sqlite3.connect(database) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("repository database integrity check failed")
config = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_CONFIG", "/etc/webnas/os-repositories.yaml"))
settings = {"listen_address": "0.0.0.0", "port": "8088"}
if config.exists():
    for line in config.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            settings[key.strip()] = value.strip()
host = settings["listen_address"]
if host in {"0.0.0.0", "::"}:
    host = "127.0.0.1" if host == "0.0.0.0" else "::1"
with socket.create_connection((host, int(settings["port"])), timeout=3):
    pass
print("os-repositories healthy")
