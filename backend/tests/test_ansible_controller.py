from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.identity.permissions import ALL_PERMISSIONS, Permission
from app.identity import permissions as identity_permissions
from app.modules.ansible_controller import router as ansible_router
from app.modules.ansible_controller.awx import AwxClient
from app.modules.ansible_controller.backup import create_backup, restore_backup, validate_backup
from app.modules.ansible_controller.inventory import generate_inventory, parse_inventory, validation_commands as inventory_validation_commands
from app.modules.ansible_controller.models import (
    AwxSettingsInput,
    CredentialInput,
    CredentialType,
    HostInput,
    ManagedAccountConfigInput,
    NetworkScanInput,
    OnboardingInput,
    PlaybookInput,
    ProjectInput,
    ScheduleInput,
)
from app.modules.ansible_controller.network import build_nmap_args, parse_nmap_xml, scan_addresses
from app.modules.ansible_controller.playbooks import analyze_playbook, build_ansible_playbook_args, safe_project_path, validation_commands as playbook_validation_commands
from app.modules.ansible_controller.repository import AnsibleRepository
from app.modules.ansible_controller.runner import build_managed_user_script, build_ssh_args, demote_preexec, parse_recap
from app.modules.ansible_controller.scheduler import next_run
from app.modules.ansible_controller.security import CredentialCipher, redact, redact_text
from app.modules.providers import get_provider
from app.modules.providers.ansible_controller import _generate_host_key, _run_cancellable
from app.package_center.manifests import load_manifest
from app.security import SessionUser


def store(tmp_path: Path) -> AnsibleRepository:
    return AnsibleRepository(tmp_path / "controller.sqlite3", tmp_path / "controller.key")


def test_manifest_is_searchable_and_uses_distribution_packages():
    manifest = load_manifest("ansible-controller")

    assert manifest.name == "Ansible Automation Controller"
    assert "Ansible Tower" in manifest.description
    assert "AWX" in manifest.description
    assert {"ansible-core", "openssh-client", "nmap", "git", "python3-venv"} <= set(manifest.packages.apt)
    assert {"ansible-core", "openssh-clients", "nmap", "git"} <= set(manifest.packages.dnf)
    assert manifest.requires_root is True
    assert manifest.proxmox_safe is False
    assert manifest.ports == []
    assert "/var/lib/webnas/secrets/ansible-controller.key" in manifest.data_paths


def test_migration_creates_logically_separated_tables(tmp_path: Path):
    repository = store(tmp_path)
    with repository.connect() as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert {"hosts", "inventory_groups", "host_group_memberships", "host_variables", "group_variables", "credentials", "projects", "playbooks", "job_templates", "schedules", "executions", "host_results", "saved_facts", "network_scans", "controller_audit_events", "known_host_keys"} <= names
    assert version >= 1


def test_credential_is_authenticated_encrypted_and_never_returned(tmp_path: Path):
    repository = store(tmp_path)
    private_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nQUJDREVGRw==\n-----END OPENSSH PRIVATE KEY-----"
    created = repository.save_credential(CredentialInput(name="Host key", type=CredentialType.ssh_private_key, secret=private_key, passphrase="key-pass"), "admin")
    raw = repository._get("credentials", created["id"])

    assert "secret" not in created
    assert created["secret_configured"] is True
    assert raw is not None and "OPENSSH PRIVATE KEY" not in raw["encrypted_secret"]
    assert repository.credential_secret(created["id"])["secret"] == private_key
    assert repository.credential_secret(created["id"])["passphrase"] == "key-pass"


def test_playbook_library_can_delete_a_playbook_and_its_versions(tmp_path: Path):
    repository = store(tmp_path)
    project = repository.save_project(ProjectInput(name="Local", source_type="editor"), "admin")
    playbook = repository.save_playbook(
        PlaybookInput(project_id=project["id"], name="Deploy web", filename="deploy-web.yml", content="---\n- hosts: web\n  tasks: []\n"),
        "admin",
        {"ok": True, "warnings": [], "blocked": []},
    )

    assert [item["id"] for item in repository.playbooks()] == [playbook["id"]]
    assert repository.delete_playbook(playbook["id"], "admin") is True
    assert repository.playbooks() == []
    assert repository._get("playbooks", playbook["id"]) is None
    assert repository.playbook_versions(playbook["id"]) == []


