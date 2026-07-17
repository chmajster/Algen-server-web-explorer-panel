from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import apps
from app.modules import router as module_router
from app.modules.providers import base as provider_base
from app.modules.providers.base import ModuleProvider
from app.modules.providers.samba import SambaProvider, parse_smb_conf, parse_smbstatus_json, parse_smbstatus_text
from app.package_center.models import ModuleManifest, ModuleStatus, ModuleValidationResult, PackageAction
from app.package_center.repository import PackageRepository
from app.security import SessionUser


def admin() -> SessionUser:
    return SessionUser(username="admin", csrf_token="csrf")


def test_legacy_manifest_is_mapped_to_provider_contract():
    manifest = ModuleManifest(id="demo", name="Demo", description="Demo", version="1.0", apt_packages=["demo"], dnf_packages=["demo"], systemd_services=["demo"])

    assert manifest.packages.apt == ["demo"]
    assert manifest.packages.yum == ["demo"]
    assert manifest.services[0].name == "demo"
    assert manifest.services[0].required is True


def test_manifest_rejects_arbitrary_validation_commands():
    with pytest.raises(ValueError):
        ModuleManifest(
            id="demo",
            name="Demo",
            description="Demo",
            version="1.0",
            apt_packages=["demo"],
            config={"primary_file": "/etc/demo.conf", "validation_command": ["bash", "-c", "anything"]},
        )


def test_provider_rejects_unknown_service_operation():
    with pytest.raises(HTTPException) as exc:
        ModuleProvider._systemctl("smbd", "status; reboot")

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "INVALID_SERVICE_ACTION"


def test_router_rejects_unknown_service_action_before_handler(monkeypatch):
    app = FastAPI()
    app.include_router(module_router.router)
    app.dependency_overrides[module_router.mutating_admin] = admin
    client = TestClient(app)

    response = client.post("/api/modules/samba/service/reboot", json={}, headers={"x-csrf-token": "csrf"})

    assert response.status_code == 422


def test_state_change_uses_the_authenticated_session(monkeypatch, tmp_path: Path):
    repository = PackageRepository(tmp_path / "jobs.sqlite3")
    plan = SimpleNamespace(module_id="samba", action=PackageAction.restart)
    monkeypatch.setattr(module_router, "repository", lambda: repository)
    monkeypatch.setattr(module_router, "manager", lambda repo: SimpleNamespace(enqueue=lambda next_plan, actor: {"id": "job", "module_id": next_plan.module_id, "created_by": actor}))

    result = module_router._enqueue(plan, module_router.ModuleAdminRequest(), admin())

    assert result["job"]["id"] == "job"


def test_smb_conf_parser_imports_only_supported_options():
    parsed = parse_smb_conf(
        """[global]
workgroup = HOME
server min protocol = SMB2

[Media$]
path = /srv/media
read only = no
valid users = alice @family
create mask = 0660
directory mask = 0770
vfs objects = recycle
recycle:versions = yes
"""
    )

    assert parsed.global_options["workgroup"] == "HOME"
    assert parsed.shares[0].name == "Media"
    assert parsed.shares[0].hidden is True
    assert parsed.shares[0].valid_users == ["alice"]
    assert parsed.shares[0].valid_groups == ["family"]
    assert parsed.shares[0].recycle_bin is True


def test_smb_conf_parser_rejects_unknown_directives_and_size():
    with pytest.raises(ValueError, match="Unsupported Samba options"):
        parse_smb_conf("[share]\npath = /srv/share\nroot preexec = reboot\n")
    with pytest.raises(ValueError, match="1 MB"):
        parse_smb_conf("#" * 1_000_001)


def test_smbstatus_json_and_text_fallback_parsers():
    payload = {
        "sessions": {"10": {"session_id": "10", "username": "alice", "hostname": "laptop", "remote_machine": "10.0.0.8", "protocol_ver": "SMB3", "pid": 123}},
        "tcons": {"1": {"session_id": "10", "share_name": "Media"}},
        "open_files": {"1": {"session_id": "10"}, "2": {"session_id": "10"}},
    }

    parsed_json = parse_smbstatus_json(json.dumps(payload))
    parsed_text = parse_smbstatus_text("PID Username Group Machine Protocol Version Encryption Signing\n123 alice users 10.0.0.8 SMB3 - -\n\nService pid Machine Connected at Encryption Signing\n")

    assert parsed_json[0]["share"] == "Media"
    assert parsed_json[0]["open_files"] == 2
    assert parsed_text[0]["username"] == "alice"
    assert parsed_text[0]["pid"] == 123


