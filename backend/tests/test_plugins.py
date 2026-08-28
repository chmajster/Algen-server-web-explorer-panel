from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.plugins.installer import PluginInstaller
from app.plugins.models import PluginManifest, PluginTrust, StorePlugin
from app.plugins.repository import PluginRepository
from app.plugins.service import PluginService
from app.plugins.validator import PluginValidator


def manifest(**overrides):
    payload = {
        "schema_version": 1,
        "id": "demo-plugin",
        "name": "Demo Plugin",
        "version": "1.2.3",
        "publisher": "example",
        "description": "demo",
        "repository": "https://github.com/example/demo-plugin",
        "min_algen_version": "0.1.0",
        "entrypoint": "demo_plugin:register",
        "capabilities": ["filesystem.read", "network.access"],
        "permissions": ["modules.view"],
    }
    payload.update(overrides)
    return payload


def test_valid_manifest_and_declared_capabilities():
    validated = PluginValidator().validate_manifest(PluginManifest.model_validate(manifest()))
    assert validated.version == "1.2.3"
    assert validated.capabilities == ["filesystem.read", "network.access"]


@pytest.mark.parametrize("version", ["1", "1.2", "v1.2.3", "1.02.3"])
def test_invalid_semver_is_rejected(version):
    with pytest.raises(ValueError):
        PluginManifest.model_validate(manifest(version=version))


def test_unsupported_schema_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        PluginValidator().validate_manifest(PluginManifest.model_validate(manifest(schema_version=2)))


def test_incompatible_algen_version_is_rejected():
    with pytest.raises(ValueError, match="requires Algen"):
        PluginValidator().validate_manifest(PluginManifest.model_validate(manifest(min_algen_version="99.0.0")))


def test_commit_sha_and_checksum_are_persisted(tmp_path):
    repository = PluginRepository(tmp_path / "plugins.sqlite3")
    metadata = PluginInstaller.installation_metadata(resolved_commit="a" * 40, artifact=b"plugin archive", installed_version="1.2.3")
    plugin = StorePlugin(
        id="demo-plugin", name="Demo", github_url="https://github.com/example/demo-plugin", version="1.2.3",
        installed_version=metadata.installed_version, available_version="1.2.3", resolved_commit=metadata.resolved_commit,
        checksum_sha256=metadata.checksum_sha256, trust=PluginTrust.trusted, capabilities=["filesystem.read"], credential_id="cred-demo",
    )
    repository.upsert(plugin)
    reopened = PluginRepository(repository.path).get("demo-plugin")
    assert reopened and reopened.resolved_commit == "a" * 40
    assert reopened.checksum_sha256 == metadata.checksum_sha256
    assert reopened.trust == PluginTrust.trusted
    assert reopened.credential_id == "cred-demo"
    assert not hasattr(reopened, "password") and not hasattr(reopened, "token")


def test_legacy_plugin_json_is_migrated_without_secrets(tmp_path):
    legacy = tmp_path / "apps" / "store_plugins.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"plugins": [{
        "id": "legacy-plugin", "name": "Legacy", "github_url": "https://github.com/example/legacy-plugin",
        "branch": "main", "enabled": True, "codex_instructions": "Inspect", "created_at": 1, "updated_at": 2,
    }]}), encoding="utf-8")
    repository = PluginRepository(tmp_path / "plugins.sqlite3", legacy_path=legacy)
    migrated = repository.get("legacy-plugin")
    assert migrated and migrated.version == "0.0.0"
    assert migrated.source_ref == "main"
    assert migrated.trust == PluginTrust.unverified


def test_store_plugin_rejects_secret_payload_and_invalid_repository():
    with pytest.raises(ValueError):
        StorePlugin.model_validate({"name": "Demo", "github_url": "https://github.com/example/demo", "password": "secret"})
    plugin = StorePlugin(name="Demo", github_url="https://example.com/demo")
    with pytest.raises(HTTPException):
        PluginValidator().validate_store_plugin(plugin)


def test_service_audits_create_enable_trust_and_remove(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr("app.plugins.service.record_activity", lambda category, action, actor, **kwargs: events.append(action))
    service = PluginService(PluginRepository(tmp_path / "plugins.sqlite3"))
    created = service.create(StorePlugin(name="Demo", github_url="https://github.com/example/demo"), "admin")
    updated = created.model_copy(update={"enabled": False, "trust": PluginTrust.trusted})
    service.update(created.id, updated, "admin")
    service.delete(created.id, "admin")
    assert "plugin installed" in events
    assert "plugin disabled" in events
    assert "plugin trust changed" in events
    assert "plugin removed" in events
