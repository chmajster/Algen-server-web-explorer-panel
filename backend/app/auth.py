from __future__ import annotations

import os
import pwd

import pam
from fastapi import HTTPException


def authenticate(username: str, password: str) -> None:
    if not username or "/" in username or "\x00" in username:
        raise HTTPException(400, "Invalid username")
    authenticator = pam.pam()
    if not authenticator.authenticate(username, password):
        raise HTTPException(401, "Invalid username or password")


def user_home(username: str) -> str:
    try:
        return pwd.getpwnam(username).pw_dir
    except KeyError as exc:
        raise HTTPException(401, "Unknown local user") from exc


def current_process_can_impersonate() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
