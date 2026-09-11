from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
DEFAULT_MAX_RECORDS = 10_000


def prune_history_file(
    path: Path,
    *,
    now: float | None = None,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> dict[str, Any]:
    """Prune NTP JSONL history by age and record count using an atomic rewrite."""
    if retention_seconds <= 0:
        raise ValueError("retention_seconds must be positive")
    if max_records <= 0:
        raise ValueError("max_records must be positive")
    if not path.exists():
        return {"before": 0, "after": 0, "removed": 0, "rewritten": False}

    cutoff = (time.time() if now is None else now) - retention_seconds
    valid: list[tuple[float, str]] = []
    before = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        before += 1
        try:
            payload = json.loads(raw)
            timestamp = float(payload["timestamp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if timestamp >= cutoff:
            valid.append((timestamp, raw))

    valid.sort(key=lambda item: item[0])
    if len(valid) > max_records:
        valid = valid[-max_records:]

    kept = [raw for _, raw in valid]
    after = len(kept)
    removed = before - after
    if removed <= 0:
        return {"before": before, "after": after, "removed": 0, "rewritten": False}

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.retention-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            if kept:
                stream.write("\n".join(kept) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass

    return {"before": before, "after": after, "removed": removed, "rewritten": True}