def test_cipher_rejects_tampering(tmp_path: Path):
    cipher = CredentialCipher(tmp_path / "key")
    encrypted = cipher.encrypt("secret", associated_data="credential")
    replacement = encrypted[:-2] + ("AA" if encrypted[-2:] != "AA" else "BB")

    with pytest.raises(ValueError):
        cipher.decrypt(replacement, associated_data="credential")


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "::/0", "8.8.8.0/24", "192.168.0.0/16"])
def test_scan_limits_block_internet_and_oversized_ranges(cidr: str):
    with pytest.raises(ValueError):
        scan_addresses(NetworkScanInput(cidr=cidr))


def test_nmap_arguments_are_fixed_tcp_only_and_bounded():
    payload = NetworkScanInput(cidr="192.168.10.0/30", port=2222, timeout_seconds=3)
    addresses = scan_addresses(payload)
    args = build_nmap_args(payload, addresses, "/usr/bin/nmap")

    assert args[0] == "/usr/bin/nmap"
    assert "-sT" in args
    assert "-sU" not in args
    assert "--script" not in args
    assert args[-2:] == addresses


def test_nmap_xml_parser_returns_only_discovered_ssh_endpoints():
    xml = """<nmaprun><host><address addr="192.168.1.4" addrtype="ipv4"/><ports><port protocol="tcp" portid="22"><state state="open"/></port></ports><times srtt="1200"/></host></nmaprun>"""
    result = parse_nmap_xml(xml, 22)

    assert result == [{"address": "192.168.1.4", "hostname": "", "port": 22, "latency_ms": 1.2, "ssh_status": "open"}]


def test_playbook_risk_analysis_blocks_controller_execution():
    result = analyze_playbook(
        """- hosts: all
  connection: local
  tasks:
    - name: pipe
      ansible.builtin.debug:
        msg: "{{ lookup('pipe', 'id') }}"
    - local_action: command id
"""
    )

    assert result["ok"] is False
    assert {item["code"] for item in result["blocked"]} >= {"LOCAL_CONNECTION", "PIPE_LOOKUP", "LOCAL_EXECUTION"}
    assert any(item["code"] == "ALL_HOSTS" for item in result["warnings"])


def test_playbook_builder_never_accepts_an_executable_or_path_from_frontend(tmp_path: Path):
    playbook = tmp_path / "site.yml"
    inventory = tmp_path / "inventory.yml"
    playbook.write_text("- hosts: managed\n", encoding="utf-8")
    inventory.write_text("all: {}\n", encoding="utf-8")
    args = build_ansible_playbook_args(playbook, inventory, limit="managed", tags=["safe"], check=True, verbosity=2)

    assert args[0] == "ansible-playbook"
    assert args[-1] == str(playbook)
    assert "--check" in args
    with pytest.raises(ValueError):
        build_ansible_playbook_args(playbook, inventory, limit="managed;reboot")


def test_all_ansible_preflight_commands_are_fixed(tmp_path: Path):
    playbook = tmp_path / "site.yml"
    inventory = tmp_path / "inventory.yml"
    playbook.write_text("- hosts: managed\n", encoding="utf-8")
    inventory.write_text("all: {}\n", encoding="utf-8")

    commands = playbook_validation_commands(playbook, inventory)

    assert [command[-2] for command in commands] == ["--syntax-check", "--list-hosts", "--list-tasks", "--list-tags"]
    assert inventory_validation_commands(str(inventory)) == [
        ["ansible-inventory", "--inventory", str(inventory), "--list"],
        ["ansible-inventory", "--inventory", str(inventory), "--graph"],
    ]


def test_project_path_cannot_escape(tmp_path: Path):
    with pytest.raises(ValueError):
        safe_project_path(tmp_path / "project", "../../etc/shadow")


def test_inventory_generation_and_plaintext_secret_rejection():
    content = generate_inventory(
        [{"id": "host", "name": "node", "address": "192.168.1.9", "port": 22, "ssh_user": "ansible", "python_interpreter": "auto_silent", "connection_type": "ssh", "variables": {}, "active": True}],
        [],
    )
    assert "192.168.1.9" in content
    with pytest.raises(ValueError, match="plaintext secret"):
        parse_inventory("all:\n  vars:\n    ansible_password: secret\n")


