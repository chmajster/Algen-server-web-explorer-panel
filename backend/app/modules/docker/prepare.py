from __future__ import annotations

import os
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"}
ROLLBACK_STATE = Path("/var/lib/webnas/docker-manager/engine-rollback.json")
DOCKER_PACKAGES = ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin")


def save_rollback_state(manager: str, previous: list[str], conflicts: list[str]) -> None:
    ROLLBACK_STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix="engine-rollback-", dir=ROLLBACK_STATE.parent)
    temp = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"manager": manager, "previous": previous, "conflicts": conflicts}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, ROLLBACK_STATE)
        os.chmod(ROLLBACK_STATE, 0o600)
    finally:
        temp.unlink(missing_ok=True)


def values() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key] = value.strip().strip("\"'")
    return result


def run(args: list[str]) -> None:
    executable = shutil.which(args[0])
    if not executable:
        raise RuntimeError(f"Required executable is unavailable: {args[0]}")
    subprocess.run([executable, *args[1:]], check=True, shell=False, env=SAFE_ENV)


def atomic_download(url: str, target: Path) -> None:
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310 - URL is assembled only from closed Docker HTTPS origins
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024 or len(content) < 100:
        raise RuntimeError("Docker repository file has an invalid size")
    descriptor, raw = tempfile.mkstemp(prefix="webnas-docker-", dir=target.parent)
    temp = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def apt_prepare(data: dict[str, str]) -> None:
    distro = data.get("ID", "debian").lower()
    family = "ubuntu" if distro == "ubuntu" else "raspbian" if distro == "raspbian" else "debian"
    run(["apt-get", "update"])
    run(["apt-get", "install", "-y", "--no-install-recommends", "ca-certificates"])
    installed: list[str] = []
    query_tool = shutil.which("dpkg-query")
    if not query_tool:
        raise RuntimeError("dpkg-query is unavailable")
    for package in ("docker.io", "docker-compose", "docker-doc", "podman-docker", "containerd", "runc"):
        query = subprocess.run([query_tool, "-W", "-f=${db:Status-Abbrev}", package], capture_output=True, text=True, check=False, shell=False, env=SAFE_ENV)
        if query.returncode == 0 and query.stdout.startswith("ii"):
            installed.append(package)
    previous: list[str] = []
    for package in DOCKER_PACKAGES:
        query = subprocess.run([query_tool, "-W", "-f=${Version}", package], capture_output=True, text=True, check=False, shell=False, env=SAFE_ENV)
        if query.returncode == 0 and query.stdout.strip():
            previous.append(f"{package}={query.stdout.strip()}")
    save_rollback_state("apt-get", previous, installed)
    if installed:
        run(["apt-get", "remove", "-y", *installed])
    key = Path("/etc/apt/keyrings/docker.asc")
    atomic_download(f"https://download.docker.com/linux/{family}/gpg", key)
    dpkg = shutil.which("dpkg")
    if not dpkg:
        raise RuntimeError("dpkg is unavailable")
    architecture = subprocess.run([dpkg, "--print-architecture"], capture_output=True, text=True, check=True, shell=False, env=SAFE_ENV).stdout.strip()
    codename = data.get("VERSION_CODENAME") or data.get("UBUNTU_CODENAME")
    if not codename or not codename.replace("-", "").isalnum():
        raise RuntimeError("Could not determine distribution codename for Docker repository")
    source = Path("/etc/apt/sources.list.d/docker.sources")
    source_content = f"Types: deb\nURIs: https://download.docker.com/linux/{family}\nSuites: {codename}\nComponents: stable\nArchitectures: {architecture}\nSigned-By: {key}\n"
    descriptor, raw = tempfile.mkstemp(prefix="webnas-docker-source-", dir=source.parent)
    temp = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(source_content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, source)
    finally:
        temp.unlink(missing_ok=True)


def rpm_prepare(data: dict[str, str]) -> None:
    distro = data.get("ID", "fedora").lower()
    family = "fedora" if distro == "fedora" else "rhel"
    manager = "dnf" if shutil.which("dnf") else "yum"
    rpm = shutil.which("rpm")
    if not rpm or not shutil.which(manager):
        raise RuntimeError("RPM package tools are unavailable")
    installed: list[str] = []
    conflicts = ("docker", "docker-client", "docker-client-latest", "docker-common", "docker-latest", "docker-latest-logrotate", "docker-logrotate", "docker-selinux", "docker-engine-selinux", "docker-engine", "podman-docker", "moby-engine")
    for package in conflicts:
        query = subprocess.run([rpm, "-q", package], capture_output=True, text=True, check=False, shell=False, env=SAFE_ENV)
        if query.returncode == 0:
            installed.append(package)
    previous: list[str] = []
    for package in DOCKER_PACKAGES:
        query = subprocess.run([rpm, "-q", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}", package], capture_output=True, text=True, check=False, shell=False, env=SAFE_ENV)
        if query.returncode == 0 and query.stdout.strip():
            previous.append(query.stdout.strip())
    save_rollback_state(manager, previous, installed)
    if installed:
        run([manager, "remove", "-y", *installed])
    atomic_download(f"https://download.docker.com/linux/{family}/docker-ce.repo", Path("/etc/yum.repos.d/docker-ce.repo"))


data = values()
identifier = data.get("ID", "").lower()
like = data.get("ID_LIKE", "").lower().split()
try:
    if identifier in {"debian", "ubuntu", "raspbian"} or "debian" in like:
        apt_prepare(data)
    elif identifier in {"fedora", "rhel", "rocky", "almalinux"} or set(like) & {"fedora", "rhel"}:
        rpm_prepare(data)
    else:
        raise RuntimeError(f"Docker stable repository is not supported on {identifier or platform.system()}")
except Exception as error:
    if ROLLBACK_STATE.is_file():
        rollback = subprocess.run([sys.executable, str(Path(__file__).with_name("rollback.py"))], capture_output=True, text=True, timeout=1800, check=False, shell=False, env=SAFE_ENV)
        if rollback.returncode != 0:
            raise RuntimeError(f"Docker repository preparation failed and package rollback also failed: {rollback.stderr.strip() or rollback.stdout.strip()}") from error
    raise
