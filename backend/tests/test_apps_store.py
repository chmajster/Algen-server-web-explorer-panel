from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import apps


def test_app_state_defaults_to_data_dir():
    assert apps.APP_STATE_DIR == apps.Path("/var/lib/webnas/apps")


def test_samba_install_dry_run_lists_packages(monkeypatch):
    monkeypatch.setattr(apps.shutil, "which", lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)

    steps = apps.plan_install("samba")

    assert any("samba" in step for step in steps)
    assert any("smbclient" in step for step in steps)


def test_smb_conf_backup_is_created(monkeypatch, tmp_path):
    conf = tmp_path / "smb.conf"
    conf.write_text("[global]\n", encoding="utf-8")
    monkeypatch.setattr(apps, "SAMBA_CONF", conf)

    backup = apps.backup_smb_conf("20260101-120000")

    assert backup is not None
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "[global]\n"


def test_blocked_share_path_rejected(monkeypatch):
    monkeypatch.setattr(apps, "safe_mode_active", lambda: False)
    share = apps.SambaShare(name="etc", path="/etc")

    with pytest.raises(HTTPException) as exc:
        apps.validate_share_path("admin", share)

    assert exc.value.status_code == 403


def test_samba_config_generation_validates_and_renders():
    config = apps.SambaConfig(shares=[
        apps.SambaShare(name="media", path="/srv/media", comment="Media", read_only=False, valid_users=["alice"], write_list=["alice"], admin_users=["@admins"], recycle_bin=True)
    ])

    rendered = apps.render_smb_conf(config)

    assert "[media]" in rendered
    assert "path = /srv/media" in rendered
    assert "valid users = alice" in rendered
    assert "write list = alice" in rendered
    assert "admin users = @admins" in rendered
    assert "vfs objects = recycle" in rendered


def test_samba_config_rejects_injected_comment():
    config = apps.SambaConfig(shares=[
        apps.SambaShare(name="media", path="/srv/media", comment="ok\n[bad]")
    ])

    with pytest.raises(HTTPException) as exc:
        apps.render_smb_conf(config)

    assert exc.value.status_code == 400


def test_bad_testparm_blocks_config_write(monkeypatch, tmp_path):
    conf = tmp_path / "smb.conf"
    algen_conf = tmp_path / "algen-shares.conf"
    state_dir = tmp_path / "state"
    candidate = state_dir / "algen-shares.conf.candidate"
    monkeypatch.setattr(apps, "SAMBA_CONF", conf)
    monkeypatch.setattr(apps, "SAMBA_ALGEN_CONF", algen_conf)
    monkeypatch.setattr(apps, "APP_STATE_DIR", state_dir)
    monkeypatch.setattr(apps.shutil, "which", lambda name: "/usr/bin/testparm" if name == "testparm" else None)
    monkeypatch.setattr(apps, "validate_share_path", lambda username, share: tmp_path / "media")
    monkeypatch.setattr(apps.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="bad config", stdout=""))

    config = apps.SambaConfig(shares=[apps.SambaShare(name="media", path=str(tmp_path / "media"))])

    with pytest.raises(HTTPException) as exc:
        apps.write_samba_config("admin", config)

    assert exc.value.status_code == 400
    assert candidate.exists()
    assert not conf.exists()
    assert not algen_conf.exists()


def test_proxmox_safe_mode_blocks_unsafe_module(monkeypatch):
    monkeypatch.setattr(apps, "load_manifest", lambda app_id: {"proxmox_safe": False})
    monkeypatch.setattr(apps, "safe_mode_active", lambda: True)

    with pytest.raises(HTTPException) as exc:
        apps.assert_app_allowed_on_host("unsafe")

    assert exc.value.status_code == 403


def test_non_admin_cannot_list_apps(monkeypatch):
    monkeypatch.setattr(apps, "_is_admin", lambda username: False)

    with pytest.raises(HTTPException) as exc:
        apps.list_apps(SimpleNamespace(username="alice"))

    assert exc.value.status_code == 403


def test_install_action_is_audited(monkeypatch):
    messages = []
    monkeypatch.setattr(apps, "_require_admin", lambda *args, **kwargs: None)
    monkeypatch.setattr(apps, "assert_app_allowed_on_host", lambda app_id: None)
    monkeypatch.setattr(apps, "enqueue", lambda app_id, action, worker: SimpleNamespace(to_dict=lambda: {"id": "job-1"}))
    monkeypatch.setattr(apps.logger, "info", lambda *args, **kwargs: messages.append(args))

    result = apps.install_app("samba", apps.AdminAction(admin_password="secret"), SimpleNamespace(username="admin"))

    assert result == {"job": {"id": "job-1"}}
    assert any("app_store_action" in item[0] for item in messages)


def test_store_plugin_requires_github_url():
    plugin = apps.StorePlugin(
        name="Demo plugin",
        github_url="https://example.com/not-github/plugin",
        codex_instructions="Inspect repository",
    )

    with pytest.raises(HTTPException) as exc:
        apps._validate_plugin(plugin)

    assert exc.value.status_code == 400


def test_store_plugin_generates_codex_instructions():
    plugin = apps.StorePlugin(
        name="Demo plugin",
        github_url="https://github.com/example/algen-demo-plugin",
        branch="main",
        codex_instructions="",
    )

    validated = apps._validate_plugin(plugin)

    assert "Codex task" in validated.codex_instructions
    assert "https://github.com/example/algen-demo-plugin" in validated.codex_instructions