def test_host_model_blocks_transport_override_and_controller_loopback():
    with pytest.raises(ValueError, match="transport"):
        HostInput(name="node", address="192.168.1.9", variables={"ansible_connection": "local"})
    with pytest.raises(ValueError, match="controller host"):
        HostInput(name="node", address="127.0.0.1")
    with pytest.raises(ValueError, match="Python interpreter"):
        HostInput(name="node", address="192.168.1.9", python_interpreter="/tmp/python;id")


def test_ssh_password_credential_requires_a_local_username():
    with pytest.raises(ValueError, match="require a username"):
        CredentialInput(name="Local account", type=CredentialType.ssh_password, secret="password")
    credential = CredentialInput(name="Local account", type=CredentialType.ssh_password, username="operator", secret="password")
    assert credential.username == "operator"


def test_known_host_change_is_blocked_without_explicit_replace(tmp_path: Path):
    repository = store(tmp_path)
    host = repository.save_host(HostInput(name="node", address="192.168.1.20"), "admin")
    repository.accept_known_key(host["id"], host["address"], 22, "ssh-ed25519", "AAAATEST", "SHA256:firstfirstfirstfirst", "admin")

    with pytest.raises(RuntimeError, match="changed"):
        repository.accept_known_key(host["id"], host["address"], 22, "ssh-ed25519", "AAAANEW", "SHA256:secondsecondsecond", "admin")


def test_ssh_builder_enforces_known_hosts_and_fixed_probe(tmp_path: Path):
    args = build_ssh_args({"address": "192.168.1.5", "port": 22, "ssh_user": "ansible"}, tmp_path / "known_hosts", key_file=tmp_path / "key", probe="python")

    assert "StrictHostKeyChecking=yes" in args
    assert f"UserKnownHostsFile={tmp_path / 'known_hosts'}" in args
    assert "BatchMode=yes" in args
    assert args[-3:] == ["sh", "-c", "command -v python3 || command -v python || true"]


