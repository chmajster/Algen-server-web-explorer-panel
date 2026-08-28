from __future__ import annotations

import subprocess
import threading
from typing import Any

from fastapi import HTTPException

from ..modules.ansible_controller.security import redact_text
from .models import MAX_COMMAND_BYTES


def run_bounded(args: list[str], *, timeout: float = 12, max_bytes: int = MAX_COMMAND_BYTES) -> tuple[int, str, str]:
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
    except OSError as error:
        raise HTTPException(503, "The log source is unavailable") from error
    output = [bytearray(), bytearray()]
    overflow = threading.Event()

    def drain(index: int, stream: Any, limit: int) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = limit - len(output[index])
            if remaining > 0:
                output[index].extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return

    readers = [
        threading.Thread(target=drain, args=(0, process.stdout, max_bytes), daemon=True),
        threading.Thread(target=drain, args=(1, process.stderr, 64 * 1024), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise HTTPException(504, "The log source did not respond in time") from error
    finally:
        for reader in readers:
            reader.join(timeout=1)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
    if overflow.is_set():
        raise HTTPException(413, "The log source exceeded the response safety limit")
    stdout = bytes(output[0]).decode("utf-8", errors="replace")
    stderr = bytes(output[1]).decode("utf-8", errors="replace")
    return code, stdout, redact_text(stderr, limit=64 * 1024)
