from __future__ import annotations

import io
import os
import shutil
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.identity.models import Role
from app.identity.permissions import Permission, ROLE_PERMISSIONS
from app.modules import BUILTIN_MODULE_IDS
from app.modules.os_repositories.jobs import RepositoryJobManager
from app.modules.os_repositories.auth_proxy import authenticated_mirror_proxy
from app.modules.os_repositories.models import (
    BackupInput,
    ChannelName,
    FilterRuleInput,
    RepositoryInput,
    SettingsInput,
    SigningKeyInput,
    SnapshotInput,
)
from app.modules.os_repositories.repository import RepositoryStore, SCHEMA_VERSION, object_id
from app.modules.os_repositories.security import decrypt_backup_payload, encrypt_backup_payload, managed_path, validate_mirror_url
from app.modules.os_repositories.scheduler import schedule_matches
from app.modules.os_repositories.service import RepositoryService
from app.package_center.manifests import load_manifest


@pytest.fixture
def service(tmp_path: Path, monkeypatch) -> RepositoryService:
    instance = RepositoryService(tmp_path / "os-repositories")
    monkeypatch.setattr(instance, "_audit", lambda *args, **kwargs: None)
    return instance


def local_payload(**values) -> RepositoryInput:
    return RepositoryInput.model_validate(
        {"name": "Ubuntu Local", "kind": "local", "format": "apt", "distribution": "ubuntu", "distribution_version": "24.04", "architectures": ["amd64"]}
        | values
    )


def test_manifest_is_installable_visible_and_proxmox_unsafe():
    manifest = load_manifest("os-repositories")
    assert "os-repositories" in BUILTIN_MODULE_IDS
    assert manifest.ui.hidden is False
    assert manifest.installations["apt-get"].script == "install.py"
    assert manifest.proxmox_safe is False
    assert manifest.services[0].name == "webnas-repository-server"


def test_database_migration_creates_expected_entities_and_recovers_jobs(tmp_path: Path):
    root = tmp_path / "store"
    store = RepositoryStore(root)
    tables = {row["name"] for row in store.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"repositories", "packages", "snapshots", "channels", "signing_keys", "host_assignments", "repository_sync_jobs", "schema_migrations"} <= tables
    assert store.one("SELECT MAX(version) AS version FROM schema_migrations")["version"] == SCHEMA_VERSION
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o077 == 0


def test_repository_crud_creates_four_channels(service: RepositoryService):
    item = service.save_repository(local_payload(), "admin")
    assert item["format"] == "apt"
    assert {channel["name"] for channel in item["channels"]} == {"incoming", "testing", "production", "archive"}
    assert service.dashboard()["repositories"] == 1
    assert service.delete_repository(item["id"], "admin") is True


def test_mirror_credentials_are_encrypted_masked_and_preserved(service: RepositoryService, monkeypatch):
    monkeypatch.setattr("app.modules.os_repositories.service.validate_mirror_url", lambda *args, **kwargs: ["203.0.113.10"])
    payload = RepositoryInput(
        name="Private mirror", kind="mirror", format="apt", distribution="ubuntu",
        distribution_version="24.04", architectures=["amd64"], source_url="https://packages.example/repo",
        auth_type="bearer", auth_secret="top-secret-token",
    )
    item = service.save_repository(payload, "admin")
    stored = service.store.one("SELECT * FROM repositories WHERE id=?", (item["id"],))
    assert stored and stored["encrypted_auth_secret"]
    assert "top-secret-token" not in stored["encrypted_auth_secret"]
    assert item["auth_secret_configured"] is True
    assert "encrypted_auth_secret" not in item and "auth_secret" not in item

    updated = service.save_repository(payload.model_copy(update={"description": "updated", "auth_secret": ""}), "admin", item["id"])
    assert updated["auth_secret_configured"] is True
    assert service.mirror_authorization(item["id"]) == "Bearer top-secret-token"

    public = service.repositories()["items"][0]
    assert public["auth_secret_configured"] is True
    assert "encrypted_auth_secret" not in public
    cleared_payload = RepositoryInput.model_validate(payload.model_dump() | {"auth_type": "none", "auth_secret": ""})
    cleared = service.save_repository(cleared_payload, "admin", item["id"])
    assert cleared["auth_secret_configured"] is False
    assert cleared["auth_username"] == ""
    assert service.mirror_authorization(item["id"]) == ""


