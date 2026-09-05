from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


# The worker is started as a file by GNU screen. Add the backend root so the
# existing privileged-broker package can be imported without relying on a
# caller-provided PYTHONPATH.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.privileged_broker.client import BrokerClient
from app.privileged_broker.runtime import broker_command


PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:-]{0,127}$")
APT_INST_RE = re.compile(r"^Inst\s+(?P<name>[A-Za-z0-9][A-Za-z0-9+._:-]*)\s+")
SESSION_RE = re.compile(r"^[a-f0-9]{24}$")
SAFE_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
}


def validate_update_command(command: list[str]) -> list[str]:
    """Accept only the fixed package-manager operations assembled by WebNAS."""
    if command in (["apt-get", "upgrade", "-y"], ["dnf", "upgrade", "-y"], ["yum", "upgrade", "-y"]):
        return command
    if command in (["dnf", "upgrade", "--security", "-y"], ["yum", "upgrade", "--security", "-y"]):
        return command
    apt_security_prefix = ["apt-get", "install", "--only-upgrade", "-y"]
    if command[: len(apt_security_prefix)] == apt_security_prefix:
        packages = command[len(apt_security_prefix) :]
        if packages and all(PACKAGE_RE.fullmatch(package) and not package.startswith("-") for package in packages):
            return command
    raise ValueError("Unsupported detached system update command")


def _write_state(directory: Path, value: dict[str, Any]) -> None:
    value = {**value, "updated_at": time.time()}
    temporary = directory / f".status-{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / "status.json")
        os.chmod(directory / "status.json", 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _probe(command: list[str], *, accepted_codes: set[int]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        shell=False,
        env=SAFE_ENV,
    )
    if result.returncode not in accepted_codes:
        detail = result.stderr.strip() or result.stdout.strip() or f"{command[0]} package probe failed"
        raise RuntimeError(detail[:500])
    return result


def _apt_upgrade_packages() -> list[str]:
    result = _probe(
        ["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"],
        accepted_codes={0},
    )
    packages: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        match = APT_INST_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        if name not in seen:
            seen.add(name)
            packages.append(name)
    return packages


def _rpm_upgrade_packages(manager: str, *, security_only: bool) -> list[str]:
    available = _probe([manager, "-q", "check-update"], accepted_codes={0, 100})
    packages: list[str] = []
    seen: set[str] = set()
    for line in available.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or "." not in parts[0] or parts[0].startswith(("Last", "Obsoleting")):
            continue
        name = parts[0].rsplit(".", 1)[0]
        if PACKAGE_RE.fullmatch(name) and name not in seen:
            seen.add(name)
            packages.append(name)
    if not security_only:
        return packages

    security = _probe([manager, "-q", "updateinfo", "list", "security", "updates"], accepted_codes={0, 100})
    security_names = {
        token.rsplit(".", 1)[0]
        for line in security.stdout.splitlines()
        for token in line.split()
        if "." in token and not token.startswith(("FEDORA-", "RHSA-", "RHEA-", "RHBA-"))
    }
    return [name for name in packages if name in security_names]


def _broker_update_command(command: list[str]) -> list[str] | None:
    apt_security_prefix = ["apt-get", "install", "--only-upgrade", "-y"]
    if command[: len(apt_security_prefix)] == apt_security_prefix:
        # The broker deliberately exposes only a narrow package-manager API.
        # These names came from APT's installed-update simulation, so a normal
        # `apt-get install -y <names>` upgrades the same installed packages.
        return ["apt-get", "install", "-y", *command[len(apt_security_prefix) :]]
    if command == ["apt-get", "upgrade", "-y"]:
        packages = _apt_upgrade_packages()
        return ["apt-get", "install", "-y", *packages] if packages else None
    if command in (["dnf", "upgrade", "-y"], ["yum", "upgrade", "-y"]):
        packages = _rpm_upgrade_packages(command[0], security_only=False)
        return [command[0], "install", "-y", *packages] if packages else None
    if command in (["dnf", "upgrade", "--security", "-y"], ["yum", "upgrade", "--security", "-y"]):
        packages = _rpm_upgrade_packages(command[0], security_only=True)
        return [command[0], "install", "-y", *packages] if packages else None
    raise ValueError("Unsupported privileged detached update command")


def _run_privileged_update(command: list[str], output) -> int:
    translated = _broker_update_command(command)
    if translated is None:
        output.write("No packages require an upgrade.\n")
        output.flush()
        return 0

    output.write("WebNAS is executing the package operation through the privileged broker.\n")
    output.flush()
    client = BrokerClient(timeout=3665.0)
    result = broker_command(
        translated,
        timeout=3600,
        actor="linux-updates-detached",
        client=client,
    )
    if result is None:
        raise RuntimeError("Privileged broker rejected the detached package operation")
    if result.stdout:
        output.write(result.stdout)
        if not result.stdout.endswith("\n"):
            output.write("\n")
    if result.stderr:
        output.write(result.stderr)
        if not result.stderr.endswith("\n"):
            output.write("\n")
    output.flush()
    return result.returncode


def run_update(directory: Path, session_id: str, command: list[str]) -> int:
    if not SESSION_RE.fullmatch(session_id):
        raise ValueError("Invalid detached update session identifier")
    command = validate_update_command(command)
    executable = shutil.which(command[0])
    if not executable:
        raise RuntimeError(f"{command[0]} is unavailable")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    log_path = directory / "output.log"
    clean_env = {
        "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "DEBIAN_FRONTEND": "noninteractive",
    }
    state: dict[str, Any] = {"session_id": session_id, "status": "running", "started_at": time.time(), "pid": os.getpid()}
    _write_state(directory, state)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", errors="replace") as output:
            output.write("WebNAS detached Linux update started.\n")
            output.flush()
            # Standard WebNAS installations intentionally run the web service as
            # the unprivileged `webnas` account. Package mutations must therefore
            # cross the existing root privileged-broker boundary rather than
            # executing apt/dnf/yum directly and failing on package-manager locks.
            if hasattr(os, "geteuid") and os.geteuid() != 0:
                return_code = _run_privileged_update(command, output)
            else:
                process = subprocess.Popen(  # noqa: S603 - executable and arguments pass the closed validator above
                    [executable, *command[1:]],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    env=clean_env,
                )
                state["command_pid"] = process.pid
                _write_state(directory, state)
                return_code = process.wait()
            output.write(f"WebNAS detached Linux update finished with exit code {return_code}.\n")
            output.flush()
            os.fsync(output.fileno())
    except Exception as error:
        _write_state(directory, {**state, "status": "failed", "finished_at": time.time(), "exit_code": 1, "error": str(error)[:500]})
        raise
    final_status = "completed" if return_code == 0 else "failed"
    _write_state(
        directory,
        {
            **state,
            "status": final_status,
            "finished_at": time.time(),
            "exit_code": return_code,
            "error": "" if return_code == 0 else f"Package manager exited with code {return_code}",
        },
    )
    return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebNAS detached Linux update worker")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = arguments.command[1:] if arguments.command[:1] == ["--"] else arguments.command
    try:
        return run_update(Path(arguments.state_dir), arguments.session_id, command)
    except Exception as error:
        print(f"Detached update worker failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
