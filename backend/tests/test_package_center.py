from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from app import security as session_security
from app.package_center import distro, executor, jobs, manifests, security, service
from app.package_center.jobs import PackageJobManager
from app.package_center.detached_updates import update_session_directory, write_update_state
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


def test_detects_fedora_and_prefers_dnf(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text("ID=fedora\nID_LIKE=fedora\n", encoding="utf-8")
    monkeypatch.setattr(distro.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"dnf", "yum"} else None)

    result = distro.detect_distribution(release)

    assert result.id == "fedora"
    assert result.package_manager == "dnf"


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


@pytest.mark.parametrize("module_id", ["samba", "squid", "nginx", "syncthing"])
def test_every_production_module_builds_an_apt_plan(module_id, monkeypatch, tmp_path):
    repository = PackageRepository(tmp_path / f"{module_id}.sqlite3")
    monkeypatch.setattr(service, "repository", lambda: repository)
    monkeypatch.setattr(service, "detect_distribution", lambda: DistributionInfo(id="debian", name="Debian", architecture="x86_64", package_manager="apt-get"))
    monkeypatch.setattr(service, "safe_mode_active", lambda: False)

    result = service.plan_operation(module_id, PackageAction.install)

    assert result.compatible is True
    assert result.packages
    assert result.steps
    assert all("upgrade" not in step and "autoremove" not in step for step in result.steps)


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


def test_repository_preserves_running_detached_linux_update_for_reconnection(tmp_path):
    path = tmp_path / "packages.sqlite3"
    session_id = "0123456789abcdef01234567"
    detached_plan = plan("linux-updates", PackageAction.manage)
    detached_plan.payload = {"operation": "upgrade_security", "screen_session": session_id}
    first = PackageRepository(path)
    created = first.create_job(detached_plan, "operator")
    first.update_job(created["id"], status="running", started_at=1)
    write_update_state(update_session_directory(tmp_path, session_id), {"session_id": session_id, "status": "running", "pid": 123})

    second = PackageRepository(path)

    assert second.get_job(created["id"])["status"] == "running"


def test_running_detached_linux_update_cannot_be_cancelled_unsafely(monkeypatch, tmp_path):
    session_id = "0123456789abcdef01234567"
    detached_plan = plan("linux-updates", PackageAction.manage)
    detached_plan.payload = {"operation": "upgrade_all", "screen_session": session_id}
    repository = PackageRepository(tmp_path / "packages.sqlite3")
    created = repository.create_job(detached_plan, "operator")
    repository.update_job(created["id"], status="running", started_at=1)
    write_update_state(update_session_directory(tmp_path, session_id), {"session_id": session_id, "status": "running", "pid": 123})
    monkeypatch.setattr(PackageJobManager, "_run", lambda self, job_id: None)
    manager = PackageJobManager(repository)

    assert repository.get_job(created["id"])["cancellable"] is False
    with pytest.raises(HTTPException) as exc:
        manager.cancel(created["id"])

    assert exc.value.detail["code"] == "JOB_NOT_CANCELLABLE"


def test_retry_of_detached_linux_update_gets_a_fresh_screen_session(monkeypatch, tmp_path):
    original_session = "0123456789abcdef01234567"
    retry_session = "89abcdef0123456701234567"
    detached_plan = plan("linux-updates", PackageAction.manage)
    detached_plan.payload = {"operation": "upgrade_all", "screen_session": original_session}
    repository = PackageRepository(tmp_path / "packages.sqlite3")
    created = repository.create_job(detached_plan, "operator")
    repository.update_job(created["id"], status="failed", error="screen unavailable")
    manager = PackageJobManager(repository)
    monkeypatch.setattr(manager, "_schedule", lambda: None)
    monkeypatch.setattr("app.package_center.jobs.secrets.token_hex", lambda length: retry_session)

    retried = manager.retry(created["id"], "operator")

    assert retried["plan"]["payload"]["screen_session"] == retry_session
    assert retried["retry_of"] == created["id"]


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


def test_install_hook_runs_after_package_install_and_before_service_start(monkeypatch):
    calls: list[list[str]] = []
    package_plan = plan("syncthing")
    manifest = manifests.load_manifest("syncthing")
    monkeypatch.setattr(executor.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(executor, "_run", lambda args, timeout, log: calls.append(args))
    monkeypatch.setattr(executor, "_run_hook", lambda module, action, log: calls.append(["hook", action]))

    executor.execute(package_plan, manifest, lambda stream, line: None, lambda percent, step: None, lambda: False)

    install_index = next(index for index, args in enumerate(calls) if args[:2] == ["apt-get", "install"])
    hook_index = calls.index(["hook", "install"])
    start_index = next(index for index, args in enumerate(calls) if args[:2] == ["systemctl", "start"])
    assert install_index < hook_index < start_index


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


def test_samba_manifest_and_existing_renderer_remain_available():
    from app import apps

    manifest = manifests.load_manifest("samba")
    rendered = apps.render_smb_conf(apps.SambaConfig(shares=[apps.SambaShare(name="media", path="/srv/media")]))

    assert manifest.apt_packages == ["samba", "smbclient", "cifs-utils"]
    assert "cifs-utils" in manifest.dnf_packages
    assert "cifs-utils" in manifest.yum_packages
    assert "[media]" in rendered


def test_samba_can_report_that_configuration_is_required(monkeypatch):
    from app import apps

    monkeypatch.setattr(apps, "read_state", lambda app_id: {"installed": True, "configured": False})

    assert service.needs_configuration(manifests.load_manifest("samba"), {"version": "1.0.0"}) is True


def test_package_center_router_exposes_required_contract():
    from fastapi import FastAPI

    from app.package_center.router import router

    app = FastAPI()
    app.include_router(router)

    schema = app.openapi()
    routes = {(method.upper(), path) for path, operations in schema["paths"].items() for method in operations}
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


def test_package_install_route_checks_the_concrete_permission(monkeypatch):
    from app.identity.permissions import Permission
    from app.package_center import router as package_router
    from app.package_center.models import AdminPackageAction
    from app.security import SessionUser

    checked = []
    monkeypatch.setattr(package_router, "authorize", lambda user, permission: checked.append(permission))
    monkeypatch.setattr(package_router, "_enqueue_action", lambda module_id, action, payload, user: {"ok": True})

    result = package_router.install_module("samba", AdminPackageAction(confirm_plan=True), SessionUser(username="admin", csrf_token="csrf"))

    assert result == {"ok": True}
    assert checked == [Permission.MODULES_INSTALL]
