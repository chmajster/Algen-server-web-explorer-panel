from __future__ import annotations

from difflib import unified_diff
from typing import Any

_MAX_DIFF_CHARS = 20_000


def build_config_preview(
    *,
    original: str,
    candidate: str,
    path: str,
    backend: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded, human-readable dry-run result for an NTP config change."""
    diff = "".join(
        unified_diff(
            original.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=path,
            tofile=f"{path} (candidate)",
            n=3,
        )
    )
    truncated = len(diff) > _MAX_DIFF_CHARS
    if truncated:
        diff = diff[:_MAX_DIFF_CHARS].rstrip() + "\n... diff truncated by WebNAS ...\n"

    return {
        **validation,
        "backend": backend,
        "path": path,
        "changed": original != candidate,
        "diff": diff,
        "diff_truncated": truncated,
    }
