from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..config import get_config
from .models import SavedView

USER_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")


def views_path(username: str) -> Path:
    if not USER_RE.fullmatch(username):
        raise ValueError("invalid username")
    base = Path(get_config().paths.data_dir) / "log-views"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{username}.json"


def read_views(username: str) -> list[SavedView]:
    path = views_path(username)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    result: list[SavedView] = []
    for item in raw[:100]:
        try:
            result.append(SavedView.model_validate(item))
        except ValueError:
            continue
    return result


def write_views(username: str, views: list[SavedView]) -> None:
    path = views_path(username)
    temporary = path.with_suffix(".tmp")
    payload = json.dumps([view.model_dump(mode="json") for view in views[:100]], ensure_ascii=False, indent=2)
    temporary.write_text(payload, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
