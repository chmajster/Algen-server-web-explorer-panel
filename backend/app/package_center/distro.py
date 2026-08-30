from __future__ import annotations

import platform
import shutil
from pathlib import Path

from .models import DistributionInfo, InstallationType, ModuleInstallation, ModuleManifest
from .package_managers import find_package_manager, normalize_package_manager

SUPPORTED_IDS = {"debian", "ubuntu", "raspbian", "fedora", "rhel", "rocky", "almalinux", "centos", "opensuse", "sles", "arch", "manjaro", "alpine", "proxmox"}


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
    manager: str | None = None
    if distro_id in {"debian", "ubuntu", "raspbian", "proxmox"} or "debian" in id_like:
        manager = find_package_manager(("apt-get",), shutil.which)
    elif distro_id in {"fedora", "rhel", "rocky", "almalinux", "centos"} or any(item in id_like for item in ("fedora", "rhel")):
        manager = find_package_manager(("dnf", "yum"), shutil.which)
    elif distro_id in {"opensuse", "sles"} or any(item in id_like for item in ("suse", "opensuse")):
        manager = find_package_manager(("zypper",), shutil.which)
    elif distro_id in {"arch", "manjaro"} or "arch" in id_like:
        manager = find_package_manager(("pacman",), shutil.which)
    elif distro_id == "alpine" or "alpine" in id_like:
        manager = find_package_manager(("apk",), shutil.which)
    return DistributionInfo(
        id=distro_id,
        name=values.get("PRETTY_NAME") or values.get("NAME") or distro_id,
        version_id=values.get("VERSION_ID", ""),
        id_like=id_like,
        architecture=platform.machine().lower(),
        package_manager=manager,
    )


def compatible(manifest: ModuleManifest, distro: DistributionInfo) -> bool:
    return compatibility_issue(manifest, distro) is None


def compatibility_issue(manifest: ModuleManifest, distro: DistributionInfo) -> str | None:
    distro_match = distro.id in manifest.supported_distributions or bool(set(distro.id_like) & set(manifest.supported_distributions))
    if not distro_match:
        return f"Distribution '{distro.id}' is not supported by module '{manifest.id}'"
    if distro.architecture not in manifest.supported_architectures:
        return f"Architecture '{distro.architecture}' is not supported by module '{manifest.id}'"
    # Package-less modules are repository-owned WebNAS features. Their lifecycle
    # only toggles Module Center state and must not require a host package manager
    # or a synthetic installation strategy.
    if manifest.package_less:
        return None
    if distro.package_manager is None:
        return "No supported package manager was detected on this system"
    installation = installation_for(manifest, distro)
    if installation is None:
        return f"Module '{manifest.id}' has no installation strategy for package manager '{distro.package_manager}'"
    if installation.type == InstallationType.unsupported:
        return installation.reason
    return None


def installation_for(manifest: ModuleManifest, distro: DistributionInfo) -> ModuleInstallation | None:
    manager = normalize_package_manager(distro.package_manager)
    return manifest.installations.get(manager) if manager else None


def packages_for(manifest: ModuleManifest, distro: DistributionInfo) -> list[str]:
    installation = installation_for(manifest, distro)
    return list(installation.packages) if installation and installation.type in {InstallationType.system_package, InstallationType.download_package} else []
