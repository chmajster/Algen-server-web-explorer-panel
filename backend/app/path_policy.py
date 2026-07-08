from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

from .audit import logger
from .auth import user_home
from .config import get_config
from .proxmox_guard import assert_path_allowed, validate_allowed_roots


def _real(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def allowed_roots(username: str) -> list[Path]:
    cfg = get_config()
    if cfg.paths.allowed_roots:
        roots = [_real(root.replace("{username}", username)) for root in cfg.paths.allowed_roots]
    else:
        roots = [_real(user_home(username))]
    try:
        from .network_mounts import visible_mount_roots

        roots.extend(visible_mount_roots(username))
    except Exception:
        pass
    return validate_allowed_roots(username, roots, cfg)


def resolve_user_path(username: str, requested: str | None) -> Path:
    roots = allowed_roots(username)
    base = roots[0]
    candidate = base if not requested else _real(requested if os.path.isabs(requested) else base / requested)
    for root in roots:
        try:
            candidate.relative_to(root)
            assert_path_allowed(candidate, "resolve", include_parent=True)
            return candidate
        except ValueError:
            continue
    logger.info("path_policy_denied user=%s requested=%s reason=outside_allowed_roots", username, requested)
    raise HTTPException(403, "Path is outside allowed roots")


def ensure_parent_allowed(username: str, requested: str) -> Path:
    path = resolve_user_path(username, requested)
    resolve_user_path(username, str(path.parent))
    return path