def test_remote_user_script_validates_sudoers_and_contains_rollback():
    script = build_managed_user_script("algen-ansible", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest controller", "nopasswd")

    assert "visudo -cf" in script
    assert "rollback" in script
    assert "authorized_keys.new" in script
    assert "chmod 0600" in script
    assert "usermod --lock" in script
    assert "NOPASSWD: ALL" in script
    with pytest.raises(ValueError):
        build_managed_user_script("root;reboot", "ssh-ed25519 AAAA")


def test_passwordless_onboarding_requires_typed_host_confirmation():
    payload = {
        "host": {"name": "node", "address": "192.168.1.4"},
        "initial_username": "root",
        "create_managed_user": True,
        "sudo_profile": "nopasswd",
        "confirm": True,
    }
    with pytest.raises(ValueError, match="typing the host address"):
        OnboardingInput.model_validate(payload)
    assert OnboardingInput.model_validate({**payload, "confirm_host_name": "192.168.1.4"}).sudo_profile == "nopasswd"


def test_onboarding_always_provisions_a_safe_configurable_managed_account():
    base = {
        "host": {"name": "node", "address": "192.168.1.4"},
        "initial_username": "root",
        "confirm": True,
    }
    payload = OnboardingInput.model_validate(base)
    assert payload.create_managed_user is True
    assert payload.managed_username == "algen-ansible"
    with pytest.raises(ValueError):
        OnboardingInput.model_validate({**base, "create_managed_user": False})
    assert OnboardingInput.model_validate({**base, "managed_username": "automation-user"}).managed_username == "automation-user"
    with pytest.raises(ValueError, match="protected system account"):
        OnboardingInput.model_validate({**base, "managed_username": "root"})


def test_managed_account_configuration_validates_username_and_safe_sudo_profiles():
    value = ManagedAccountConfigInput.model_validate({"username": "deploy-bot", "sudo_profile": "nopasswd", "shell": "/bin/sh", "comment": "Production automation", "authorized_keys_mode": "exclusive", "key_rotation_days": 60, "confirm": True})
    assert value.username == "deploy-bot"
    assert value.sudo_profile == "nopasswd"
    assert value.shell == "/bin/sh"
    assert value.authorized_keys_mode == "exclusive"
    assert value.key_rotation_days == 60
    with pytest.raises(ValueError):
        ManagedAccountConfigInput.model_validate({"username": "root", "sudo_profile": "none"})
    with pytest.raises(ValueError):
        ManagedAccountConfigInput.model_validate({"username": "deploy-bot", "sudo_profile": "password"})
    with pytest.raises(ValueError):
        ManagedAccountConfigInput.model_validate({"username": "deploy-bot", "shell": "/bin/zsh"})
    with pytest.raises(ValueError):
        ManagedAccountConfigInput.model_validate({"username": "deploy-bot", "comment": "invalid:comment"})
    with pytest.raises(ValueError):
        ManagedAccountConfigInput.model_validate({"username": "deploy-bot", "authorized_keys_mode": "append"})


def test_each_managed_host_gets_a_distinct_ed25519_key(tmp_path: Path):
    if not shutil.which("ssh-keygen"):
        pytest.skip("ssh-keygen is unavailable")
    repository = store(tmp_path)
    first_private, first_public = _generate_host_key(repository, "host-a")
    second_private, second_public = _generate_host_key(repository, "host-b")

    assert first_private != second_private
    assert first_public != second_public
    assert first_public.endswith("webnas-ansible:host-a")
    assert second_public.endswith("webnas-ansible:host-b")


def test_demote_preexec_drops_groups_gid_and_uid(monkeypatch):
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(os, "setgroups", lambda groups: calls.append(("groups", groups)), raising=False)
    monkeypatch.setattr(os, "setgid", lambda gid: calls.append(("gid", gid)), raising=False)
    monkeypatch.setattr(os, "setuid", lambda uid: calls.append(("uid", uid)), raising=False)
    monkeypatch.setattr(os, "umask", lambda mask: calls.append(("umask", mask)), raising=False)

    demote_preexec(1001, 1002)()

    assert calls[:3] == [("groups", []), ("gid", 1002), ("uid", 1001)]
    with pytest.raises(ValueError):
        demote_preexec(0, 0)


def test_host_locks_block_overlapping_executions(tmp_path: Path):
    repository = store(tmp_path)
    host = repository.save_host(HostInput(name="node", address="192.168.1.7"), "admin")
    now = 1.0
    with repository.connect() as connection:
        for execution_id in ("first", "second"):
            connection.execute("INSERT INTO executions(id,requested_by,status,stage,active,created_at,updated_at,created_by,updated_by) VALUES(?,?, 'running','run',1,?,?,?,?)", (execution_id, "admin", now, now, "admin", "admin"))
    repository.acquire_host_locks("first", [host["id"]])
    with pytest.raises(RuntimeError, match="locked"):
        repository.acquire_host_locks("second", [host["id"]])
    repository.release_host_locks("first")
    repository.acquire_host_locks("second", [host["id"]])


def test_execution_concurrency_policies_are_enforced(tmp_path: Path):
    repository = store(tmp_path)
    with repository.connect() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("INSERT INTO executions(id,template_id,requested_by,status,stage,active,created_at,updated_at,created_by,updated_by) VALUES('running','template-a','admin','running','run',1,1,1,'admin','admin')")
        connection.execute("INSERT INTO executions(id,template_id,requested_by,status,stage,active,created_at,updated_at,created_by,updated_by) VALUES('next','template-a','admin','queued','queued',1,2,2,'admin','admin')")
    repository.acquire_execution_locks("next", "template-a", [], "parallel")
    with pytest.raises(RuntimeError, match="concurrency"):
        repository.acquire_execution_locks("next", "template-a", [], "template")
    with pytest.raises(RuntimeError, match="concurrency"):
        repository.acquire_execution_locks("next", "template-b", [], "single")


def test_recap_parser_separates_every_host_result():
    result = parse_recap("node1 : ok=3 changed=1 unreachable=0 failed=0 skipped=2 rescued=0 ignored=0\nnode2 : ok=0 changed=0 unreachable=1 failed=0 skipped=0 rescued=0 ignored=0")

    assert result[0]["host_name"] == "node1" and result[0]["status"] == "changed"
    assert result[1]["host_name"] == "node2" and result[1]["status"] == "unreachable"


def test_schedules_calculate_persistent_next_run():
    schedule = ScheduleInput(name="Daily", template_id="a" * 32, kind="daily", expression="1", timezone="UTC")
    following = next_run(schedule.kind.value, schedule.expression, schedule.timezone, 1_700_000_000)

    assert following is not None and following > 1_700_000_000
    with pytest.raises(ValueError):
        ScheduleInput(name="Bad", template_id="a" * 32, kind="cron", expression="* * * * *;id", timezone="UTC")


def test_backup_is_versioned_checksummed_and_validated(tmp_path: Path):
    repository = store(tmp_path)
    repository.save_host(HostInput(name="node", address="192.168.1.30"), "admin")
    backup = create_backup(repository, "admin", "test")
    manifest = validate_backup(repository, backup["id"], backup["checksum"])

    assert manifest["version"] == 1
    assert len(backup["checksum"]) == 64
    with pytest.raises(ValueError, match="checksum"):
        validate_backup(repository, backup["id"], "0" * 64)


def test_restore_is_atomic_and_creates_a_safety_backup(tmp_path: Path):
    repository = store(tmp_path)
    host = repository.save_host(HostInput(name="node", address="192.168.1.31"), "admin")
    project_file = repository.root / "projects" / "demo" / "site.yml"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("original\n", encoding="utf-8")
    backup = create_backup(repository, "admin", "before")
    repository.delete_host(host["id"], "admin")
    project_file.write_text("changed\n", encoding="utf-8")

    result = restore_backup(repository, backup["id"], backup["checksum"], "admin")

    assert result["ok"] is True
    assert result["safety_backup"]["id"] != backup["id"]
    assert repository.host(host["id"])["active"] is True
    assert project_file.read_text(encoding="utf-8") == "original\n"


def test_backup_omits_credential_envelopes_unless_explicitly_requested(tmp_path: Path):
    repository = store(tmp_path)
    repository.save_credential(CredentialInput(name="AWX", type=CredentialType.awx_token, secret="token-value"), "admin")
    backup = create_backup(repository, "admin", include_credentials=False)
    extracted = tmp_path / "backup.sqlite3"
    with tarfile.open(repository.root / "backups" / f"{backup['id']}.tar.gz", "r:gz") as archive:
        member = archive.extractfile("controller.sqlite3")
        assert member is not None
        extracted.write_bytes(member.read())
    connection = sqlite3.connect(extracted)
    try:
        encrypted = connection.execute("SELECT encrypted_secret FROM credentials").fetchone()[0]
    finally:
        connection.close()

    assert encrypted == ""


def test_redaction_removes_nested_and_text_secrets():
    assert redact({"token": "abc", "nested": {"password": "def"}}) == {"token": "[REDACTED]", "nested": {"password": "[REDACTED]"}}
    cleaned = redact_text("password=hunter2\n-----BEGIN PRIVATE KEY-----\nvalue\n-----END PRIVATE KEY-----")
    assert "hunter2" not in cleaned and "value" not in cleaned


def test_all_granular_permissions_are_registered():
    expected = {
        "ansible-controller.view", "ansible-controller.install", "ansible-controller.configure", "ansible-controller.hosts.view",
        "ansible-controller.hosts.manage", "ansible-controller.discovery", "ansible-controller.credentials.view",
        "ansible-controller.credentials.manage", "ansible-controller.projects.view", "ansible-controller.projects.manage",
        "ansible-controller.playbooks.view", "ansible-controller.playbooks.manage", "ansible-controller.jobs.launch",
        "ansible-controller.jobs.cancel", "ansible-controller.schedules.manage", "ansible-controller.audit.view",
        "ansible-controller.backup", "ansible-controller.restore",
    }
    assert expected <= ALL_PERMISSIONS
    assert Permission.ANSIBLE_RESTORE.value in expected


def test_ansible_read_is_csrf_free_and_mutation_requires_csrf(monkeypatch, tmp_path: Path):
    repository = store(tmp_path)
    monkeypatch.setattr(ansible_router, "repository", lambda: repository)
    monkeypatch.setattr(identity_permissions, "get_session_user", lambda _request: SessionUser(username="admin", csrf_token="csrf"))
    monkeypatch.setattr(identity_permissions, "authorize", lambda _user, _permission: None)
    app = FastAPI()
    app.include_router(ansible_router.router)
    client = TestClient(app)
    payload = {"name": "node", "address": "192.168.1.25"}

    assert client.get("/api/modules/ansible-controller/scans").status_code == 200
    assert client.post("/api/modules/ansible-controller/hosts", json=payload).status_code == 403
    assert client.post("/api/modules/ansible-controller/hosts", json=payload, headers={"x-csrf-token": "csrf"}).status_code == 200


def test_managed_key_can_only_be_assigned_to_its_own_host(monkeypatch, tmp_path: Path):
    repository = store(tmp_path)
    own_host = repository.save_host(HostInput(name="node-a", address="192.168.1.25"), "admin")
    credential = repository.save_credential(
        CredentialInput(
            name="Host key - node-a",
            type=CredentialType.ssh_private_key,
            username="algen-ansible",
            secret="-----BEGIN OPENSSH PRIVATE KEY-----\nQUJDREVGRw==\n-----END OPENSSH PRIVATE KEY-----",
            description=f"managed-host:{own_host['id']}; unique Ed25519 key",
        ),
        "admin",
    )
    monkeypatch.setattr(ansible_router, "repository", lambda: repository)
    monkeypatch.setattr(identity_permissions, "get_session_user", lambda _request: SessionUser(username="admin", csrf_token="csrf"))
    monkeypatch.setattr(identity_permissions, "authorize", lambda _user, _permission: None)
    app = FastAPI()
    app.include_router(ansible_router.router)
    client = TestClient(app)
    headers = {"x-csrf-token": "csrf"}

    own_update = {"name": "node-a", "address": "192.168.1.25", "credential_id": credential["id"]}
    assert client.put(f"/api/modules/ansible-controller/hosts/{own_host['id']}", json=own_update, headers=headers).status_code == 200
    other_host = {"name": "node-b", "address": "192.168.1.26", "credential_id": credential["id"]}
    response = client.post("/api/modules/ansible-controller/hosts", json=other_host, headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MANAGED_HOST_CREDENTIAL"


def test_typed_router_generates_complete_openapi_schema():
    app = FastAPI()
    app.include_router(ansible_router.router)
    schema = app.openapi()
    paths = [path for path in schema["paths"] if path.startswith("/api/modules/ansible-controller")]
    operations = sum(sum(method in {"get", "post", "put", "delete", "patch"} for method in schema["paths"][path]) for path in paths)

    assert len(paths) >= 40
    assert operations >= 50


def test_project_urls_support_https_and_ssh_without_embedded_secrets():
    assert ProjectInput(name="HTTPS", source_type="git", repository_url="https://example.com/team/repo.git").repository_url
    assert ProjectInput(name="SSH", source_type="git", repository_url="git@example.com:team/repo.git").repository_url
    with pytest.raises(ValueError):
        ProjectInput(name="Secret", source_type="git", repository_url="https://user:token@example.com/repo.git")
    with pytest.raises(ValueError):
        ProjectInput(name="Mismatch", source_type="editor", repository_url="https://example.com/repo.git")


def test_awx_requires_https_and_rejects_uncontrolled_paths():
    assert str(AwxSettingsInput(url="https://awx.example.com").url).startswith("https://")
    with pytest.raises(ValueError):
        AwxSettingsInput(url="http://awx.example.com")
    client = AwxClient("https://awx.example.com", "token")
    with pytest.raises(ValueError, match="unsupported"):
        client.request("/api/v2/../settings/")


def test_awx_integration_uses_bearer_header_and_bounded_resource(monkeypatch):
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit: int) -> bytes:
            assert limit == 4 * 1024 * 1024
            return b'{"results":[{"id":1,"name":"Demo"}]}'

    def fake_urlopen(request, *, timeout, context):
        captured.update({"authorization": request.get_header("Authorization"), "url": request.full_url, "timeout": timeout, "context": context})
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = AwxClient("https://awx.example.com", "secret-token", timeout=8).list_resource("organizations")

    assert result == [{"id": 1, "name": "Demo"}]
    assert captured["authorization"] == "Bearer secret-token"
    assert captured["url"] == "https://awx.example.com/api/v2/organizations/?page_size=200"


def test_provider_is_explicitly_registered(tmp_path: Path, monkeypatch):
    isolated = store(tmp_path)
    monkeypatch.setattr("app.modules.providers.ansible_controller.repository", lambda: isolated)
    assert get_provider("ansible-controller", "admin").module_id == "ansible-controller"


def test_network_process_observes_cancellation():
    with pytest.raises(InterruptedError, match="cancelled"):
        _run_cancellable([sys.executable, "-c", "import time; time.sleep(30)"], timeout=30, cancelled=lambda: True)
