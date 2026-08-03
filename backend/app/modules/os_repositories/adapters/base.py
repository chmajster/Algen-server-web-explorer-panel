from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ..security import managed_path


class RepositoryAdapter:
    """Builds a complete publication inside a private generation directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def link_package(self, package: dict[str, Any], destination: Path) -> None:
        source = managed_path(self.root, package["relative_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        os.chmod(destination, 0o644)