def test_basic_mirror_requires_username_and_returns_authorization(service: RepositoryService, monkeypatch):
    monkeypatch.setattr("app.modules.os_repositories.service.validate_mirror_url", lambda *args, **kwargs: ["203.0.113.10"])
    payload = RepositoryInput(
        name="Basic mirror", kind="mirror", format="rpm", distribution="rocky", distribution_version="9",
        architectures=["x86_64"], source_url="https://packages.example/rpm", auth_type="basic",
        auth_username="mirror-user", auth_secret="mirror-pass",
    )
    item = service.save_repository(payload, "admin")
    assert service.mirror_authorization(item["id"]).startswith("Basic ")


def test_authenticated_proxy_is_loopback_only_and_forwards_secret_in_header(monkeypatch):
    received: dict[str, str] = {}
    monkeypatch.setattr("app.modules.os_repositories.auth_proxy.validate_mirror_url", lambda *args, **kwargs: ["127.0.0.1"])

    class SourceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received["path"] = self.path
            received["authorization"] = self.headers.get("Authorization", "")
            body = b"repository metadata"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    source = ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
    thread = threading.Thread(target=source.serve_forever, daemon=True)
    thread.start()
    try:
        source_url = f"http://127.0.0.1:{source.server_port}/repo/"
        with authenticated_mirror_proxy(
            source_url,
            "Bearer private-token",
            allow_private_network=True,
            allow_private_http=True,
        ) as proxy_url:
            assert proxy_url.startswith("http://127.0.0.1:")
            with urllib.request.urlopen(f"{proxy_url}metadata", timeout=5) as response:  # noqa: S310
                assert response.read() == b"repository metadata"
        assert received == {"path": "/repo/metadata", "authorization": "Bearer private-token"}
    finally:
        source.shutdown()
        source.server_close()
        thread.join(timeout=5)


