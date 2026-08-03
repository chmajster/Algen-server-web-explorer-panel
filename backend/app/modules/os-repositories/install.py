#!/usr/bin/env python3
from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_DATA", "/var/lib/webnas/os-repositories"))
UNIT = Path("/etc/systemd/system/webnas-repository-server.service")
CONFIG = Path("/etc/webnas/os-repositories.yaml")
PUBLIC_MOUNT = Path("/srv/webnas-repositories")


def run(args: list[str], timeout: int = 600) -> None:
    subprocess.run(args, check=True, shell=False, timeout=timeout, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})


def install_dependencies() -> None:
    if shutil.which("apt-get"):
        run(["apt-get", "update"], 300)
        run(["apt-get", "install", "-y", "--no-install-recommends", "aptly", "dpkg-dev", "gnupg", "createrepo-c", "rpm"])
        return
    manager = shutil.which("dnf") or shutil.which("yum")
    if not manager:
        raise RuntimeError("os-repositories supports apt, dnf or yum hosts")
    run([manager, "install", "-y", "dnf-plugins-core", "createrepo_c", "rpm-build", "rpm-sign", "gnupg2", "dpkg"])


def main() -> None:
    install_dependencies()
    if os.geteuid() != 0:
        raise RuntimeError("installation requires root")
    try:
        pwd.getpwnam("webnas-repository")
    except KeyError:
        run(["useradd", "--system", "--home", str(ROOT / "published"), "--shell", "/usr/sbin/nologin", "webnas-repository"], 30)
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ROOT, 0o700)
    for name in ("content", "incoming", "published", "snapshots", "builds", "temporary", "gnupg", "backups", "logs", "mirrors", "config"):
        path = ROOT / name
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o755 if name == "published" else 0o700)
    PUBLIC_MOUNT.mkdir(parents=True, exist_ok=True, mode=0o555)
    os.chmod(PUBLIC_MOUNT, 0o555)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text("listen_address: 0.0.0.0\nport: 8088\n", encoding="utf-8")
    os.chmod(CONFIG, 0o644)
    module = Path(__file__).resolve().parents[1] / "os_repositories" / "http_server.py"
    executable = shutil.which("python3") or "/usr/bin/python3"
    unit = f"""[Unit]\nDescription=WebNAS repository server\nAfter=network.target\n\n[Service]\nType=simple\nUser=webnas-repository\nGroup=webnas-repository\nEnvironment=WEBNAS_OS_REPOSITORIES_PUBLISHED={PUBLIC_MOUNT}\nExecStart={executable} {module}\nRestart=on-failure\nRestartSec=2\nNoNewPrivileges=true\nPrivateTmp=true\nPrivateDevices=true\nProtectSystem=strict\nProtectHome=true\nProtectKernelTunables=true\nProtectKernelModules=true\nProtectControlGroups=true\nRestrictSUIDSGID=true\nRestrictRealtime=true\nSystemCallArchitectures=native\nBindReadOnlyPaths={ROOT / "published"}:{PUBLIC_MOUNT}\nRestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX\nLockPersonality=true\nMemoryDenyWriteExecute=true\nLimitNOFILE=4096\n\n[Install]\nWantedBy=multi-user.target\n"""
    UNIT.write_text(unit, encoding="utf-8")
    os.chmod(UNIT, 0o644)
    run(["systemctl", "daemon-reload"], 30)
    run(["systemctl", "enable", "--now", "webnas-repository-server.service"], 60)
    print("os-repositories installed")


if __name__ == "__main__":
    main()
