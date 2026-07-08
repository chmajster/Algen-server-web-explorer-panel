from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

from .auth import user_home
from .config import get_config


def _real(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def allowed_roots(username: str) -> list[Path]:
    cfg = get_config()
    if cfg.paths.allowed_roots:
        return [_real(root.replace("{username}", username)) for root in cfg.paths.allowed_roots]
    return [_real(user_home(username))]


def resolve_user_path(username: str, requested: str | None) -> Path:
    roots = allowed_roots(username)
    base = roots[0]
    candidate = base if not requested else _real(requested if os.path.isabs(requested) else base / requested)
    for root in roots:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise HTTPException(403, "Path is outside allowed roots")


def ensure_parent_allowed(username: str, requested: str) -> Path:
    path = resolve_user_path(username, requested)
    resolve_user_path(username, str(path.parent))
    return path
