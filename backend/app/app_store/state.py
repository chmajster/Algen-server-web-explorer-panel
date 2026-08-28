from __future__ import annotations

import json
from pathlib import Path

from ..config import get_config


APP_STATE_DIR = Path(get_config().paths.data_dir) / "apps"


def app_state_path(app_id: str) -> Path:
    APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return APP_STATE_DIR / f"{app_id}.json"


def read_state(app_id: str) -> dict:
    path = app_state_path(app_id)
    if not path.exists():
        return {"installed": False, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(app_id: str, state: dict) -> None:
    path = app_state_path(app_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)
