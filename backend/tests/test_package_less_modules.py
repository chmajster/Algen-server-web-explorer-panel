from app.package_center import service
from app.package_center.distro import compatibility_issue
from app.package_center.executor import command_preview
from app.package_center.jobs import _lifecycle_execution_plan
from app.package_center.manifests import load_manifest
from app.package_center.models import DistributionInfo, InstallationType, PackageAction, PackagePlan
from app.package_center.repository import PackageRepository


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


def test_package_less_module_with_declared_strategies_keeps_manager_compatibility_checks() -> None:
    manifest = load_manifest("apmid")
    distro = DistributionInfo(
        id="ubuntu",
        name="Ubuntu 26.04 LTS",
        version_id="26.04",
        id_like=["debian"],
        architecture="x86_64",
        package_manager="brew",
    )

    assert manifest.package_less is True
    assert manifest.installations
    assert compatibility_issue(manifest, distro) == "Module 'apmid' has no installation strategy for package manager 'brew'"


def test_strategy_less_package_less_execution_preserves_lifecycle_without_package_manager() -> None:
    manifest = load_manifest("proxmox-manager")
    plan = PackagePlan(
        module_id="proxmox-manager",
        action=PackageAction.uninstall,
        distribution=DistributionInfo(
            id="ubuntu",
            name="Ubuntu 26.04 LTS",
            version_id="26.04",
            id_like=["debian"],
            architecture="x86_64",
            package_manager="apt-get",
        ),
        compatible=True,
        packages=[],
        remove_data=True,
    )

    execution_plan = _lifecycle_execution_plan(plan, manifest)

    assert plan.installation_type is None
    assert execution_plan.installation_type == InstallationType.command
    assert execution_plan.distribution.package_manager is None
    assert execution_plan.remove_data is True
    assert command_preview(execution_plan, manifest) == []


def test_proxmox_manager_plan_contains_no_package_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service, "repository", lambda: PackageRepository(tmp_path / "proxmox-package-less.sqlite3"))
    monkeypatch.setattr(
        service,
        "detect_distribution",
        lambda: DistributionInfo(
            id="ubuntu",
            name="Ubuntu 26.04 LTS",
            version_id="26.04",
            id_like=["debian"],
            architecture="x86_64",
            package_manager="apt-get",
        ),
    )
    monkeypatch.setattr(service, "safe_mode_active", lambda: False)

    plan = service.plan_operation("proxmox-manager", PackageAction.install)

    assert plan.compatible is True
    assert plan.installation_type is None
    assert plan.packages == []
    assert plan.steps == []