def test_samba_version_is_normalized_for_the_user_interface(monkeypatch):
    monkeypatch.setattr("app.modules.providers.samba.shutil.which", lambda name: "/usr/sbin/smbd")
    monkeypatch.setattr("app.modules.providers.samba.subprocess.run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "Version 4.19.5-Ubuntu\n", ""))

    assert SambaProvider._version() == "4.19.5-Ubuntu"


def test_global_config_uses_closed_validation_and_renders_safe_warnings(monkeypatch, tmp_path: Path):
    provider = SambaProvider("admin")
    current = apps.SambaConfig()
    monkeypatch.setattr(apps, "read_samba_config", lambda: current)
    monkeypatch.setattr(apps, "preview_samba_config", lambda actor, config: {"config": apps.render_smb_conf(config), "validation": {"ok": True, "stdout": "Loaded services file OK", "stderr": ""}})

    validation = provider.validate_config({"shares": [], "global_options": {"workgroup": "HOME", "server min protocol": "NT1", "wide links": "yes", "log level": "2"}})
    invalid = provider.validate_config({"shares": [], "global_options": {"root preexec": "reboot"}})

    assert validation.ok is True
    assert validation.confirmations_required == ["smb1"]
    assert any("Wide links" in warning for warning in validation.warnings)
    assert invalid.ok is False
    assert "Unsupported global Samba option" in invalid.errors[0]


def test_share_validation_reports_missing_path_and_unknown_account(monkeypatch, tmp_path: Path):
    provider = SambaProvider("admin")
    path = tmp_path / "missing"
    monkeypatch.setattr(apps, "read_samba_config", lambda: apps.SambaConfig())
    monkeypatch.setattr(apps, "preview_samba_config", lambda actor, config: {"config": apps.render_smb_conf(config), "validation": {"ok": True, "stdout": "ok", "stderr": ""}})
    monkeypatch.setattr("app.modules.providers.samba.pwd.getpwnam", lambda username: (_ for _ in ()).throw(KeyError(username)))

    validation = provider.validate_config({"shares": [{"name": "media", "path": str(path), "valid_users": ["missing"]}], "global_options": {}})

    assert validation.ok is False
    assert any("does not exist" in error for error in validation.errors)
    assert any("account does not exist" in error for error in validation.errors)


def test_module_logs_reject_source_and_redact_secrets(monkeypatch):
    provider = ModuleProvider("nginx")
    monkeypatch.setattr(provider_base.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(provider_base.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "password=secret token: abc\nordinary line\n", ""))

    result = provider.get_logs("journal:nginx", 50)

    assert "secret" not in "\n".join(result["lines"])
    assert "abc" not in "\n".join(result["lines"])
    assert "[REDACTED]" in result["lines"][0]
    with pytest.raises(HTTPException) as exc:
        provider.get_logs("file:/etc/shadow")
    assert exc.value.status_code == 400


def configure_backup_provider(monkeypatch, tmp_path: Path) -> SambaProvider:
    data = tmp_path / "data"
    main = tmp_path / "smb.conf"
    managed = tmp_path / "algen-shares.conf"
    main.write_text("[global]\ninclude = /etc/samba/algen-shares.conf\n", encoding="utf-8")
    managed.write_text("[media]\npath = /srv/media\n", encoding="utf-8")
    monkeypatch.setattr("app.modules.providers.samba.get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(data)), security=SimpleNamespace(system_uid_threshold=1000)))
    monkeypatch.setattr(apps, "SAMBA_CONF", main)
    monkeypatch.setattr(apps, "SAMBA_ALGEN_CONF", managed)
    monkeypatch.setattr(SambaProvider, "_version", staticmethod(lambda: "4.20"))
    return SambaProvider("admin")


def test_backup_is_private_checksummed_and_contains_controlled_configs(monkeypatch, tmp_path: Path):
    provider = configure_backup_provider(monkeypatch, tmp_path)

    backup = provider.create_backup("admin", "before edit")
    listed = provider.list_backups()

    assert listed[0]["id"] == backup["id"]
    assert listed[0]["files"] == ["algen-shares.conf", "smb.conf"]
    assert provider._backup_content(backup["id"]).startswith(b"[media]")
    if os.name != "nt":
        assert stat.S_IMODE((provider.backup_dir / f"{backup['id']}.json").stat().st_mode) & 0o077 == 0
    (provider.backup_dir / f"{backup['id']}.managed.conf").write_text("tampered", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        provider._backup_content(backup["id"])
    assert exc.value.detail["code"] == "BACKUP_CHECKSUM_MISMATCH"


def test_automatic_backup_retention_keeps_twenty(monkeypatch, tmp_path: Path):
    provider = configure_backup_provider(monkeypatch, tmp_path)

    for index in range(22):
        provider.create_backup("admin", f"automatic {index}", automatic=True)

    assert len([item for item in provider.list_backups() if item["automatic"]]) == 20


def test_apply_rolls_back_both_config_files_when_reload_fails(monkeypatch, tmp_path: Path):
    provider = configure_backup_provider(monkeypatch, tmp_path)
    old_main = apps.SAMBA_CONF.read_bytes()
    old_managed = apps.SAMBA_ALGEN_CONF.read_bytes()
    next_config = apps.SambaConfig(shares=[apps.SambaShare(name="new", path=str(tmp_path))])
    validation = ModuleValidationResult(ok=True, generated_config="[new]\npath = /srv/new\n")
    reloads = 0

    monkeypatch.setattr(provider, "validate_config", lambda config: validation)
    monkeypatch.setattr(apps, "validate_share_path", lambda actor, share: tmp_path)
    monkeypatch.setattr(apps, "_prepare_share_directory", lambda share, path: None)
    monkeypatch.setattr(apps, "_ensure_smb_conf_include", lambda: apps.SAMBA_CONF.write_text("changed main", encoding="utf-8"))
    monkeypatch.setattr(apps, "testparm_config", lambda content: {"ok": True, "stdout": "ok", "stderr": ""})

    def reload(log):
        nonlocal reloads
        reloads += 1
        if reloads == 1:
            raise RuntimeError("reload failed")

    monkeypatch.setattr(provider, "_reload_and_verify", reload)

    with pytest.raises(RuntimeError, match="reload failed"):
        provider.execute_operation(PackageAction.apply, {"config": next_config.model_dump()}, "admin", lambda *_: None, lambda *_: None, lambda: False)

    assert apps.SAMBA_CONF.read_bytes() == old_main
    assert apps.SAMBA_ALGEN_CONF.read_bytes() == old_managed
    assert reloads == 2


def test_samba_cleanup_never_removes_shared_directories(monkeypatch, tmp_path: Path):
    provider = configure_backup_provider(monkeypatch, tmp_path)
    shared = tmp_path / "shared-data"
    shared.mkdir()
    (shared / "keep.txt").write_text("keep", encoding="utf-8")
    state = {"configured": True, "config": {"shares": [{"name": "Media", "path": str(shared)}]}}
    monkeypatch.setattr(apps, "read_state", lambda app_id: state)
    monkeypatch.setattr(apps, "write_state", lambda app_id, value: state.update(value))

    result = provider.cleanup_after_uninstall("admin", True)

    assert result["managed_config_removed"] is True
    assert result["shared_data_removed"] is False
    assert (shared / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_repository_migrates_old_jobs_and_persists_module_result(tmp_path: Path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE package_jobs (
            id TEXT PRIMARY KEY, module_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0, current_step TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL,
            created_at REAL NOT NULL, started_at REAL, finished_at REAL, exit_code INTEGER, error TEXT NOT NULL DEFAULT '',
            cancellation_requested INTEGER NOT NULL DEFAULT 0, requires_reboot INTEGER NOT NULL DEFAULT 0,
            previous_version TEXT, target_version TEXT, plan_json TEXT NOT NULL, retry_of TEXT)"""
        )
    repository = PackageRepository(database)
    columns = {row[1] for row in repository.connect().execute("PRAGMA table_info(package_jobs)").fetchall()}

    assert {"warnings_json", "result_json"} <= columns


def test_service_operation_checks_real_post_state(monkeypatch):
    provider = ModuleProvider("nginx")
    monkeypatch.setattr(provider, "_systemctl", lambda service, action: subprocess.CompletedProcess(["systemctl", action, service], 0, "ok", ""))
    monkeypatch.setattr(
        provider,
        "get_status",
        lambda: ModuleStatus(installed=True, service_state="inactive", service_enabled=True, services={"nginx": {"state": "inactive", "enabled": True, "required": True}}),
    )

    with pytest.raises(RuntimeError, match="not active"):
        provider.execute_operation(PackageAction.start, {}, "admin", lambda *_: None, lambda *_: None, lambda: False)
