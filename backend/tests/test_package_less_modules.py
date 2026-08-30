from app.package_center.distro import compatibility_issue
from app.package_center.manifests import load_manifest
from app.package_center.models import DistributionInfo


def test_proxmox_manager_package_less_does_not_require_installation_strategy() -> None:
    manifest = load_manifest("proxmox-manager")
    distro = DistributionInfo(
        id="ubuntu",
        name="Ubuntu 26.04 LTS",
        version_id="26.04",
        id_like=["debian"],
        architecture="x86_64",
        package_manager="apt-get",
    )

    assert manifest.package_less is True
    assert manifest.installations == {}
    assert compatibility_issue(manifest, distro) is None


def test_proxmox_manager_package_less_does_not_require_package_manager() -> None:
    manifest = load_manifest("proxmox-manager")
    distro = DistributionInfo(
        id="ubuntu",
        name="Ubuntu 26.04 LTS",
        version_id="26.04",
        id_like=["debian"],
        architecture="x86_64",
        package_manager=None,
    )

    assert compatibility_issue(manifest, distro) is None
