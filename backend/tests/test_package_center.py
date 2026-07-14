from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from app import security as session_security
from app.package_center import distro, executor, jobs, manifests, security, service
from app.package_center.jobs import PackageJobManager
from app.package_center.models import DistributionInfo, ModuleManifest, PackageAction, PackagePlan, PackageSourceInput
from app.package_center.repository import PackageRepository


def plan(module_id: str = "nginx", action: PackageAction = PackageAction.install) -> PackagePlan:
    return PackagePlan(
        module_id=module_id,
        action=action,
        distribution=DistributionInfo(id="debian", name="Debian", architecture="x86_64", package_manager="apt-get"),
        compatible=True,
        packages=[module_id],
        services=[module_id],
        target_version="1.0.0",
        steps=[f"apt-get install -y {module_id}"],
    )


def test_discovers_four_valid_production_manifests_and_hides_example():
    found = {item.id: item for item in manifests.discover_manifests()}

    assert {"samba", "squid", "nginx", "syncthing"} <= set(found)
    assert "example" not in found
    assert found["samba"].category == "file_sharing"


def test_manifest_rejects_invalid_identifier_and_package():
    with pytest.raises(ValueError):
        ModuleManifest(id="../bad", name="Bad", description="Bad", version="1", apt_packages=["bad;command"])


def test_module_directory_rejects_path_traversal(tmp_path):
    with pytest.raises(HTTPException) as exc:
        manifests.module_directory("../outside", tmp_path)

    assert exc.value.detail["code"] == "INVALID_MODULE_ID"


def test_detects_debian_and_selects_apt(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text('ID=ubuntu\nID_LIKE="debian"\nPRETTY_NAME="Ubuntu Test"\nVERSION_ID="24.04"\n', encoding="utf-8")
    monkeypatch.setattr(distro.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "apt-get" else None)
    monkeypatch.setattr(distro.platform, "machine", lambda: "x86_64")

    result = distro.detect_distribution(release)

    assert result.id == "ubuntu"
    assert result.package_manager == "apt-get"


def test_detects_rocky_and_falls_back_to_yum(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=rocky\nID_LIKE=\"rhel fedora\"\n", encoding="utf-8")
    monkeypatch.setattr(distro.shutil, "which", lambda name: "/usr/bin/yum" if name == "yum" else None)
    monkeypatch.setattr(distro.platform, "machine", lambda: "aarch64")

    result = distro.detect_distribution(release)

    assert result.package_manager == "yum"
    assert result.architecture == "aarch64"


def test_dry_run_contains_packages_services_and_safe_commands(monkeypatch, tmp_path):
    repository = PackageRepository(tmp_path / "packages.sqlite3")
    monkeypatch.setattr(service, "repository", lambda: repository)
    monkeypatch.setattr(service, "detect_distribution", lambda: DistributionInfo(id="debian", name="Debian", architecture="x86_64", package_manager="apt-get"))
    monkeypatch.setattr(service, "safe_mode_active", lambda: False)

    result = service.plan_operation("nginx", PackageAction.install)

    assert result.packages == ["nginx"]
    assert result.services == ["nginx"]
    assert any(step.startswith("apt-get install") for step in result.steps)
    assert not any("upgrade" in step or "autoremove" in step for step in result.steps)


def test_plan_blocks_unsafe_module_in_proxmox_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "repository", lambda: PackageRepository(tmp_path / "packages.sqlite3"))
    monkeypatch.setattr(service, "safe_mode_active", lambda: True)

    with pytest.raises(HTTPException) as exc:
        service.plan_operation("nginx", PackageAction.install)

    assert exc.value.detail["code"] == "MODULE_BLOCKED_BY_PROXMOX"


def test_repository_persists_history_and_recovers_interrupted_job(tmp_path):
    path = tmp_path / "packages.sqlite3"
    first = PackageRepository(path)
    created = first.create_job(plan(), "alice")
    first.update_job(created["id"], status="running", started_at=1)

    second = PackageRepository(path)
    recovered = second.get_job(created["id"])

    assert recovered["status"] == "failed"
    assert "interrupted" in recovered["error"].lower()
    assert second.history()[0]["job_id"] == created["id"]


def test_repository_persists_and_updates_package_sources(tmp_path):
    path = tmp_path / "packages.sqlite3"
    first = PackageRepository(path)
    created = first.create_source(PackageSourceInput(name="Community", github_url="https://github.com/example/packages", branch="main"))
    updated = first.update_source(created["id"], PackageSourceInput(name="Community stable", github_url="https://github.com/example/packages", branch="stable", enabled=False))

    second = PackageRepository(path)
    sources = second.list_sources()

    assert updated is not None
    assert sources[0]["name"] == "Community stable"
    assert sources[0]["branch"] == "stable"
    assert sources[0]["enabled"] is False