def test_authenticated_mirror_commands_contain_only_ephemeral_proxy_url(service: RepositoryService, monkeypatch, tmp_path: Path):
    repository = {
        "id": "a" * 32,
        "kind": "mirror",
        "format": "apt",
        "architectures": ["amd64"],
        "distribution_version": "24.04",
        "source_url": "https://packages.example/repo",
        "auth_secret_configured": True,
    }
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/aptly")
    monkeypatch.setattr("app.modules.os_repositories.jobs.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    commands = RepositoryJobManager(service)._commands(repository, tmp_path, "http://127.0.0.1:41000/")
    rendered = " ".join(part for command in commands for part in command)
    assert "http://127.0.0.1:41000/" in rendered
    assert "packages.example" not in rendered
    assert "private-token" not in rendered


def test_authenticated_proxy_does_not_forward_secret_across_origins(monkeypatch):
    received: dict[str, str] = {}
    monkeypatch.setattr("app.modules.os_repositories.auth_proxy.validate_mirror_url", lambda *args, **kwargs: ["127.0.0.1"])

    class DestinationHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received["authorization"] = self.headers.get("Authorization", "")
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    destination = ThreadingHTTPServer(("127.0.0.1", 0), DestinationHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/metadata")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (source, destination)]
    for thread in threads:
        thread.start()
    try:
        with authenticated_mirror_proxy(
            f"http://127.0.0.1:{source.server_port}/repo/",
            "Bearer private-token",
            allow_private_network=True,
            allow_private_http=True,
        ) as proxy_url:
            with urllib.request.urlopen(f"{proxy_url}metadata", timeout=5) as response:  # noqa: S310
                assert response.status == 204
        assert received["authorization"] == ""
    finally:
        for server in (source, destination):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


def test_mirror_url_rejects_credentials_loopback_and_unapproved_private_network():
    def resolver(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    with pytest.raises(ValueError, match="forbidden"):
        validate_mirror_url("https://mirror.example/repo", allow_private_network=False, allow_private_http=False, resolver=resolver)
    with pytest.raises(ValueError, match="credentials"):
        validate_mirror_url("https://user:pass@mirror.example/repo", allow_private_network=False, allow_private_http=False, resolver=resolver)

    def private(*args, **kwargs):
        return [(2, 1, 6, "", ("10.10.0.4", 443))]

    with pytest.raises(ValueError, match="private"):
        validate_mirror_url("https://mirror.example/repo", allow_private_network=False, allow_private_http=False, resolver=private)
    assert validate_mirror_url("https://mirror.example/repo", allow_private_network=True, allow_private_http=False, resolver=private) == ["10.10.0.4"]


def test_managed_path_rejects_traversal(tmp_path: Path):
    with pytest.raises(ValueError, match="escapes"):
        managed_path(tmp_path / "content", "../outside")


def test_upload_rejects_fake_deb(service: RepositoryService):
    repository = service.save_repository(local_payload(), "admin")
    with pytest.raises(ValueError, match="does not match"):
        service.upload_package(repository["id"], "fake.deb", io.BytesIO(b"not a package"), "admin")


def test_upload_rejects_fake_rpm_and_enforces_limit(service: RepositoryService):
    rpm = service.save_repository(
        RepositoryInput(name="Rocky", kind="local", format="rpm", distribution="rocky", distribution_version="9", architectures=["x86_64"]), "admin"
    )
    with pytest.raises(ValueError, match="does not match"):
        service.upload_package(rpm["id"], "fake.rpm", io.BytesIO(b"not an rpm"), "admin")
    apt = service.save_repository(local_payload(name="Small upload"), "admin")
    service.save_settings(SettingsInput(upload_limit_mb=1), "admin")
    with pytest.raises(ValueError, match="limit"):
        service.upload_package(apt["id"], "large.deb", io.BytesIO(b"x" * (1024 * 1024 + 1)), "admin")


def test_upload_is_content_addressed_and_checksum_verified(service: RepositoryService, monkeypatch):
    repository = service.save_repository(local_payload(), "admin")
    metadata = {
        "name": "webnas-demo",
        "version": "1.0",
        "release": "",
        "epoch": "",
        "architecture": "amd64",
        "maintainer": "WebNAS",
        "description": "Demo",
        "dependencies": [],
        "conflicts": [],
        "vendor": "",
        "license": "MIT",
    }
    monkeypatch.setattr(service, "_inspect_package", lambda path, expected: metadata)
    content = b"!<arch>\ncontrolled package bytes"
    item = service.upload_package(repository["id"], "demo.deb", io.BytesIO(content), "admin")
    assert item["sha256"] == __import__("hashlib").sha256(content).hexdigest()
    assert (service.root / item["relative_path"]).read_bytes() == content


def test_filter_preview_and_versioned_rule(service: RepositoryService, monkeypatch):
    repository = service.save_repository(local_payload(), "admin")
    monkeypatch.setattr(
        service,
        "_inspect_package",
        lambda *args: {
            "name": "demo-dbg",
            "version": "1",
            "release": "",
            "epoch": "",
            "architecture": "amd64",
            "maintainer": "",
            "description": "",
            "dependencies": [],
            "conflicts": [],
            "vendor": "",
            "license": "",
        },
    )
    service.upload_package(repository["id"], "demo.deb", io.BytesIO(b"!<arch>\nx"), "admin")
    rule = FilterRuleInput(name="No debug", exclude_debug=True)
    assert service.filter_preview(repository["id"], rule)["rejected"] == 1
    assert service.save_filter(repository["id"], rule, "admin")["version"] == 1


def test_filter_version_bounds_and_regex_complexity(service: RepositoryService, monkeypatch):
    repository = service.save_repository(local_payload(), "admin")
    versions = iter(["1.9", "1.10"])
    monkeypatch.setattr(
        service,
        "_inspect_package",
        lambda *args: {
            "name": "demo",
            "version": next(versions),
            "release": "",
            "epoch": "",
            "architecture": "amd64",
            "maintainer": "",
            "description": "",
            "dependencies": [],
            "conflicts": [],
            "vendor": "",
            "license": "",
        },
    )
    service.upload_package(repository["id"], "one.deb", io.BytesIO(b"!<arch>\none"), "admin")
    service.upload_package(repository["id"], "two.deb", io.BytesIO(b"!<arch>\ntwo"), "admin")
    assert service.filter_preview(repository["id"], FilterRuleInput(name="latest", latest_versions=1))["included"] == 1
    assert service.filter_preview(repository["id"], FilterRuleInput(name="minimum", minimum_version="1.10"))["included"] == 1
    with pytest.raises(ValueError, match="complex"):
        FilterRuleInput(name="unsafe", include_regex="(a|aa)+$")


def test_snapshot_is_immutable_and_blocks_package_deletion(service: RepositoryService, monkeypatch):
    repository = service.save_repository(local_payload(), "admin")
    monkeypatch.setattr(
        service,
        "_inspect_package",
        lambda *args: {
            "name": "demo",
            "version": "1",
            "release": "",
            "epoch": "",
            "architecture": "amd64",
            "maintainer": "",
            "description": "",
            "dependencies": [],
            "conflicts": [],
            "vendor": "",
            "license": "",
        },
    )
    package = service.upload_package(repository["id"], "demo.deb", io.BytesIO(b"!<arch>\nx"), "admin")
    snapshot = service.create_snapshot(repository["id"], SnapshotInput(name="stable-1"), "admin")
    assert snapshot["package_count"] == 1
    with pytest.raises(ValueError, match="immutable"):
        service.delete_package(package["id"], "admin")


def test_snapshot_comparison_reports_added_package(service: RepositoryService, monkeypatch):
    repository = service.save_repository(local_payload(), "admin")
    first = service.create_snapshot(repository["id"], SnapshotInput(name="empty"), "admin")
    monkeypatch.setattr(
        service,
        "_inspect_package",
        lambda *args: {
            "name": "demo",
            "version": "1",
            "release": "",
            "epoch": "",
            "architecture": "amd64",
            "maintainer": "",
            "description": "",
            "dependencies": [],
            "conflicts": [],
            "vendor": "",
            "license": "",
        },
    )
    service.upload_package(repository["id"], "demo.deb", io.BytesIO(b"!<arch>\nx"), "admin")
    second = service.create_snapshot(repository["id"], SnapshotInput(name="filled"), "admin")
    assert [item["name"] for item in service.compare_snapshots(first["id"], second["id"])["added"]] == ["demo"]


def test_snapshot_retention_removes_old_unpublished_snapshots(service: RepositoryService):
    repository = service.save_repository(local_payload(retention_count=1), "admin")
    first = service.create_snapshot(repository["id"], SnapshotInput(name="first"), "admin")
    second = service.create_snapshot(repository["id"], SnapshotInput(name="second"), "admin")
    assert service.snapshot(first["id"]) is None
    assert service.snapshot(second["id"])["name"] == "second"


def test_apt_publication_is_standard_atomic_and_can_rollback(service: RepositoryService, monkeypatch):
    repository = service.save_repository(local_payload(), "admin")
    monkeypatch.setattr(
        service,
        "_inspect_package",
        lambda *args: {
            "name": "demo",
            "version": "1",
            "release": "",
            "epoch": "",
            "architecture": "amd64",
            "maintainer": "WebNAS",
            "description": "Demo",
            "dependencies": [],
            "conflicts": [],
            "vendor": "",
            "license": "MIT",
        },
    )
    service.upload_package(repository["id"], "demo.deb", io.BytesIO(b"!<arch>\nfirst"), "admin")
    first = service.create_snapshot(repository["id"], SnapshotInput(name="first"), "admin")
    if os.name == "nt":
        monkeypatch.setattr(os, "symlink", lambda source, target, target_is_directory=False: shutil.copytree(source, target))
    channel = next(item for item in service.channels() if item["repository_id"] == repository["id"] and item["name"] == "testing")
    service.publish(repository["id"], ChannelName.testing, first["id"], "admin")
    service.publish(repository["id"], ChannelName.production, first["id"], "admin")
    published = service.root / "published" / repository["id"] / "testing"
    assert (published / "dists" / "24.04" / "Release").is_file()
    assert list((published / "pool" / "main").rglob("*.deb"))
    monkeypatch.setattr(
        service,
        "_inspect_package",
        lambda *args: {
            "name": "extra",
            "version": "2",
            "release": "",
            "epoch": "",
            "architecture": "amd64",
            "maintainer": "WebNAS",
            "description": "Extra",
            "dependencies": [],
            "conflicts": [],
            "vendor": "",
            "license": "MIT",
        },
    )
    service.upload_package(repository["id"], "extra.deb", io.BytesIO(b"!<arch>\nsecond"), "admin")
    second = service.create_snapshot(repository["id"], SnapshotInput(name="second"), "admin")
    with pytest.raises(ValueError, match="currently published in Testing"):
        service.publish(repository["id"], ChannelName.production, second["id"], "admin")
    service.publish(repository["id"], ChannelName.testing, second["id"], "admin")
    rolled_back = service.rollback_channel(channel["id"], "admin")
    assert rolled_back["snapshot_id"] == first["id"]


def test_cancel_and_retry_are_durable(service: RepositoryService):
    repository = service.save_repository(local_payload(), "admin")
    job_id = object_id()
    service.store.execute(
        "INSERT INTO repository_sync_jobs(id,repository_id,operation,status,stage,progress,current_item,downloaded_count,downloaded_bytes,speed_bps,warnings_json,error,created_at,created_by) VALUES(?,?,'sync','queued','queued',0,'',0,0,0,'[]','',?,?)",
        (job_id, repository["id"], time.time(), "admin"),
    )
    manager = RepositoryJobManager.__new__(RepositoryJobManager)
    manager.service = service
    manager._lock = __import__("threading").RLock()
    manager._processes = {}
    assert manager.cancel(job_id, "admin")["status"] == "cancelled"


def test_restart_marks_running_jobs_interrupted(tmp_path: Path):
    root = tmp_path / "restart"
    service = RepositoryService(root)
    repository = service.save_repository(local_payload(), "admin")
    job_id = object_id()
    service.store.execute(
        "INSERT INTO repository_sync_jobs(id,repository_id,operation,status,stage,progress,current_item,downloaded_count,downloaded_bytes,speed_bps,warnings_json,error,created_at,created_by) VALUES(?,?,'sync','running','downloading',50,'demo',1,1,1,'[]','',?,?)",
        (job_id, repository["id"], time.time(), "admin"),
    )
    restarted = RepositoryStore(root)
    assert restarted.one("SELECT status,stage FROM repository_sync_jobs WHERE id=?", (job_id,)) == {"status": "failed", "stage": "interrupted"}


def test_backup_is_private_checksummed_and_full_remove_is_typed(service: RepositoryService):
    service.save_repository(local_payload(), "admin")
    backup = service.create_backup(BackupInput(confirm=True), "admin")
    assert len(backup["checksum"]) == 64
    with pytest.raises(ValueError, match="typing"):
        service.full_remove("wrong", False, "admin")


def test_private_key_is_encrypted_and_backup_envelope_is_authenticated(service: RepositoryService, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    key = service.save_key(
        SigningKeyInput(name="Release", public_key="-" * 32, private_key="PRIVATE SECRET MATERIAL", passphrase="key password", fingerprint="A" * 40), "admin"
    )
    stored = service.store.one("SELECT encrypted_private_key FROM signing_keys WHERE id=?", (key["id"],))
    assert "PRIVATE SECRET MATERIAL" not in stored["encrypted_private_key"]
    envelope = encrypt_backup_payload(b"private keys", "a-very-long-backup-passphrase")
    assert decrypt_backup_payload(envelope, "a-very-long-backup-passphrase") == b"private keys"
    with pytest.raises(ValueError, match="authentication"):
        decrypt_backup_payload(envelope, "a-different-long-passphrase")


def test_settings_reject_port_conflict(service: RepositoryService):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(ValueError, match="already in use"):
            service.save_settings(SettingsInput(listen_address="127.0.0.1", port=port), "admin")


def test_lifecycle_scripts_use_argument_arrays_and_preserve_data():
    module = Path(__file__).parents[1] / "app" / "modules" / "os-repositories"
    install = (module / "install.py").read_text(encoding="utf-8")
    update = (module / "update.py").read_text(encoding="utf-8")
    uninstall = (module / "uninstall.py").read_text(encoding="utf-8")
    assert "shell=False" in install and "shell=False" in update and "shell=False" in uninstall
    assert "rmtree" not in uninstall and "/var/lib/webnas/os-repositories" not in uninstall


def test_cron_schedule_parser_is_bounded_and_predictable():
    timestamp = __import__("datetime").datetime(2026, 8, 3, 12, 0, tzinfo=__import__("datetime").UTC).timestamp()
    assert schedule_matches("@hourly", timestamp)
    assert schedule_matches("0 12 * * 1", timestamp)
    assert not schedule_matches("15 12 * * 1", timestamp)


def test_rbac_role_defaults_follow_the_security_model():
    operator = ROLE_PERMISSIONS[Role.operator]
    auditor = ROLE_PERMISSIONS[Role.auditor]
    assert Permission.OS_REPOSITORIES_SYNC.value in operator
    assert Permission.OS_REPOSITORIES_CHANNELS_PROMOTE.value not in operator
    assert Permission.OS_REPOSITORIES_KEYS_MANAGE.value not in operator
    assert Permission.OS_REPOSITORIES_VIEW.value in auditor
    assert Permission.OS_REPOSITORIES_MANAGE.value not in auditor
