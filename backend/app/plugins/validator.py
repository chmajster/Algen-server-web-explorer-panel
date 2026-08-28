from __future__ import annotations

import re

from fastapi import HTTPException

from .. import __version__ as ALGEN_VERSION
from .models import CHECKSUM_RE, GITHUB_URL_RE, PLUGIN_ID_RE, REF_RE, SEMVER_RE, SHA_RE, PluginManifest, StorePlugin


SAFE_TEXT_RE = re.compile(r"^[^\r\n\[\]]{0,200}$")


def _semver_tuple(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise ValueError("invalid semantic version")
    return tuple(int(match.group(index)) for index in (1, 2, 3))


def compatible_with_algen(minimum: str, current: str = ALGEN_VERSION) -> bool:
    return _semver_tuple(current) >= _semver_tuple(minimum)


class PluginValidator:
    def validate_manifest(self, manifest: PluginManifest) -> PluginManifest:
        if manifest.schema_version != 1:
            raise ValueError(f"unsupported plugin schema version: {manifest.schema_version}")
        if not compatible_with_algen(manifest.min_algen_version):
            raise ValueError(f"plugin requires Algen >= {manifest.min_algen_version}")
        return manifest

    def validate_store_plugin(self, plugin: StorePlugin) -> StorePlugin:
        plugin.name = plugin.name.strip()
        if not plugin.name or not SAFE_TEXT_RE.fullmatch(plugin.name):
            raise HTTPException(400, "Invalid plugin name")
        plugin.github_url = plugin.github_url.strip().rstrip("/")
        if not GITHUB_URL_RE.fullmatch(plugin.github_url):
            raise HTTPException(400, "Plugin URL must be an https://github.com/owner/repo link")
        if plugin.id and not PLUGIN_ID_RE.fullmatch(plugin.id):
            raise HTTPException(400, "Invalid plugin id")
        plugin.branch = plugin.branch.strip() or "main"
        if not REF_RE.fullmatch(plugin.branch):
            raise HTTPException(400, "Invalid plugin branch/ref")
        plugin.source_ref = plugin.source_ref.strip() or plugin.branch
        if not REF_RE.fullmatch(plugin.source_ref):
            raise HTTPException(400, "Invalid plugin source ref")
        if not SEMVER_RE.fullmatch(plugin.version):
            raise HTTPException(400, "Invalid plugin version")
        for version in (plugin.installed_version, plugin.available_version, plugin.min_algen_version):
            if version is not None and not SEMVER_RE.fullmatch(version):
                raise HTTPException(400, "Invalid plugin semantic version")
        if not compatible_with_algen(plugin.min_algen_version):
            raise HTTPException(409, f"Plugin requires Algen >= {plugin.min_algen_version}")
        if plugin.resolved_commit and not SHA_RE.fullmatch(plugin.resolved_commit):
            raise HTTPException(400, "Invalid plugin commit SHA")
        if plugin.checksum_sha256 and not CHECKSUM_RE.fullmatch(plugin.checksum_sha256):
            raise HTTPException(400, "Invalid plugin checksum")
        if len(plugin.codex_instructions) > 8000:
            raise HTTPException(400, "Codex instructions are too long")
        manifest = PluginManifest(
            schema_version=plugin.schema_version,
            id=plugin.id or "placeholder",
            name=plugin.name,
            version=plugin.version,
            publisher=plugin.publisher,
            description=plugin.description,
            repository=plugin.github_url,
            min_algen_version=plugin.min_algen_version,
            entrypoint=plugin.entrypoint,
            capabilities=plugin.capabilities,
            permissions=plugin.permissions,
        )
        if plugin.id:
            self.validate_manifest(manifest)
        return plugin
