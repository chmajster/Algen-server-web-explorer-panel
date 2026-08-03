from __future__ import annotations

import os

import uvicorn

from .config import get_config


def main() -> None:
    cfg = get_config()
    host = os.environ.get("WEBNAS_BIND_HOST", cfg.server.host)
    port = int(os.environ.get("WEBNAS_BIND_PORT", cfg.server.port))
    behind_gateway = "WEBNAS_BIND_PORT" in os.environ
    if cfg.server.use_https and not behind_gateway:
        uvicorn.run("app.main:app", host=host, port=port, ssl_certfile=cfg.server.tls_cert, ssl_keyfile=cfg.server.tls_key)
    else:
        uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
