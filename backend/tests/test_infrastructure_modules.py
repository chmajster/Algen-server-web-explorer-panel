from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import rbac
from app.modules import router as module_router
from app.modules.providers.dns import PiHoleProvider
from app.modules.providers.docker import DockerProvider
from app.modules.providers.home_assistant import HomeAssistantProvider
from app.modules.providers.infrastructure import ApiConnectionProvider
from app.modules.providers.linux_updates import LinuxUpdatesProvider
from app.modules import linux_update_worker
from app.package_center.detached_updates import read_update_state, update_session_directory, write_update_state
from app.modules.providers.databases import RedisProvider
from app.package_center.manifests import discover_manifests
from app.package_center import executor as package_executor
from app.package_center.executor import redact
from app.package_center.models import PackageAction
from app.package_center.models import DistributionInfo, PackagePlan
from app.package_center.repository import PackageRepository
from app.security import SessionUser
from app.settings import DesktopWidget, UserSettings


NEW_MODULES = {"linux-updates", "docker", "pihole", "adguard-home", "postgresql", "mariadb", "redis", "home-assistant"}


def test_infrastructure_manifests_declare_only_supported_resources_and_actions():
    manifests = {manifest.id: manifest for manifest in discover_manifests()}

    assert NEW_MODULES <= manifests.keys()
    assert manifests["linux-updates"].capabilities.actions == ["refresh", "upgrade_all", "upgrade_security"]
    assert {"containers", "images", "networks", "volumes", "stats", "compose"} <= set(manifests["docker"].capabilities.resources)
    assert manifests["postgresql"].capabilities.backups is True
    assert manifests["home-assistant"].proxmox_safe is False


def test_rbac_preserves_linux_admin_and_gives_roles_granular_permissions(monkeypatch):
    assert "access.manage_roles" in rbac.ROLE_PERMISSIONS[rbac.Role.admin]
    assert "docker.manage_containers" in rbac.ROLE_PERMISSIONS[rbac.Role.operator]
    assert "access.manage_roles" not in rbac.ROLE_PERMISSIONS[rbac.Role.operator]
    assert "docker.view" in rbac.ROLE_PERMISSIONS[rbac.Role.auditor]
    assert "docker.manage_containers" not in rbac.ROLE_PERMISSIONS[rbac.Role.auditor]
    assert rbac.module_permission("postgresql", "restore") == "databases.restore"


def test_rbac_assignment_is_atomic_private_and_rejects_unknown_permission(monkeypatch, tmp_path: Path):
    path = tmp_path / "rbac.json"
    monkeypatch.setattr(rbac, "_path", lambda: path)
    assignment = rbac.RoleAssignment(username="alice", role="operator", allow=["audit.view"])

    rbac._write({"alice": assignment})

    assert rbac._read()["alice"] == assignment
    database = path.with_name("identity.sqlite3")
    assert database.is_file()
    if database.stat().st_mode:
        assert database.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        rbac.RoleAssignment(username="alice", allow=["system.reboot"])


def test_proxmox_safe_mode_blocks_provider_management(monkeypatch):
    monkeypatch.setattr(module_router, "get_module", lambda module_id: {"id": module_id, "blocked_by_proxmox": True})
    monkeypatch.setattr(module_router, "get_provider", lambda module_id, actor="root": SimpleNamespace(manifest=SimpleNamespace()))

    with pytest.raises(HTTPException) as error:
        module_router._provider_plan("docker", PackageAction.manage, {"operation": "container_start"})

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "MODULE_BLOCKED_BY_PROXMOX"


