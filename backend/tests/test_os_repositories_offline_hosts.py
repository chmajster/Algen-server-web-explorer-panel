from __future__ import annotations

from pathlib import Path

from app.modules.os_repositories.models import RepositoryInput
from app.modules.os_repositories.offline_hosts import OfflineHostsIntegration
from app.modules.os_repositories.offline_models import OfflineHostGroupTargetInput
from app.modules.os_repositories.offline_service import OfflineRepositoryService
from app.modules.os_repositories.service import RepositoryService


class FakeHostsRegistry:
    def list_groups(self):
        return [{"id": "a" * 32, "name": "production-linux", "host_ids": ["host-ubuntu", "host-rocky"]}]

    def host(self, host_id: str):
        if host_id == "host-ubuntu":
            return {
                "id": host_id,
                "name": "ubuntu01",
                "distribution": "ubuntu",
                "system_version": "24.04",
                "facts": {"architecture": "x86_64"},
                "latest_report": {},
            }
        if host_id == "host-rocky":
            return {
                "id": host_id,
                "name": "rocky01",
                "distribution": "rocky",
                "system_version": "9.4",
                "facts": {"architecture": "x86_64"},
                "latest_report": {},
            }
        return None


def test_hosts_group_compatibility_and_target_generation(tmp_path: Path, monkeypatch):
    base = RepositoryService(tmp_path / "os-repositories")
    monkeypatch.setattr(base, "_audit", lambda *args, **kwargs: None)
    offline = OfflineRepositoryService(base)
    integration = OfflineHostsIntegration(offline)
    monkeypatch.setattr("app.modules.os_repositories.offline_hosts.hosts_registry", lambda: FakeHostsRegistry())

    ubuntu = base.save_repository(
        RepositoryInput(
            name="Ubuntu 24.04",
            kind="local",
            format="apt",
            distribution="ubuntu",
            distribution_version="24.04",
            architectures=["amd64"],
        ),
        "admin",
    )
    rocky = base.save_repository(
        RepositoryInput(
            name="Rocky 9",
            kind="local",
            format="rpm",
            distribution="rocky",
            distribution_version="9",
            architectures=["x86_64"],
        ),
        "admin",
    )

    compatibility = integration.compatibility("a" * 32, [ubuntu["id"], rocky["id"]])
    assert compatibility["total_hosts"] == 2
    assert compatibility["compatible_hosts"] == 2
    assert compatibility["incompatible_hosts"] == 0
    assert {item["architecture"] for item in compatibility["compatible"]} == {"x86_64"}

    result = integration.generate_targets(
        OfflineHostGroupTargetInput(
            host_group_id="a" * 32,
            repository_ids=[ubuntu["id"], rocky["id"]],
            name_prefix="Production",
            package_names=["curl"],
            confirm=True,
        ),
        "admin",
    )
    assert len(result["targets"]) == 2
    targets = {(item["distribution"], item["architecture"]): item for item in result["targets"]}
    assert ("ubuntu", "amd64") in targets
    assert ("rocky", "x86_64") in targets
    assert all(item["host_group_id"] == "a" * 32 for item in result["targets"])
