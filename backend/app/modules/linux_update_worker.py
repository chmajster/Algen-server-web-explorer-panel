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


PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:-]{0,127}$")
SESSION_RE = re.compile(r"^[a-f0-9]{24}$")


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
