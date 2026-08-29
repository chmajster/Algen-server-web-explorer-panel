from __future__ import annotations

import io
import shutil
import tarfile
import time
from pathlib import Path

import pytest

from app.modules.os_repositories.jobs import RepositoryJobManager
from app.modules.os_repositories.models import RepositoryInput, SnapshotInput
from app.modules.os_repositories.offline_jobs import OfflineRepositoryJobManager
from app.modules.os_repositories.offline_models import OfflineBundleType, OfflineExportInput, OfflineSettingsInput, OfflineTargetInput
from app.modules.os_repositories.offline_service import OfflineRepositoryService
from app.modules.os_repositories.service import RepositoryService


@pytest.fixture
def services(tmp_path: Path, monkeypatch):
    base = RepositoryService(tmp_path / "os-repositories")
    monkeypatch.setattr(base, "_audit", lambda *args, **kwargs: None)
    offline = OfflineRepositoryService(base)
    return base, offline


def repository_payload() -> RepositoryInput:
    return RepositoryInput(
        name="Ubuntu Offline",
        kind="local",
        format="apt",
        distribution="ubuntu",
        distribution_version="24.04",
        architectures=["amd64"],
    )


def upload_package(
    base: RepositoryService,
    monkeypatch,
    repository_id: str,
    *,
    filename: str,
    name: str,
    version: str = "1.0",
    dependencies: list[str] | None = None,
):
    metadata = {
        "name": name,
        "version": version,
        "release": "",
        "epoch": "",
        "architecture": "amd64",
        "maintainer": "WebNAS",
        "description": f"{name} test package",
        "dependencies": dependencies or [],
        "conflicts": [],
        "vendor": "",
        "license": "MIT",
    }
    monkeypatch.setattr(base, "_inspect_package", lambda _path, _expected: metadata)
    return base.upload_package(repository_id, filename, io.BytesIO(b"!<arch>\n" + f"{name}-{version}".encode()), "admin")


