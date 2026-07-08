from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from ..auth import current_process_can_impersonate
from ..config import get_config
from ..proxmox_guard import assert_path_allowed, validate_rsync_args

PROGRESS_RE = re.compile(
    r"^\s*(?P<bytes>[\d,]+)\s+(?P<percent>\d+)%\s+(?P<speed>\S+)\s+(?P<eta>\d+:\d+:\d+)"
)


def find_rsync() -> str:
    configured = get_config().file_tasks.rsync_path
    found = shutil.which(configured) if configured else shutil.which("rsync")
    if configured and not found and Path(configured).exists():
        found = configured
    if not found:
        raise HTTPException(503, "rsync is required for copy and move operations but was not found")
    return found


def human_bytes(value: int | float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    unit = units.pop(0)
    while size >= 1024 and units:
        size /= 1024
        unit = units.pop(0)
    return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"


def human_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:d}:{sec:02d}"


def parse_eta(value: str) -> int | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    hours, minutes, seconds = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds


def parse_speed_bps(value: str) -> float | None:
    match = re.match(r"(?P<number>[\d.,]+)(?P<unit>[A-Za-z/]+)", value)
    if not match:
        return None
    number = float(match.group("number").replace(",", ""))
    unit = match.group("unit").lower()
    multiplier = 1
    if unit.startswith("k"):
        multiplier = 1024
    elif unit.startswith("m"):
        multiplier = 1024**2
    elif unit.startswith("g"):
        multiplier = 1024**3
    elif unit.startswith("t"):
        multiplier = 1024**4
    return number * multiplier


def parse_progress_line(line: str) -> dict:
    match = PROGRESS_RE.search(line.strip())
    if not match:
        return {}
    transferred = int(match.group("bytes").replace(",", ""))
    speed_bps = parse_speed_bps(match.group("speed"))
    eta_seconds = parse_eta(match.group("eta"))
    return {
        "bytes_transferred": transferred,
        "progress_percent": int(match.group("percent")),
        "speed_bps": speed_bps or 0,
        "speed_human": human_bytes(speed_bps or 0) + "/s",
        "eta_seconds": eta_seconds,
        "eta_human": human_eta(eta_seconds),
    }


def count_sources(source_paths: list[Path], on_error: Callable[[str], None]) -> tuple[int, int]:
    total_bytes = 0
    total_files = 0
    for source in source_paths:
        try:
            if source.is_file() or source.is_symlink():
                total_bytes += source.stat().st_size
                total_files += 1
                continue
            for root, dirs, files in os.walk(source, onerror=lambda err: on_error(str(err))):
                root_path = Path(root)
                for name in files:
                    item = root_path / name
                    try:
                        total_bytes += item.stat().st_size
                        total_files += 1
                    except OSError as exc:
                        on_error(str(exc))
                dirs.sort()
                files.sort()
        except OSError as exc:
            on_error(str(exc))
    return total_bytes, total_files


def rsync_source_arg(source: Path) -> str:
    return str(source)


def rsync_destination_arg(destination: Path) -> str:
    return str(destination)


def build_rsync_command(source_paths: list[Path], destination: Path) -> list[str]:
    for source in source_paths:
        assert_path_allowed(source, "rsync-source", include_parent=True)
    assert_path_allowed(destination, "rsync-destination", include_parent=True)
    extra_args = validate_rsync_args(get_config().file_tasks.rsync_extra_args)
    return [
        find_rsync(),
        "--archive",
        "--human-readable",
        "--info=progress2",
        "--stats",
        "--partial",
        "--partial-dir=.webnas-partial",
        "--protect-args",
        *extra_args,
        *[rsync_source_arg(source) for source in source_paths],
        rsync_destination_arg(destination),
    ]


def cleanup_partial_files(username: str, destination: Path, on_error: Callable[[str], None]) -> None:
    partial_dir = destination / ".webnas-partial" if destination.is_dir() else destination.parent / ".webnas-partial"
    if not partial_dir.exists():
        return
    result = subprocess.run(
        ["rm", "-rf", "--", str(partial_dir)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        shell=False,
        preexec_fn=_drop_privileges(username),
    )
    if result.returncode != 0:
        on_error(result.stderr.strip() or f"Could not clean partial files: {partial_dir}")


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _drop_privileges(username: str):
    if not current_process_can_impersonate():
        raise HTTPException(503, "File transfers require the service to run as root for per-user impersonation")
    import pwd

    def drop() -> None:
        pw = pwd.getpwnam(username)
        os.setgid(pw.pw_gid)
        os.initgroups(username, pw.pw_gid)
        os.setuid(pw.pw_uid)

    return drop


def start_rsync(username: str, cmd: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        shell=False,
        preexec_fn=_drop_privileges(username),
        start_new_session=True,
    )


def remove_sources_after_move(username: str, source_paths: list[Path], on_error: Callable[[str], None]) -> None:
    errors: list[str] = []
    for source in sorted(source_paths, key=lambda path: len(path.parts), reverse=True):
        assert_path_allowed(source, "move-cleanup", include_parent=True)
        result = subprocess.run(
            ["rm", "-rf", "--", str(source)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            shell=False,
            preexec_fn=_drop_privileges(username),
        )
        if result.returncode != 0:
            error = result.stderr.strip() or f"Could not remove source after move: {source}"
            errors.append(error)
            on_error(error)
    if errors:
        raise HTTPException(500, "Transfer completed but source cleanup failed")


def now() -> float:
    return time.time()
