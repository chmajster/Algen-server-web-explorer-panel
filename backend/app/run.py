from __future__ import annotations

import uvicorn

from .config import get_config


def main() -> None:
    cfg = get_config()
    ssl_args = {}
    if cfg.server.use_https:
        ssl_args = {"ssl_certfile": cfg.server.tls_cert, "ssl_keyfile": cfg.server.tls_key}
    uvicorn.run("app.main:app", host=cfg.server.host, port=cfg.server.port, **ssl_args)


if __name__ == "__main__":
    main()
