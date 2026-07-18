from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.identity.models import Role
from app.identity.permissions import ROLE_PERMISSIONS
from app.modules.docker_manager.models import ComposeActionRequest, ComposeSaveRequest, ContainerActionRequest, ContainerCreateRequest, ContainerSettingsRequest, MountSpec, NetworkCreateRequest, RegistryRequest
from app.modules.docker_manager.router import PUBLIC_DOCKER_HUB
from app.modules.docker_manager.storage import DockerManagerStore
from app.modules import router as legacy_module_router
from app.modules.providers.container_apps import CONTAINER_APPS
from app.modules.providers.docker import DockerProvider
from app.modules.providers.home_assistant import HomeAssistantProvider
from app.modules.providers.dns import PiHoleProvider
from app.package_center.manifests import module_script
from app.security import SessionUser


def test_container_contract_rejects_high_risk_fields_and_socket_mounts():
    with pytest.raises(ValidationError):
        ContainerCreateRequest.model_validate({"name": "unsafe", "image": "nginx:stable", "network": "host", "privileged": True})
    with pytest.raises(ValidationError):
        ContainerCreateRequest.model_validate({"name": "unsafe", "image": "nginx:stable", "command": ["sh", "-c", "id"]})
    with pytest.raises(ValidationError):
        MountSpec(type="bind", source="/var/run/docker.sock", target="/var/run/docker.sock")
    with pytest.raises(ValidationError):
        ContainerActionRequest(action="kill", signal="SIGSTOP")
    with pytest.raises(ValidationError):
        ContainerCreateRequest.model_validate({"name": "duplicate-ports", "image": "nginx:stable", "ports": [{"published": 8080, "target": 80}, {"published": 8080, "target": 81}]})


def test_network_contract_rejects_system_names_and_conflicting_gateway():
    with pytest.raises(ValidationError):
        NetworkCreateRequest(name="bridge")
    with pytest.raises(ValidationError):
        NetworkCreateRequest(name="private", subnet="10.20.0.0/24", gateway="10.21.0.1")


def test_secret_contracts_preserve_spaces_and_reject_line_injection():
    request = ContainerCreateRequest(name="safe", image="nginx:stable", secret_environment={"PASSWORD": "  keep spaces  "})
    assert request.secret_environment["PASSWORD"] == "  keep spaces  "
    with pytest.raises(ValidationError):
        ContainerCreateRequest(name="unsafe", image="nginx:stable", environment={"VALUE": "first\nSECOND=injected"})
    with pytest.raises(ValidationError):
        ComposeSaveRequest(content="services: {}", secret_environment={"TOKEN": "one\r\ntwo"})
    with pytest.raises(ValidationError):
        RegistryRequest(name="hub", server="registry-1.docker.io", username="alice", password="token\nnext")
    with pytest.raises(ValidationError):
        RegistryRequest(name="hub", server="registry-1.docker.io", username="alice", password="token", ca_certificate="not-a-certificate")


def test_compose_scale_contract_is_typed_and_bounded():
    assert ComposeActionRequest(action="scale", scale={"web": 3}).scale == {"web": 3}
    with pytest.raises(ValidationError):
        ComposeActionRequest(action="scale", scale={})
    with pytest.raises(ValidationError):
        ComposeActionRequest(action="scale", scale={"web": 1001})


def test_container_settings_require_limits_and_a_published_port_selection():
    with pytest.raises(ValidationError):
        ContainerSettingsRequest(name="demo", resource_limits_enabled=True)
    with pytest.raises(ValidationError):
        ContainerSettingsRequest(name="demo", portal_enabled=True)


def test_public_docker_hub_is_the_builtin_anonymous_registry():
    assert PUBLIC_DOCKER_HUB == {
        "id": "docker-hub-public",
        "name": "Docker Hub",
        "provider": "docker_hub",
        "server": "docker.io",
        "username": "",
        "tls": True,
        "ca_certificate_configured": False,
        "secret_configured": False,
        "built_in": True,
        "public_access": True,
        "created_at": 0,
        "updated_at": 0,
    }


