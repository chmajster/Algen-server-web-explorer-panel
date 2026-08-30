from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

import yaml
from fastapi import HTTPException, Request


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "backend"))


def _write_config(root: Path) -> Path:
    home = root / "home"
    data = root / "data"
    logs = root / "logs"
    temporary = root / "tmp"
    for path in (home, data, logs, temporary):
        path.mkdir(parents=True, exist_ok=True)
    config = {
        "server": {"host": "127.0.0.1", "port": 5000, "use_https": False},
        "paths": {
            "default_root": "allowed",
            "allowed_roots": [str(home)],
            "data_dir": str(data),
            "log_dir": str(logs),
            "temp_dir": str(temporary),
        },
        "security": {
            "session_secret": "real-e2e-session-secret",
            "cookie_secure": False,
            "allow_insecure_http": True,
            "rate_limit_login_per_minute": 20,
        },
        "proxmox": {"detect": False, "safe_mode": True},
    }
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def create_test_app(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    config_path = _write_config(root)
    os.environ["WEBNAS_CONFIG"] = str(config_path)
    os.environ["WEBNAS_CANDIDATE"] = "1"
    os.environ["WEBNAS_SLOT"] = "real-e2e"
    os.environ["WEBNAS_ACTIVE_SLOT_FILE"] = str(root / "inactive-slot")

    from app.config import get_config

    get_config.cache_clear()

    from app import auth_api
    from app import local_auth
    from app import security as session_security
    from app.identity import permissions as identity_permissions

    session_security._store.cache_clear()
    local_auth.repository.cache_clear()
    local_auth.repository().set_auth_mode("system", "real-e2e")
    username = getpass.getuser()

    def fake_authenticate(candidate: str, password: str) -> None:
        if candidate != username or password != "correct":
            raise HTTPException(status_code=401, detail="Invalid username or password")

    auth_api.authenticate = fake_authenticate
    identity_permissions.has_permission = lambda _username, _permission: True

    from app.bootstrap import create_app

    app = create_app(mount_frontend=False)

    @app.get("/api/__e2e/meta", include_in_schema=False)
    def e2e_meta():
        return {"username": username}

    @app.post("/api/__e2e/expire-session", include_in_schema=False)
    def e2e_expire_session(request: Request):
        cfg = get_config()
        token = request.cookies.get(cfg.auth.session_cookie_name)
        if not token:
            raise HTTPException(status_code=401, detail="No session")
        store = session_security._session_store()
        token_hash = store._hash(token)
        connection = sqlite3.connect(store.path, timeout=10)
        try:
            connection.execute(
                "UPDATE auth_sessions SET expires_at=0 WHERE token_hash=?",
                (token_hash,),
            )
            connection.commit()
        finally:
            connection.close()
        store.invalidate(token)
        return {"ok": True}

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    import uvicorn

    app = create_test_app(args.root.resolve())
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
