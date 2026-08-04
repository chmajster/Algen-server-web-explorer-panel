from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from .audit import logger
from .config import get_config
from .rbac import authorize
from .security import SessionUser, get_session_user, require_csrf


router = APIRouter(tags=["update-policy"])
POLICY_ID = "updates.detailed_steps"


class UpdateDetailPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    detailed_steps: bool = False


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _policy_path() -> Path:
    directory = Path(get_config().paths.data_dir) / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "update_detail_policy.json"


def _default_policy() -> dict[str, object]:
    return {
        "policy_id": POLICY_ID,
        "detailed_steps": False,
        "default_detailed_steps": False,
    }


def _read_policy() -> dict[str, object]:
    path = _policy_path()
    if not path.is_file():
        return _default_policy()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_policy()
    if not isinstance(payload, dict) or type(payload.get("detailed_steps")) is not bool:
        return _default_policy()
    return {
        **_default_policy(),
        "detailed_steps": payload["detailed_steps"],
    }


def _write_policy(value: UpdateDetailPolicy) -> dict[str, object]:
    path = _policy_path()
    temporary = path.with_suffix(".tmp")
    payload = {"detailed_steps": value.detailed_steps}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return {
        **_default_policy(),
        **payload,
    }


@router.get("/api/system/update-detail-policy")
def get_public_update_detail_policy(_user: SessionUser = Depends(_current_user)):
    """Return only the global visibility flag used by the update status screen."""
    return {"detailed_steps": bool(_read_policy()["detailed_steps"])}


@router.get("/api/admin/system/updates/detail-policy")
def get_update_detail_policy(user: SessionUser = Depends(_current_user)):
    authorize(user, "updates.configure_auto_update")
    return _read_policy()


@router.patch("/api/admin/system/updates/detail-policy")
def save_update_detail_policy(
    payload: UpdateDetailPolicy,
    user: SessionUser = Depends(_current_user),
):
    authorize(user, "settings.edit_system")
    authorize(user, "updates.configure_auto_update")
    value = _write_policy(payload)
    logger.info(
        "admin_action actor=%s action=configure_update_detail_policy target=%s enabled=%s",
        user.username,
        POLICY_ID,
        payload.detailed_steps,
    )
    return value