def test_private_store_never_returns_registry_password_and_consumes_inputs(tmp_path: Path):
    storage = DockerManagerStore(tmp_path / "docker")
    saved = storage.save_registry(registry_id=None, name="ghcr", provider="ghcr", server="ghcr.io", username="alice", password="private-value")

    assert "password" not in saved
    assert "private-value" not in json.dumps(storage.list_registries())
    assert b"private-value" not in storage.path.read_bytes()
    assert storage.registry_credentials(saved["id"])["password"] == "private-value"
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3

    preferences = storage.save_container_preferences("sha256:container", portal_enabled=True, portal_protocol="https", portal_port=8096)
    assert preferences["portal_enabled"] == 1
    assert storage.container_preferences("sha256:container")["portal_port"] == 8096

    token = storage.stage_input({"environment": {"APP_PASSWORD": "one-time"}})
    assert storage.consume_input(token)["environment"]["APP_PASSWORD"] == "one-time"
    with pytest.raises(RuntimeError):
        storage.consume_input(token)


def test_registry_v1_migration_moves_plaintext_credential_to_private_store(tmp_path: Path):
    root = tmp_path / "docker"
    root.mkdir()
    database = root / "manager.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE registries (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, provider TEXT NOT NULL,
                server TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            INSERT INTO registries VALUES ('0123456789abcdef01234567','hub','docker_hub','registry-1.docker.io','alice','legacy-secret',1,1);
            PRAGMA user_version=1;
            """
        )

    storage = DockerManagerStore(root)

    assert storage.registry_credentials("0123456789abcdef01234567")["password"] == "legacy-secret"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT password FROM registries").fetchone()[0] == ""
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert all(b"legacy-secret" not in path.read_bytes() for path in root.glob("manager.sqlite3*"))


def test_docker_catalog_contains_required_versioned_templates():
    ids = {item.id for item in CONTAINER_APPS}
    assert {"pihole", "adguard-home", "home-assistant", "uptime-kuma", "nginx-proxy-manager", "jellyfin", "syncthing", "nextcloud", "mariadb-container", "postgresql-container", "redis-container"} <= ids
    assert len(CONTAINER_APPS) >= 11
    assert all(item.version and item.image and item.container for item in CONTAINER_APPS)
    assert all(item.architectures and item.healthcheck and item.documentation_url for item in CONTAINER_APPS)


def test_compose_policy_rejects_executable_and_privileged_fields():
    provider = DockerProvider("alice")
    for field, value in (("command", ["sh", "-c", "id"]), ("entrypoint", "/bin/sh"), ("privileged", True), ("devices", ["/dev/sda"])):
        content = f"services:\n  app:\n    image: nginx:stable\n    {field}: {json.dumps(value)}\n"
        with pytest.raises(Exception):
            provider.validate_compose(content)
    with pytest.raises(Exception):
        provider.validate_compose("services:\n  app:\n    image: nginx:stable\n    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n")


def test_daemon_policy_allows_bounded_settings_and_rejects_remote_or_arbitrary_configuration():
    assert DockerProvider._daemon_policy_errors({"log-driver": "local", "log-opts": {"max-size": "10m", "max-file": "3"}, "live-restore": True}) == []
    assert DockerProvider._daemon_policy_errors({"data-root": "/tmp/docker"})
    assert DockerProvider._daemon_policy_errors({"insecure-registries": ["0.0.0.0/0"]})
    assert DockerProvider._daemon_policy_errors({"registry-mirrors": ["http://user:password@example.test"]})


def test_compose_edit_preserves_unsubmitted_secret_environment(monkeypatch, tmp_path: Path):
    provider = DockerProvider("alice")
    monkeypatch.setattr(DockerProvider, "compose_dir", property(lambda self: tmp_path))
    content = "services:\n  app:\n    image: nginx:stable\n"
    provider.save_compose("demo", content, secret_environment={"PASSWORD": "private"}, actor="alice")
    provider.save_compose("demo", content, environment={"MODE": "prod"}, actor="alice")

    assert (tmp_path / "demo" / ".env.secrets").read_text(encoding="utf-8") == "PASSWORD=private\n"
    assert provider.get_compose("demo")["secrets_configured"] is True


def test_registry_search_uses_fixed_docker_cli_arguments(monkeypatch):
    captured = []
    provider = DockerProvider("alice")

    def run(args, *, timeout=30, input_text=None, env=None):
        captured.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps({"Name": "library/nginx", "Description": "web", "StarCount": "5", "IsOfficial": "true"}) + "\n", "")

    monkeypatch.setattr(provider, "_run", run)
    result = provider.search_registry("nginx", 10)
    assert captured == [["docker", "search", "--limit", "10", "--format", "{{json .}}", "nginx"]]
    assert result["items"][0]["repository"] == "library/nginx"
    with pytest.raises(Exception):
        DockerProvider("alice").search_registry("$(id)", 10)


def test_container_creation_uses_env_file_and_fixed_argument_array(monkeypatch, tmp_path: Path):
    provider = DockerProvider("alice")
    storage = DockerManagerStore(tmp_path / "manager")
    monkeypatch.setattr(DockerProvider, "manager_store", property(lambda self: storage))
    monkeypatch.setattr(provider, "_inspect_container", lambda name: None)
    monkeypatch.setattr(provider, "container_details", lambda name: {"name": name, "state": {"Status": "running"}})
    calls: list[tuple[list[str], str | None]] = []

    def run(args, *, timeout=30, input_text=None, env=None):
        calls.append((list(args), input_text))
        return subprocess.CompletedProcess(args, 0, "container-id\n", "")

    monkeypatch.setattr(provider, "_run", run)
    definition = ContainerCreateRequest(
        name="safe-app", image="nginx:stable", pull_policy="never", environment={"MODE": "prod"}, secret_environment={},
        network="private-net", network_aliases=["web"], hostname="safe-web", working_dir="/app", user="1000:1000",
        mounts=[{"type": "volume", "source": "safe-data", "target": "/data"}, {"type": "tmpfs", "target": "/tmp", "tmpfs_size_mb": 64}],
        limits={"cpus": 1.5, "memory_mb": 256, "memory_swap_mb": 512, "pids": 128},
        healthcheck={"type": "tcp", "port": 8080}, confirmation="safe-app",
    ).model_dump(mode="json", exclude={"secret_environment", "confirmation"})
    provider._run_container(definition, {"APP_PASSWORD": "private-value"}, lambda *_: None)

    docker_run = next(args for args, _ in calls if args[:2] == ["docker", "run"])
    assert "--env-file" in docker_run
    assert "private-value" not in docker_run
    assert not {"--privileged", "--pid", "--ipc", "--device", "--cap-add"} & set(docker_run)
    assert docker_run[docker_run.index("--network-alias") + 1] == "web"
    assert docker_run[docker_run.index("--hostname") + 1] == "safe-web"
    assert docker_run[docker_run.index("--user") + 1] == "1000:1000"
    assert "--health-cmd" in docker_run and "--pids-limit" in docker_run and docker_run.count("--mount") == 2
    assert all(input_text is None for _, input_text in calls)
    assert not list(storage.inputs_dir.glob("env-*.list"))


def test_running_container_settings_use_typed_docker_update_and_store_portal(monkeypatch, tmp_path: Path):
    provider = DockerProvider("alice")
    storage = DockerManagerStore(tmp_path / "manager")
    monkeypatch.setattr(DockerProvider, "manager_store", property(lambda self: storage))
    inspect = {
        "Id": "sha256:demo", "Name": "/demo", "Config": {"Labels": {}, "Image": "jellyfin:latest"},
        "HostConfig": {"PortBindings": {"8096/tcp": [{"HostIp": "", "HostPort": "8096"}]}, "RestartPolicy": {"Name": "no"}},
    }
    monkeypatch.setattr(provider, "_inspect", lambda kind, target: inspect)
    monkeypatch.setattr(provider, "_inspect_container", lambda name: None)
    monkeypatch.setattr(provider, "container_settings", lambda name: {"name": name})
    monkeypatch.setattr(provider, "container_details", lambda name: {"name": name})
    calls: list[list[str]] = []
    monkeypatch.setattr(provider, "_run", lambda args, timeout=30, input_text=None, env=None: calls.append(list(args)) or subprocess.CompletedProcess(args, 0, "", ""))

    result = provider.update_container_settings("demo", {
        "name": "media", "resource_limits_enabled": True, "cpu_priority": "high", "memory_mb": 4096,
        "auto_restart": True, "portal_enabled": True, "portal_port": 8096, "portal_protocol": "http",
    })

    update = calls[0]
    assert update[:2] == ["docker", "update"]
    assert update[update.index("--cpu-shares") + 1] == "2048"
    assert update[update.index("--memory") + 1] == "4096m"
    assert update[update.index("--restart") + 1] == "unless-stopped"
    assert calls[1] == ["docker", "rename", "demo", "media"]
    assert storage.container_preferences("sha256:demo")["portal_port"] == 8096
    assert result["container"]["name"] == "media"


def test_granular_docker_permissions_keep_high_risk_admin_only():
    operator = ROLE_PERMISSIONS[Role.operator]
    auditor = ROLE_PERMISSIONS[Role.auditor]
    assert "docker.create_container" in operator
    assert "docker.pull_image" in operator
    assert "docker.prune" not in operator
    assert "docker.high_risk" not in operator
    assert "docker.view_containers" in auditor
    assert "docker.create_container" not in auditor


def test_official_repository_prepare_and_health_hooks_are_bundled():
    assert module_script("docker", "prepare") is not None
    assert module_script("docker", "health") is not None
    assert module_script("docker", "rollback") is not None


def test_home_assistant_catalog_install_uses_bridge_and_published_port(monkeypatch, tmp_path: Path):
    provider = HomeAssistantProvider("home-assistant")
    calls: list[list[str]] = []
    monkeypatch.setattr(HomeAssistantProvider, "config_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(provider, "_docker", lambda args, timeout=120: calls.append(list(args)) or "")

    provider._run_container(provider.image, "Europe/Warsaw")

    command = calls[0]
    assert command[command.index("--network") + 1] == "bridge"
    assert command[command.index("-p") + 1] == "8123:8123/tcp"
    assert "host" not in command


def test_pihole_catalog_uses_typed_ports_network_and_password_file(monkeypatch, tmp_path: Path):
    provider = PiHoleProvider("pihole")
    calls: list[list[str]] = []
    monkeypatch.setattr(PiHoleProvider, "container_data_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(provider, "connection", lambda: {"secret": "private-password"})
    monkeypatch.setattr(provider, "_docker", lambda args, timeout=180: calls.append(list(args)) or "")

    provider._run_container("pihole/pihole:latest", "Europe/Warsaw", {"hostname": "dns-home", "panel_port": 9080, "dns_port": 5353, "network": "dns-net"})

    command = calls[0]
    assert command[command.index("--hostname") + 1] == "dns-home"
    assert command[command.index("--network") + 1] == "dns-net"
    assert "9080:80/tcp" in command and "5353:53/tcp" in command and "5353:53/udp" in command
    assert "private-password" not in command
    assert "--health-cmd" in command


def test_compose_runtime_validation_uses_private_temporary_environment(monkeypatch, tmp_path: Path):
    provider = DockerProvider("docker")
    storage = DockerManagerStore(tmp_path / "manager")
    monkeypatch.setattr(DockerProvider, "manager_store", property(lambda self: storage))
    monkeypatch.setattr(provider, "_compose_tool", lambda: ["docker", "compose"])
    captured: list[list[str]] = []

    def run(args, *, timeout=30, input_text=None, env=None):
        captured.append(list(args))
        env_path = Path(args[args.index("--env-file") + 1])
        assert env_path.read_text(encoding="utf-8") == "MODE=prod\nPASSWORD=private\n"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(provider, "_run", run)
    result = provider.validate_compose_runtime("services:\n  app:\n    image: nginx:stable\n", environment={"MODE": "prod"}, secret_environment={"PASSWORD": "private"})

    assert result["valid"] is True
    assert "private" not in json.dumps(captured)
    assert not list(storage.inputs_dir.glob("compose-validate-*"))


def test_docker_manager_routes_are_registered():
    from app.modules.docker_manager.router import router

    paths = {route.path for route in router.routes if hasattr(route, "path")}
    assert "/api/modules/docker/dashboard" in paths
    assert "/api/modules/docker/containers" in paths
    assert "/api/modules/docker/containers/import" in paths
    assert "/api/modules/docker/containers/{target}/actions" in paths
    assert "/api/modules/docker/images/actions" in paths
    assert "/api/modules/docker/images/search" in paths
    assert "/api/modules/docker/compose/{project}" in paths
    assert "/api/modules/docker/compose/{project}/history/{revision}/rollback" in paths
    assert "/api/modules/docker/compose/{project}/status" in paths
    assert "/api/modules/docker/compose/{project}/logs" in paths
    assert "/api/modules/docker/backups/{backup_id}/restore" in paths
    assert "/api/modules/docker/diagnostics" in paths


def test_legacy_module_mutations_cannot_bypass_typed_docker_api():
    user = SessionUser(username="admin", csrf_token="csrf")
    calls = (
        lambda: legacy_module_router.module_management_action(
            "docker", "container_start", legacy_module_router.ModuleActionRequest(payload={"target": "demo"}), user
        ),
        lambda: legacy_module_router.module_service_action("docker", "restart", legacy_module_router.ModuleAdminRequest(), user),
        lambda: legacy_module_router.module_apply(
            "docker", legacy_module_router.ModuleApplyRequest(config={"live-restore": True}), user
        ),
        lambda: legacy_module_router.save_docker_compose(
            "demo", legacy_module_router.ComposeSaveRequest(content="services: {}"), user
        ),
    )
    for call in calls:
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "TYPED_DOCKER_API_REQUIRED"


def test_inspect_response_omits_environment_values(monkeypatch):
    provider = DockerProvider("alice")
    monkeypatch.setattr(provider, "_inspect", lambda kind, target: {
        "Id": "abc", "Name": "/demo", "Config": {"Image": "demo:1", "Env": ["APP_PASSWORD=private-value", "MODE=prod"], "Labels": {}},
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}}, "State": {"Status": "running"}, "NetworkSettings": {}, "Mounts": [],
    })
    result = provider.container_details("demo")
    encoded = json.dumps(result)
    assert result["environment_keys"] == ["APP_PASSWORD", "MODE"]
    assert "private-value" not in encoded
    assert "MODE=prod" not in encoded


def test_container_settings_offer_only_real_published_ports(monkeypatch, tmp_path: Path):
    provider = DockerProvider("alice")
    storage = DockerManagerStore(tmp_path / "manager")
    monkeypatch.setattr(DockerProvider, "manager_store", property(lambda self: storage))
    monkeypatch.setattr(provider, "_inspect", lambda kind, target: {
        "Id": "abc", "Name": "/media", "Config": {"Labels": {"com.docker.compose.project": "jellyfin"}},
        "HostConfig": {"CpuShares": 2048, "Memory": 4096 * 1024 * 1024, "RestartPolicy": {"Name": "unless-stopped"}, "PortBindings": {"8096/tcp": [{"HostIp": "", "HostPort": "18096"}], "1900/udp": None}},
    })
    storage.save_container_preferences("abc", portal_enabled=True, portal_protocol="http", portal_port=8096)

    result = provider.container_settings("media")

    assert result["cpu_priority"] == "high" and result["memory_mb"] == 4096
    assert result["portal_enabled"] is True and result["portal_published_port"] == 18096
    assert result["available_ports"] == [{"target": 8096, "published": 18096, "protocol": "tcp", "host_ip": None}]
    assert result["compose_managed"] is True
