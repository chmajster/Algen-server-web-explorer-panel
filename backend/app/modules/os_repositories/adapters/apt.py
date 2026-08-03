from __future__ import annotations

import gzip
import hashlib
import time
from pathlib import Path
from typing import Any

from .base import RepositoryAdapter
from ..security import atomic_write


class AptRepositoryAdapter(RepositoryAdapter):
    def publish(self, generation: Path, repository: dict[str, Any], channel: str, packages: list[dict[str, Any]]) -> list[Path]:
        suite = repository["distribution_version"]
        component = "main"
        indexed: dict[str, list[str]] = {architecture: [] for architecture in repository["architectures"]}
        for package in packages:
            initial = package["name"][0].lower() if package["name"] else "_"
            filename = Path(package["relative_path"]).name
            relative = Path("pool") / component / initial / package["name"] / filename
            self.link_package(package, generation / relative)
            paragraph = (
                f"Package: {package['name']}\nVersion: {package['version']}\n"
                f"Architecture: {package['architecture']}\nFilename: {relative.as_posix()}\n"
                f"Size: {package['size_bytes']}\nSHA256: {package['sha256']}\n"
                f"Maintainer: {package['maintainer']}\nDescription: {package['description']}\n"
            )
            for architecture in indexed:
                if package["architecture"] in {architecture, "all"}:
                    indexed[architecture].append(paragraph)

        checksums: list[tuple[str, int, str]] = []
        for architecture, paragraphs in indexed.items():
            binary = generation / "dists" / suite / component / f"binary-{architecture}"
            data = "\n".join(paragraphs).encode("utf-8")
            plain = binary / "Packages"
            compressed = binary / "Packages.gz"
            atomic_write(plain, data, 0o644)
            atomic_write(compressed, gzip.compress(data, mtime=0), 0o644)
            for path in (plain, compressed):
                relative = path.relative_to(generation / "dists" / suite).as_posix()
                checksums.append((hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, relative))

        release = (
            f"Origin: WebNAS\nLabel: {repository['name']}\nSuite: {channel}\nCodename: {suite}\n"
            f"Date: {time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime())}\n"
            f"Architectures: {' '.join(repository['architectures'])}\nComponents: {component}\n"
            "Acquire-By-Hash: no\nSHA256:\n" + "".join(f" {digest} {size:16d} {name}\n" for digest, size, name in checksums)
        )
        release_path = generation / "dists" / suite / "Release"
        atomic_write(release_path, release.encode("utf-8"), 0o644)
        return [release_path]