def test_blocks_two_jobs_for_the_same_module(monkeypatch, tmp_path):
    manager = PackageJobManager(PackageRepository(tmp_path / "packages.sqlite3"))
    monkeypatch.setattr(manager, "_schedule", lambda: None)
    manager.enqueue(plan(), "alice")

    with pytest.raises(HTTPException) as exc:
        manager.enqueue(plan(), "alice")

    assert exc.value.detail["code"] == "JOB_ALREADY_RUNNING"


def test_cancel_and_retry_create_durable_jobs(monkeypatch, tmp_path):
    manager = PackageJobManager(PackageRepository(tmp_path / "packages.sqlite3"))
    monkeypatch.setattr(manager, "_schedule", lambda: None)
    original = manager.enqueue(plan(), "alice")
    cancelled = manager.cancel(original["id"])
    retried = manager.retry(original["id"], "alice")

    assert cancelled["status"] == "cancelled"
    assert retried["retry_of"] == original["id"]
    assert retried["status"] == "queued"


def test_generic_job_marks_module_installed(monkeypatch, tmp_path):
    repository = PackageRepository(tmp_path / "packages.sqlite3")
    manager = PackageJobManager(repository)
    created = repository.create_job(plan(), "alice")
    monkeypatch.setattr(jobs, "execute", lambda package_plan, manifest, log, progress, cancelled: progress(100, "Completed"))

    manager._run(created["id"])

    assert repository.get_job(created["id"])["status"] == "completed"
    assert repository.installed()["nginx"]["version"] == "1.0.0"


def test_redacts_secrets_and_executor_never_uses_shell_true():
    assert "secret=[REDACTED]" in executor.redact("secret=hunter2")
    assert "password: [REDACTED]" in executor.redact("password: admin")
    assert "shell=True" not in inspect.getsource(executor)


def test_package_admin_dependency_requires_admin(monkeypatch):
    monkeypatch.setattr(security, "get_session_user", lambda request: SimpleNamespace(username="alice", csrf_token="token"))
    monkeypatch.setattr(security, "is_admin", lambda username: False)

    with pytest.raises(HTTPException) as exc:
        security.current_admin(Request({"type": "http", "method": "GET", "path": "/", "headers": []}))

    assert exc.value.status_code == 403


def test_package_mutation_requires_csrf(monkeypatch):
    response = Response()
    csrf = session_security.create_session(response, "alice")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    headers = [(b"cookie", cookie.encode("latin-1"))]
    monkeypatch.setattr(security, "is_admin", lambda username: True)

    with pytest.raises(HTTPException) as exc:
        security.mutating_admin(Request({"type": "http", "method": "POST", "path": "/", "headers": headers}))

    assert exc.value.status_code == 403
    headers.append((b"x-csrf-token", csrf.encode("latin-1")))
    assert security.mutating_admin(Request({"type": "http", "method": "POST", "path": "/", "headers": headers})).username == "alice"


def test_reauthentication_maps_pam_failure(monkeypatch):
    monkeypatch.setattr(security, "authenticate", lambda username, password: (_ for _ in ()).throw(HTTPException(401, "bad")))

    with pytest.raises(HTTPException) as exc:
        security.reauthenticate(SimpleNamespace(username="alice"), "bad")

    assert exc.value.detail["code"] == "AUTHENTICATION_FAILED"


def test_samba_manifest_and_existing_renderer_remain_available():
    from app import apps

    manifest = manifests.load_manifest("samba")
    rendered = apps.render_smb_conf(apps.SambaConfig(shares=[apps.SambaShare(name="media", path="/srv/media")]))

    assert manifest.apt_packages == ["samba", "smbclient"]
    assert "[media]" in rendered


def test_package_center_router_exposes_required_contract():
    from app.main import app

    routes = {(method, route.path) for route in app.routes for method in getattr(route, "methods", set())}
    required = {
        ("GET", "/api/apps"),
        ("GET", "/api/apps/categories"),
        ("GET", "/api/apps/installed"),
        ("GET", "/api/apps/updates"),
        ("GET", "/api/apps/jobs"),
        ("GET", "/api/apps/history"),
        ("GET", "/api/apps/sources"),
        ("POST", "/api/apps/{module_id}/plan"),
        ("POST", "/api/apps/{module_id}/install"),
        ("POST", "/api/apps/{module_id}/update"),
        ("POST", "/api/apps/{module_id}/uninstall"),
        ("POST", "/api/apps/{module_id}/start"),
        ("POST", "/api/apps/{module_id}/stop"),
        ("POST", "/api/apps/{module_id}/restart"),
    }

    assert required <= routes
