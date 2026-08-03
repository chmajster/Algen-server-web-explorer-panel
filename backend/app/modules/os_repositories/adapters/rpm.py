from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RepositoryAdapter
from ..security import run_tool


class RpmRepositoryAdapter(RepositoryAdapter):
    def publish(self, generation: Path, repository: dict[str, Any], channel: str, packages: list[dict[str, Any]]) -> list[Path]:
        metadata: list[Path] = []
        for architecture in repository["architectures"]:
            target = generation / architecture
            package_dir = target / "Packages"
            package_dir.mkdir(parents=True, exist_ok=True)
            for package in packages:
                if package["architecture"] not in {architecture, "noarch"}:
                    continue
                self.link_package(package, package_dir / Path(package["relative_path"]).name)
            result = run_tool(["createrepo_c", "--database", str(target)], timeout=300)
            if result.returncode:
                raise RuntimeError(f"createrepo_c failed for {architecture}: {result.stderr}")
            metadata.append(target / "repodata" / "repomd.xml")
        return metadata
