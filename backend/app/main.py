"""ASGI entry point for WebNAS.

All composition lives in :mod:`app.bootstrap`; business routers are discovered
from module manifests and are never imported here.
"""

from __future__ import annotations

import os

from .bootstrap import create_app
from .pam_setup import ensure_webnas_pam_service


# The standard installer validates every candidate release by importing
# ``app.main`` with WEBNAS_CANDIDATE=1 before switching traffic. That validation
# runs with installer privileges, making it the correct place to provision the
# dedicated PAM service without adding privileged side effects to normal
# application startup.
if os.environ.get("WEBNAS_CANDIDATE") == "1" and hasattr(os, "geteuid") and os.geteuid() == 0:
    ensure_webnas_pam_service()

app = create_app()

__all__ = ["app", "create_app"]
