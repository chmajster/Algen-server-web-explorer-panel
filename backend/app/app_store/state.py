from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import get_config


APP_STATE_DIR = Path(get_config().paths.data_dir) / "apps"
APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.IGNORECASE)


def app_state_path(app_id: str) -> Path:
    if not APP_ID_RE.fullmatch(app_id):
        raise ValueError("invalid app id")
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = (APP_STATE_DIR / f"{app_id}.json").resolve(strict=False)
    root = APP_STATE_DIR.resolve(strict=False)
    if path.parent != root:
        raise ValueError("invalid app id")
    return path


def read_state(app_id: str) -> dict:
    path = app_state_path(app_id)
    if not path.exists():
        return {"installed": False, "history": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"installed": False, "history": []}
    return value if isinstance(value, dict) else {"installed": False, "history": []}


def write_state(app_id: str, state: dict) -> None:
    path = app_state_path(app_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)
