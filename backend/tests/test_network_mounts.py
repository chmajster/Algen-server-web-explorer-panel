from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import network_mounts


def payload(**kwargs):
    data = {
        "admin_password": "secret",
        "name": "media",
        "type": "smb",
        "host": "nas.local",
        "share": "media",
        "username": "alice",
        "password": "mount-secret",
        "read_only": True,
    }
    data.update(kwargs)
    return network_mounts.MountPayload.model_validate(data)


def test_mount_point_blocks_system_paths(monkeypatch):
    monkeypatch.setattr(network_mounts, "safe_mode_active", lambda: False)

    for path in ["/", "/etc", "/var/lib/vz", "/etc/pve"]:
        with pytest.raises(HTTPException) as exc:
            network_mounts.validate_mount_point(path)
        assert exc.value.status_code == 403


def test_systemd_units_are_generated_without_plain_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(network_mounts, "credentials_dir", lambda: tmp_path)
    mount = {
        "id": "abc123",
        "name": "media",
        "type": "smb",
        "remote": "//nas/media",
        "mount_point": "/mnt/webnas/admin/media",
        "read_only": True,
        "persistent": True,
        "config": {"smb_version": "3.1.1", "file_mode": "0644", "dir_mode": "0755", "noexec": True, "advanced_options": []},
    }

    units = network_mounts.generate_systemd_units(mount)
    rendered = "\n".join(units.values())

    assert "credentials=" in rendered
    assert "mount-secret" not in rendered
    assert "x-systemd.automount" in rendered


def test_credentials_file_is_0600(tmp_path, monkeypatch):
    monkeypatch.setattr(network_mounts, "credentials_dir", lambda: tmp_path)
    mount_id = "credtest"

    network_mounts.write_credentials(mount_id, payload())

    path = tmp_path / f"{mount_id}.cred"
    assert path.exists()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "mount-secret" in path.read_text(encoding="utf-8")


def test_log_redacts_secret_values(tmp_path, monkeypatch):
    monkeypatch.setattr(network_mounts, "log_dir", lambda: tmp_path)

    network_mounts.log_line("m1", "mount", "failed password=super-secret token=abc")

    text = (tmp_path / "m1.log").read_text(encoding="utf-8")
    assert "super-secret" not in text
    assert "abc" not in text
    assert "<redacted>" in text


def test_smb_dry_run_uses_cifs_utils(monkeypatch):
    monkeypatch.setattr(network_mounts.shutil, "which", lambda name: None)

    plan = network_mounts.dependency_plan("smb")

    assert plan == ["Install missing package: cifs-utils"]


def test_nfs_and_sshfs_dry_run_dependencies(monkeypatch):
    monkeypatch.setattr(network_mounts.shutil, "which", lambda name: None)

    assert "nfs-common" in network_mounts.dependency_plan("nfs")[0]
    assert any("sshfs" in item for item in network_mounts.dependency_plan("sshfs"))
    assert any("fuse3" in item for item in network_mounts.dependency_plan("sshfs"))


def test_non_admin_cannot_create_mount(monkeypatch):
    monkeypatch.setattr(network_mounts, "_is_admin", lambda username: False)

    with pytest.raises(HTTPException) as exc:
        network_mounts.create_mount(payload(), SimpleNamespace(username="alice"))

    assert exc.value.status_code == 403


def test_create_mount_is_audited(monkeypatch, tmp_path):
    messages = []
    creds = tmp_path / "creds"
    creds.mkdir()
    monkeypatch.setattr(network_mounts, "_is_admin", lambda username: True)
    monkeypatch.setattr(network_mounts, "authenticate", lambda username, password: True)
    monkeypatch.setattr(network_mounts, "db_path", lambda: tmp_path / "mounts.sqlite3")
    monkeypatch.setattr(network_mounts, "credentials_dir", lambda: creds)
    monkeypatch.setattr(network_mounts, "validate_mount_point", lambda path, allow_existing_data=False: tmp_path / "media")
    monkeypatch.setattr(network_mounts.logger, "info", lambda *args, **kwargs: messages.append(args))

    result = network_mounts.create_mount(payload(), SimpleNamespace(username="admin"))

    assert result["name"] == "media"
    assert any("network_mount_action" in item[0] for item in messages)


def test_proxmox_safe_mode_blocks_vz(monkeypatch):
    monkeypatch.setattr(network_mounts, "safe_mode_active", lambda: True)

    with pytest.raises(HTTPException) as exc:
        network_mounts.validate_mount_point("/var/lib/vz/webnas")

    assert exc.value.status_code == 403


def test_read_only_mount_blocks_write(monkeypatch):
    monkeypatch.setattr(network_mounts, "mount_for_path", lambda path: {"read_only": True})

    with pytest.raises(HTTPException) as exc:
        network_mounts.assert_write_allowed("/mnt/webnas/admin/media/file.txt")

    assert exc.value.status_code == 403