def test_linux_update_route_assigns_the_screen_session_server_side(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(module_router, "_authorize", lambda *args: None)
    monkeypatch.setattr(module_router, "get_provider", lambda *args: SimpleNamespace(manifest=SimpleNamespace(capabilities=SimpleNamespace(actions=["upgrade_security"]))))
    monkeypatch.setattr(module_router.secrets, "token_hex", lambda length: "0123456789abcdef01234567")
    monkeypatch.setattr(module_router, "_provider_plan", lambda module_id, action, payload: captured.update(payload) or payload)
    monkeypatch.setattr(module_router, "_enqueue", lambda plan, payload, user: plan)
    request = module_router.ModuleActionRequest(payload={"operation": "upgrade_all", "screen_session": "client-value"})

    result = module_router.module_management_action("linux-updates", "upgrade_security", request, SessionUser(username="operator", csrf_token="csrf"))

    assert result["operation"] == "upgrade_security"
    assert result["screen_session"] == "0123456789abcdef01234567"


def test_linux_updates_marks_security_packages_and_uses_closed_upgrade_command(monkeypatch):
    provider = LinuxUpdatesProvider("linux-updates")
    monkeypatch.setattr(provider, "_manager", lambda: "apt-get")
    monkeypatch.setattr(provider, "_reboot_required", lambda: True)
    calls: list[list[str]] = []
    simulation = "Inst openssl [3.0.1] (3.0.2 Debian-Security:12/stable-security [amd64])\nInst curl [8.0] (8.1 Debian:12/stable [amd64])\n"

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, simulation if "-s" in args else "updated", "")

    monkeypatch.setattr(provider, "_run", run)
    detached: list[list[str]] = []
    monkeypatch.setattr(provider, "_run_detached_update", lambda command, session_id, log, progress: detached.append(command) or {"detached": True, "screen_session": f"webnas-update-{session_id}"})
    packages = provider.list_resources("packages")["items"]
    result = provider.manage("upgrade_security", {}, "operator", lambda *_: None, lambda *_: None, lambda: False)

    assert packages[0]["security"] is True
    assert packages[1]["security"] is False
    assert detached == [["apt-get", "install", "--only-upgrade", "-y", "openssl"]]
    assert result["detached"] is True
    assert result["reboot_required"] is True


def test_linux_update_refresh_retries_without_unsubscribed_proxmox_enterprise(monkeypatch, tmp_path: Path):
    source_root = tmp_path / "apt"
    parts = source_root / "sources.list.d"
    parts.mkdir(parents=True)
    (source_root / "sources.list").write_text("deb http://deb.debian.org/debian bookworm main\n", encoding="utf-8")
    (parts / "pve-enterprise.list").write_text("deb https://enterprise.proxmox.com/debian/pve bookworm pve-enterprise\n", encoding="utf-8")
    monkeypatch.setattr(package_executor, "APT_SOURCES_ROOT", source_root)
    provider = LinuxUpdatesProvider("linux-updates")
    monkeypatch.setattr(provider, "_manager", lambda: "apt-get")
    monkeypatch.setattr(provider, "_packages", lambda: [])
    monkeypatch.setattr(provider, "_reboot_required", lambda: False)
    calls: list[list[str]] = []

    def run(args, **kwargs):
        calls.append(args)
        if args == ["apt-get", "update"]:
            return subprocess.CompletedProcess(args, 100, "", "E: https://enterprise.proxmox.com/debian/pve 401 Unauthorized")
        return subprocess.CompletedProcess(args, 0, "Metadata refreshed", "")

    monkeypatch.setattr(provider, "_run", run)
    logs: list[str] = []

    result = provider.manage("refresh", {}, "operator", lambda stream, line: logs.append(line), lambda *_: None, lambda: False)

    assert result["operation"] == "refresh"
    assert len(calls) == 2
    assert calls[1][0:2] == ["apt-get", "-o"]
    assert any("temporarily omitted" in line for line in logs)


def test_linux_update_launches_a_fixed_worker_in_detached_screen(monkeypatch, tmp_path: Path):
    provider = LinuxUpdatesProvider("linux-updates")
    captured: list[list[str]] = []

    def run(args, **kwargs):
        captured.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("app.modules.providers.linux_updates.subprocess.run", run)
    provider._launch_screen("/usr/bin/screen", "webnas-update-0123456789abcdef01234567", tmp_path, "0123456789abcdef01234567", ["apt-get", "upgrade", "-y"])

    command = captured[0]
    assert command[:3] == ["/usr/bin/screen", "-dmS", "webnas-update-0123456789abcdef01234567"]
    assert command[-4:] == ["--", "apt-get", "upgrade", "-y"]
    assert "linux_update_worker.py" in command[4]


