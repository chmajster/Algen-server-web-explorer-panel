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


def test_mount_payload_accepts_an_authenticated_session_without_admin_password():
    assert "admin_password" not in network_mounts.MountPayload.model_fields
    assert payload().name == "media"  # Older clients may still send the ignored field.


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
        "mount_point": "/mnt/webnas/mnt/media",
        "read_only": True,
        "persistent": True,
        "config": {"smb_version": "3.1.1", "file_mode": "0644", "dir_mode": "0755", "noexec": True, "automount": True, "advanced_options": []},
    }

    units = network_mounts.generate_systemd_units(mount)
    rendered = "\n".join(units.values())

    assert "credentials=" in rendered
    assert "mount-secret" not in rendered
    assert "[Automount]" in rendered
    assert any(name.endswith(".automount") for name in units)


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
    monkeypatch.setattr(network_mounts, "authorize", lambda user, permission: None)
    monkeypatch.setattr(network_mounts, "db_path", lambda: tmp_path / "mounts.sqlite3")
    monkeypatch.setattr(network_mounts, "credentials_dir", lambda: creds)
    monkeypatch.setattr(network_mounts, "validate_mount_point", lambda path, allow_existing_data=False, name=None: tmp_path / "media")
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
        network_mounts.assert_write_allowed("/mnt/webnas/mnt/media/file.txt")

    assert exc.value.status_code == 403


def test_non_admin_cannot_list_administrative_mount_data(monkeypatch):
    monkeypatch.setattr(network_mounts, "_is_admin", lambda username: False)

    with pytest.raises(HTTPException) as exc:
        network_mounts.list_mounts(SimpleNamespace(username="alice"))

    assert exc.value.status_code == 403


def test_roots_endpoint_returns_only_minimal_visible_data(monkeypatch):
    mount = {
        "id": "m1", "name": "media", "mount_point": "/mnt/webnas/mnt/media", "read_only": True,
        "status": "mounted", "actual_mounted": True, "migration_status": "ready", "manual_intervention": False,
        "owner": "admin", "allowed_users": ["alice"], "allowed_groups": [], "fs": {"total": 10, "used": 5, "free": 5, "fs_type": "cifs"},
        "config": {"username": "technical-user", "has_secret": True}, "remote": "//nas/media",
    }
    monkeypatch.setattr(network_mounts, "_admin_mounts", lambda: [mount])
    monkeypatch.setattr(network_mounts, "_proxmox_storage_conflicts", lambda path: False)

    result = network_mounts.mount_roots(SimpleNamespace(username="alice"))

    assert result == [{"id": "m1", "name": "media", "mount_point": "/mnt/webnas/mnt/media", "read_only": True, "status": "mounted", "filesystem": mount["fs"]}]
    assert "config" not in result[0]


@pytest.mark.parametrize("name", ["", "   ", "..", "a/b", r"a\b", "a\x00b", "a\nb", "trailing."])
def test_mount_name_rejects_unsafe_components(name):
    with pytest.raises(HTTPException):
        network_mounts.validate_mount_name(name)


def test_default_mount_point_is_owner_independent():
    assert network_mounts.default_mount_point("media") == network_mounts.MOUNT_BASE_DIR / "media"
    assert network_mounts.default_mount_point("admin", "media") == network_mounts.MOUNT_BASE_DIR / "media"


def test_payload_rejects_client_mount_point():
    with pytest.raises(Exception):
        payload(mount_point="/tmp/escape")


def test_mount_point_must_be_direct_child(monkeypatch):
    monkeypatch.setattr(network_mounts, "safe_mode_active", lambda: False)

    for path in ["/mnt/webnas/mnt/a/b", "/mnt/webnas/mnt/../etc", "/mnt/webnas/mnt2/test"]:
        with pytest.raises(HTTPException):
            network_mounts.validate_mount_point(path)


def test_mount_point_rejects_symlinked_ancestor(monkeypatch):
    original_exists = network_mounts.Path.exists
    original = network_mounts.Path.is_symlink
    monkeypatch.setattr(network_mounts.Path, "exists", lambda path: str(path) == "/mnt/webnas" or original_exists(path))
    monkeypatch.setattr(network_mounts.Path, "is_symlink", lambda path: str(path) == "/mnt/webnas" or original(path))

    with pytest.raises(HTTPException):
        network_mounts.validate_mount_point("/mnt/webnas/mnt/media")


def test_user_access_uses_primary_and_supplementary_groups(monkeypatch):
    mount = {"owner": "owner", "allowed_users": [], "allowed_groups": ["media"]}
    monkeypatch.setattr(network_mounts, "_is_admin", lambda username: False)
    monkeypatch.setattr(network_mounts, "_system_groups", lambda username: {"users", "media"} if username == "alice" else {"users"})

    assert network_mounts.user_can_access("alice", mount)
    assert not network_mounts.user_can_access("bob", mount)


def test_empty_acl_keeps_existing_authenticated_user_policy(monkeypatch):
    monkeypatch.setattr(network_mounts, "_is_admin", lambda username: False)
    mount = {"owner": "owner", "allowed_users": [], "allowed_groups": []}

    assert network_mounts.user_can_access("alice", mount)


def test_systemd_unit_name_matches_mount_path(monkeypatch):
    monkeypatch.setattr(network_mounts.shutil, "which", lambda name: None)

    assert network_mounts.systemd_unit_name("/mnt/webnas/mnt/Backup-NAS", "mount") == r"mnt-webnas-mnt-Backup\x2dNAS.mount"


def test_filesystem_stats_are_hidden_when_not_actually_mounted(monkeypatch):
    monkeypatch.setattr(network_mounts, "actual_mount", lambda path: None)

    assert network_mounts.filesystem_payload(network_mounts.MOUNT_BASE_DIR / "media") is None


def test_visible_roots_require_real_mount(tmp_path, monkeypatch):
    monkeypatch.setattr(network_mounts, "db_path", lambda: tmp_path / "mounts.sqlite3")
    monkeypatch.setattr(network_mounts, "credentials_dir", lambda: tmp_path)
    monkeypatch.setattr(network_mounts, "actual_mount", lambda path: None)
    monkeypatch.setattr(network_mounts, "missing_packages", lambda mount_type: [])
    now = 1.0
    with network_mounts.connect() as conn:
        conn.execute(
            """INSERT INTO mounts
            (id,name,normalized_name,type,host,remote,mount_point,owner,read_only,persistent,status,config_json,allowed_users_json,allowed_groups_json,created_at,updated_at,migration_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("m1", "media", "media", "nfs", "nas", "nas:/media", "/mnt/webnas/mnt/media", "admin", 0, 0, "mounted", "{}", "[]", "[]", now, now, "ready"),
        )
        conn.commit()

    assert network_mounts.visible_mount_roots("alice") == []