def wait_for_job(manager: OfflineRepositoryJobManager, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.job(job_id)
        if job and job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("offline job did not finish")


def test_offline_schema_targets_and_air_gap_settings(services):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    target = offline.save_target(
        OfflineTargetInput(
            name="Ubuntu production",
            repository_id=repository["id"],
            distribution="ubuntu",
            distribution_version="24.04",
            architecture="amd64",
            package_names=["nginx"],
        ),
        "admin",
    )
    assert target["include_dependencies"] is True
    assert offline.targets()[0]["id"] == target["id"]
    settings = offline.save_settings(OfflineSettingsInput(air_gapped_mode=True), "admin")
    assert settings["air_gapped_mode"] is True
    assert offline.dashboard()["air_gapped_mode"] is True


def test_air_gapped_mode_blocks_repository_sync(services):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    offline.save_settings(OfflineSettingsInput(air_gapped_mode=True), "admin")
    manager = RepositoryJobManager(base)
    try:
        with pytest.raises(ValueError, match="Air-Gapped Mode"):
            manager.enqueue_sync(repository["id"], "admin")
    finally:
        manager.pool.shutdown(wait=False, cancel_futures=True)


def test_dependency_closure_resolves_recursive_dependencies(services, monkeypatch):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    upload_package(base, monkeypatch, repository["id"], filename="libdemo.deb", name="libdemo")
    upload_package(base, monkeypatch, repository["id"], filename="demo.deb", name="demo", dependencies=["libdemo (>= 1.0)"])
    snapshot = base.create_snapshot(repository["id"], SnapshotInput(name="dependency-test"), "admin")
    result = offline.resolve_dependencies(snapshot["id"], "amd64", ["demo"])
    assert result["complete"] is True
    assert {item["name"] for item in result["packages"]} == {"demo", "libdemo"}


def test_dependency_closure_reports_missing_package(services, monkeypatch):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    upload_package(base, monkeypatch, repository["id"], filename="demo.deb", name="demo", dependencies=["missing-runtime >= 2"])
    snapshot = base.create_snapshot(repository["id"], SnapshotInput(name="missing-test"), "admin")
    result = offline.resolve_dependencies(snapshot["id"], "amd64", ["demo"])
    assert result["complete"] is False
    assert result["missing"] == ["missing-runtime >= 2"]


def test_full_bundle_round_trip_verification(services, monkeypatch):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    upload_package(base, monkeypatch, repository["id"], filename="libdemo.deb", name="libdemo")
    upload_package(base, monkeypatch, repository["id"], filename="demo.deb", name="demo", dependencies=["libdemo"])
    snapshot = base.create_snapshot(repository["id"], SnapshotInput(name="full-bundle"), "admin")
    bundle = offline.create_bundle(
        OfflineExportInput(
            repository_id=repository["id"],
            snapshot_id=snapshot["id"],
            architecture="amd64",
            bundle_type=OfflineBundleType.full,
            sign_manifest=False,
            confirm=True,
        ),
        "admin",
    )
    assert bundle["status"] == "ready"
    assert bundle["package_count"] == 2
    source = offline.bundle_path(bundle["id"])
    staged = offline.staging_root / source.name
    shutil.copy2(source, staged)
    staged_id = offline.discover_staged()[0]["id"]
    verification = offline.verify_staged(staged_id)
    assert verification["safe_to_import"] is True
    assert verification["files_total"] == verification["files_verified"]
    assert verification["packages_total"] == 2


def test_durable_export_job_uses_shared_repository_job_store(services, monkeypatch):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    upload_package(base, monkeypatch, repository["id"], filename="demo.deb", name="demo")
    snapshot = base.create_snapshot(repository["id"], SnapshotInput(name="durable-export"), "admin")
    manager = OfflineRepositoryJobManager(offline)
    try:
        queued = manager.enqueue_export(
            OfflineExportInput(
                repository_id=repository["id"],
                snapshot_id=snapshot["id"],
                architecture="amd64",
                bundle_type=OfflineBundleType.full,
                sign_manifest=False,
                confirm=True,
            ),
            "admin",
        )
        finished = wait_for_job(manager, queued["id"])
        assert finished["status"] == "completed", finished.get("error")
        assert finished["operation"] == "offline_export"
        assert offline.bundles()["total"] == 1
        assert RepositoryJobManager(base).job(finished["id"]) is None
    finally:
        manager.pool.shutdown(wait=False, cancel_futures=True)


def test_safe_extract_rejects_tar_traversal(services, tmp_path: Path):
    _base, offline = services
    archive = tmp_path / "malicious.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("escape", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(payload, arcname="../escape")
    destination = tmp_path / "extract"
    destination.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        offline._safe_extract(archive, destination)
    assert not (tmp_path / "escape").exists()


def test_delta_plan_and_snapshot_freeze(services, monkeypatch):
    base, offline = services
    repository = base.save_repository(repository_payload(), "admin")
    upload_package(base, monkeypatch, repository["id"], filename="demo-v1.deb", name="demo", version="1.0")
    first = base.create_snapshot(repository["id"], SnapshotInput(name="base"), "admin")
    upload_package(base, monkeypatch, repository["id"], filename="demo-v2.deb", name="demo", version="2.0")
    upload_package(base, monkeypatch, repository["id"], filename="new.deb", name="new", version="1.0")
    second = base.create_snapshot(repository["id"], SnapshotInput(name="target"), "admin")
    plan = offline.delta_plan(first["id"], second["id"], "amd64")
    assert plan["updated"] == 1
    assert plan["added"] == 1
    assert plan["delta_size_bytes"] < plan["full_size_bytes"]
    frozen = offline.freeze_snapshot(second["id"], "admin")
    repeated = offline.freeze_snapshot(second["id"], "admin")
    assert frozen["freeze"]["snapshot_id"] == second["id"]
    assert repeated["freeze"]["snapshot_id"] == second["id"]
