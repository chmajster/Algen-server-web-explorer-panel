"""ASGI entry point for WebNAS.

All composition lives in :mod:`app.bootstrap`; business routers are discovered
from module manifests and are never imported here.
"""

from .bootstrap import create_app

app = create_app()

__all__ = ["app", "create_app"]