def test_detached_update_worker_accepts_only_closed_commands_and_records_result(monkeypatch, tmp_path: Path):
    with pytest.raises(ValueError):
        linux_update_worker.validate_update_command(["apt-get", "upgrade", "-y", ";reboot"])
    with pytest.raises(ValueError):
        linux_update_worker.validate_update_command(["sh", "-c", "apt-get upgrade -y"])

    class Process:
        pid = 4321

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(linux_update_worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(linux_update_worker.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = linux_update_worker.run_update(tmp_path, "0123456789abcdef01234567", ["apt-get", "upgrade", "-y"])

    state = read_update_state(tmp_path)
    assert result == 0
    assert state and state["status"] == "completed"
    assert state["exit_code"] == 0
    assert (tmp_path / "output.log").is_file()


def test_linux_update_reconnects_to_finished_worker_without_starting_a_second_upgrade(monkeypatch, tmp_path: Path):
    session_id = "0123456789abcdef01234567"
    directory = update_session_directory(tmp_path, session_id)
    write_update_state(directory, {"session_id": session_id, "status": "completed", "exit_code": 0})
    provider = LinuxUpdatesProvider("linux-updates")
    monkeypatch.setattr(provider, "_manager", lambda: "apt-get")
    monkeypatch.setattr(provider, "_reboot_required", lambda: False)
    monkeypatch.setattr(provider, "_packages", lambda: [])
    monkeypatch.setattr(LinuxUpdatesProvider, "update_state_root", property(lambda self: tmp_path))
    monkeypatch.setattr(provider, "_launch_screen", lambda *args: pytest.fail("a recovered update must not launch a second package manager"))

    result = provider.manage("upgrade_security", {"screen_session": session_id}, "operator", lambda *_: None, lambda *_: None, lambda: False)

    assert result["detached"] is True
    assert result["screen_session"] == f"webnas-update-{session_id}"


def test_docker_resources_and_compose_validation_never_accept_host_control(monkeypatch):
    provider = DockerProvider("docker")
    output = json.dumps({"ID": "abc", "Names": "web", "State": "running"}) + "\n"
    monkeypatch.setattr(provider, "_docker", lambda args, timeout=60: output)

    assert provider.list_resources("containers")["items"][0]["Names"] == "web"
    valid = provider.validate_compose("services:\n  web:\n    image: nginx:stable\n    restart: unless-stopped\n")
    assert valid["services"]["web"]["image"] == "nginx:stable"
    with pytest.raises(HTTPException) as error:
        provider.validate_compose("services:\n  web:\n    image: nginx:stable\n    privileged: true\n")
    assert error.value.detail["code"] == "UNSAFE_COMPOSE"
    with pytest.raises(HTTPException):
        provider.validate_compose("services:\n  web:\n    image: nginx:stable\n    volumes: [/var/run/docker.sock:/var/run/docker.sock]\n")


def test_pihole_session_authentication_keeps_secret_out_of_public_configuration(monkeypatch):
    provider = PiHoleProvider("pihole")
    monkeypatch.setattr(provider, "connection", lambda: {"base_url": "http://127.0.0.1", "username": "", "secret": "application-password"})
    requests: list[tuple[str, str, dict | None, dict | None]] = []

    def request(path, *, method="GET", payload=None, headers=None, timeout=10):
        requests.append((path, method, payload, headers))
        if path == "/api/auth" and method == "POST":
            return {"session": {"valid": True, "sid": "session-id"}}
        return {"blocking": True}

    monkeypatch.setattr(provider, "_request", request)
    result = provider._api("/api/dns/blocking")

    assert result == {"blocking": True}
    assert requests[1][3] == {"X-FTL-SID": "session-id"}
    assert "application-password" not in json.dumps(provider.public_connection())


def test_redis_security_view_never_returns_password(monkeypatch):
    provider = RedisProvider("redis")
    values = {"maxmemory": "0", "maxmemory-policy": "noeviction", "protected-mode": "yes", "bind": "127.0.0.1", "aclfile": "", "requirepass": "top-secret"}
    monkeypatch.setattr(provider, "_config", lambda name: values[name])

    security = provider.list_resources("security")["items"][0]

    assert security["password_configured"] is True
    assert "top-secret" not in json.dumps(security)
    assert "requirepass" not in security


def test_home_assistant_backup_skips_symlinks(monkeypatch, tmp_path: Path):
    provider = HomeAssistantProvider("home-assistant")
    config = tmp_path / "config"
    config.mkdir()
    (config / "configuration.yaml").write_text("homeassistant:\n", encoding="utf-8")
    (config / "external").symlink_to(tmp_path / "outside", target_is_directory=True)
    monkeypatch.setattr(HomeAssistantProvider, "config_dir", property(lambda self: config))
    monkeypatch.setattr(HomeAssistantProvider, "backup_dir", property(lambda self: tmp_path / "backups"))
    (tmp_path / "backups").mkdir()
    monkeypatch.setattr(provider, "get_status", lambda: SimpleNamespace(package_version="stable"))

    backup = provider.create_backup("admin", "configuration")
    archive, _ = provider._backup_metadata(backup["id"])
    import tarfile

    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
    assert "configuration.yaml" in names
    assert "external" not in names


def test_widget_layout_has_closed_identifiers_ranges_and_unique_entries():
    settings = UserSettings()
    assert {item.id for item in settings.desktop_widgets} == {"cpu", "ram", "disks", "transfers", "services", "alerts"}
    with pytest.raises(ValueError):
        DesktopWidget(id="cpu", x=12, width=3)
    with pytest.raises(ValueError):
        UserSettings(desktop_widgets=[DesktopWidget(id="cpu"), DesktopWidget(id="cpu")])


def test_module_permission_dependency_rejects_auditor_mutation(monkeypatch):
    user = SessionUser(username="auditor", csrf_token="csrf")
    monkeypatch.setattr(rbac, "has_permission", lambda username, permission: permission.endswith(".view"))
    with pytest.raises(HTTPException) as error:
        rbac.authorize(user, rbac.module_permission("docker", "operate"))
    assert error.value.status_code == 403


def test_durable_module_actions_reject_secret_fields():
    with pytest.raises(ValueError):
        module_router.ModuleActionRequest(payload={"api_token": "must-not-enter-job"})


def test_module_api_connections_reject_public_ssrf_targets(monkeypatch):
    monkeypatch.setattr("app.modules.providers.infrastructure.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))])
    with pytest.raises(HTTPException) as error:
        ApiConnectionProvider._validate_base_url("https://public.example")
    assert error.value.detail["code"] == "API_HOST_NOT_PRIVATE"


def test_module_operation_name_is_preserved_in_shared_history(tmp_path: Path):
    repository = PackageRepository(tmp_path / "jobs.sqlite3")
    plan = PackagePlan(module_id="docker", action="manage", distribution=DistributionInfo(id="debian", name="Debian", architecture="x86_64", package_manager="apt-get"), compatible=True, payload={"operation": "container_restart", "target": "web"})
    job = repository.create_job(plan, "operator")
    repository.finish_history(job)
    assert repository.history()[0]["action"] == "container_restart"


def test_redaction_covers_database_and_registry_credentials():
    text = "postgres PASSWORD 'hunter2' registry=https://user:secret@example.test Authorization: Bearer abc.def"
    cleaned = redact(text)
    assert "hunter2" not in cleaned
    assert "user:secret" not in cleaned
    assert "abc.def" not in cleaned
