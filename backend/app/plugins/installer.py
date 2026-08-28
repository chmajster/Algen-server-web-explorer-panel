from __future__ import annotations

import hashlib

from .models import CHECKSUM_RE, SHA_RE, PluginInstallMetadata


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class PluginInstaller:
    """Integrity metadata boundary; transport/extraction remains provider-specific."""

    @staticmethod
    def installation_metadata(*, resolved_commit: str, artifact: bytes, installed_version: str) -> PluginInstallMetadata:
        if not SHA_RE.fullmatch(resolved_commit):
            raise ValueError("resolved commit must be a full 40-character SHA")
        checksum = sha256_bytes(artifact)
        if not CHECKSUM_RE.fullmatch(checksum):
            raise ValueError("artifact checksum could not be calculated")
        return PluginInstallMetadata(resolved_commit=resolved_commit.lower(), checksum_sha256=checksum, installed_version=installed_version)
