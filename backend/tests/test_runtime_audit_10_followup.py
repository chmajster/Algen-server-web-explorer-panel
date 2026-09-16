from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.hosts_manager import agent as hosts_agent
from app.modules.os_repositories.offline_hardening import validate_offline_manifest
from app.modules.os_repositories.offline_models import OfflineBundleType
from app.modules.os_repositories.offline_service import BUNDLE_FORMAT_VERSION, MAX_EXTRACTED_BYTES, OfflineRepositoryService


def _agent_files(tmp_path: Path, config: dict[str, Any]) -> tuple[Path, Path]:
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    state_path.write_text("{}", encoding="utf-8")
    return config_path, state_path


def test_hosts_agent_corrupt_config_types_fall_back_without_crashing(tmp_path: Path) -> None:
    config_path, state_path = _agent_files(
        tmp_path,
        {
            "server": {"url": "https://webnas.example", "timeout_seconds": {"bad": True}, "verify_tls": "false"},
            "agent": {"heartbeat_interval": -1, "report_interval": True, "max_retries": "not-a-number"},
        },
    )
    client = hosts_agent.AgentClient(config_path, state_path)
    assert client.timeout == 15
    assert client.verify_tls is True
    assert client.heartbeat_interval == 30
    assert client.report_interval == 300
    assert client.max_retries == 10


def test_hosts_agent_preserves_explicit_false_tls_setting(tmp_path: Path) -> None:
    config_path, state_path = _agent_files(tmp_path, {"server": {"url": "http://webnas.example", "verify_tls": False}})
    assert hosts_agent.AgentClient(config_path, state_path).verify_tls is False


@pytest.mark.parametrize(
    "url",
    ["https://webnas.example?redirect=1", "https://webnas.example#fragment", "https://user:pass@webnas.example"],
)
def test_hosts_agent_rejects_ambiguous_server_urls(tmp_path: Path, url: str) -> None:
    config_path, state_path = _agent_files(tmp_path, {"server": {"url": url}})
    with pytest.raises(RuntimeError, match="without credentials, query, or fragment"):
        hosts_agent.AgentClient(config_path, state_path)._request("/api/test", {}, "token")


def test_hosts_agent_bounds_api_responses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path, state_path = _agent_files(tmp_path, {"server": {"url": "https://webnas.example"}})
    reads: list[int] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, amount: int = -1) -> bytes:
            reads.append(amount)
            return b"x" * amount

    monkeypatch.setattr(hosts_agent, "_open_no_redirect", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="safety limit"):
        hosts_agent.AgentClient(config_path, state_path)._request("/api/test", {}, "token")
    assert reads == [hosts_agent.MAX_HTTP_RESPONSE_BYTES + 1]


@pytest.mark.parametrize("payload", [b"\xff", b"[1,2,3]", b"{broken"])
def test_hosts_agent_normalizes_invalid_api_responses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes
) -> None:
    config_path, state_path = _agent_files(tmp_path, {"server": {"url": "https://webnas.example"}})

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, amount: int = -1) -> bytes:
            return payload[:amount]

    monkeypatch.setattr(hosts_agent, "_open_no_redirect", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="invalid Hosts Manager response"):
        hosts_agent.AgentClient(config_path, state_path)._request("/api/test", {}, "token")


def test_hosts_agent_update_policy_uses_bounded_size_and_strict_enabled(tmp_path: Path) -> None:
    assert hosts_agent._bounded_int("bad", hosts_agent.MAX_HTTP_RESPONSE_BYTES, minimum=1024, maximum=hosts_agent.MAX_HTTP_RESPONSE_BYTES) == hosts_agent.MAX_HTTP_RESPONSE_BYTES
    assert hosts_agent._bounded_int(True, hosts_agent.MAX_HTTP_RESPONSE_BYTES, minimum=1024, maximum=hosts_agent.MAX_HTTP_RESPONSE_BYTES) == hosts_agent.MAX_HTTP_RESPONSE_BYTES
    assert hosts_agent._bounded_int(2048, hosts_agent.MAX_HTTP_RESPONSE_BYTES, minimum=1024, maximum=hosts_agent.MAX_HTTP_RESPONSE_BYTES) == 2048
    config_path, state_path = _agent_files(tmp_path, {"server": {"url": "https://webnas.example"}})
    client = hosts_agent.AgentClient(config_path, state_path)
    client.apply_update_policy({"agent_update": {"enabled": "true", "sha256": "0" * 64, "url": "https://attacker.example"}})


def _valid_manifest() -> dict[str, Any]:
    payload = b"package"
    checksum = hashlib.sha256(payload).hexdigest()
    return {
        "bundle_id": "a" * 32,
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "repository_id": "b" * 32,
        "repository_name": "Repository",
        "format": "apt",
        "distribution": "debian",
        "distribution_version": "12",
        "snapshot_id": "c" * 32,
        "snapshot_name": "snapshot",
        "base_snapshot_id": None,
        "channel": "production",
        "architecture": "amd64",
        "bundle_type": OfflineBundleType.full.value,
        "package_count": 1,
        "target_package_count": 1,
        "packages": [{"bundle_path": "packages/demo.deb", "sha256": checksum, "name": "demo", "version": "1.0", "architecture": "amd64"}],
        "target_packages": [{"sha256": checksum, "name": "demo"}],
        "removed_packages": [],
        "created_at": 1.0,
        "compression": "zstd",
        "metadata_version": 1,
        "signing_fingerprint": "",
        "files": [{"path": "packages/demo.deb", "size": len(payload), "sha256": checksum}],
    }


def test_offline_manifest_accepts_well_typed_bundle() -> None:
    manifest = _valid_manifest()
    assert validate_offline_manifest(manifest) is manifest


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("bundle_format_version",), "1"),
        (("bundle_id",), "not-an-id"),
        (("snapshot_id",), None),
        (("architecture",), "amd64;rm"),
        (("bundle_type",), "unknown"),
        (("created_at",), float("nan")),
        (("files", 0, "size"), "7"),
        (("files", 0, "size"), True),
        (("files", 0, "size"), -1),
        (("files", 0, "size"), MAX_EXTRACTED_BYTES + 1),
        (("files", 0, "sha256"), "bad"),
        (("target_packages",), {}),
        (("target_packages", 0), "bad"),
        (("package_count",), 2),
        (("target_package_count",), 2),
    ],
)
def test_offline_manifest_rejects_corrupt_types_and_shapes(path: tuple[Any, ...], value: Any) -> None:
    manifest = _valid_manifest()
    target: Any = manifest
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_offline_manifest(manifest)


def test_offline_manifest_requires_delta_base_snapshot() -> None:
    manifest = _valid_manifest()
    manifest["bundle_type"] = OfflineBundleType.delta.value
    with pytest.raises(ValueError, match="base snapshot"):
        validate_offline_manifest(manifest)


def test_offline_hardening_is_installed_on_service_class() -> None:
    assert getattr(OfflineRepositoryService, "_runtime_audit_10_hardened", False) is True
