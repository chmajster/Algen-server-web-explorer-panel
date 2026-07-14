from __future__ import annotations

import platform
import shutil
from pathlib import Path

from .models import DistributionInfo, ModuleManifest

SUPPORTED_IDS = {"debian", "ubuntu", "raspbian", "fedora", "rhel", "rocky", "almalinux"}


def detect_distribution(path: Path = Path("/etc/os-release")) -> DistributionInfo:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, raw = line.split("=", 1)
            values[key] = raw.strip().strip('"\'')
    distro_id = values.get("ID", "unknown").lower()
    id_like = values.get("ID_LIKE", "").lower().split()
    manager = None
    if distro_id in {"debian", "ubuntu", "raspbian"} or "debian" in id_like:
        manager = "apt-get" if shutil.which("apt-get") else None
    elif distro_id in {"fedora", "rhel", "rocky", "almalinux"} or any(item in id_like for item in ("fedora", "rhel")):
        manager = "dnf" if shutil.which("dnf") else "yum" if shutil.which("yum") else None
    return DistributionInfo(
        id=distro_id,
        name=values.get("PRETTY_NAME") or values.get("NAME") or distro_id,
        version_id=values.get("VERSION_ID", ""),
        id_like=id_like,
        architecture=platform.machine().lower(),
        package_manager=manager,
    )


def compatible(manifest: ModuleManifest, distro: DistributionInfo) -> bool:
    distro_match = distro.id in manifest.supported_distributions or bool(set(distro.id_like) & set(manifest.supported_distributions))
    return distro_match and distro.architecture in manifest.supported_architectures and distro.package_manager is not None


def packages_for(manifest: ModuleManifest, distro: DistributionInfo) -> list[str]:
    return list(manifest.apt_packages if distro.package_manager == "apt-get" else manifest.dnf_packages)
