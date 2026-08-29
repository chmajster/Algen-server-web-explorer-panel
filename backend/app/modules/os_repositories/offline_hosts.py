from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..hosts_manager.public import registry as hosts_registry
from .models import RepositoryFormat
from .offline_models import OfflineHostGroupTargetInput, OfflineTargetInput
from .offline_service import OfflineRepositoryService, offline_service


class OfflineHostsIntegration:
    def __init__(self, service: OfflineRepositoryService | None = None) -> None:
        self.service = service or offline_service()

    @staticmethod
    def _host_identity(host: dict[str, Any]) -> tuple[str, str, str]:
        facts = host.get("facts") if isinstance(host.get("facts"), dict) else {}
        report = host.get("latest_report") if isinstance(host.get("latest_report"), dict) else {}
        basic = report.get("basic") if isinstance(report.get("basic"), dict) else {}
        distribution = str(host.get("distribution") or basic.get("distribution") or facts.get("distribution") or "").strip().lower()
        version = str(host.get("system_version") or basic.get("system_version") or facts.get("distribution_version") or "").strip()
        architecture = str(basic.get("architecture") or facts.get("architecture") or host.get("architecture") or "").strip().lower()
        return distribution, version, architecture

    @staticmethod
    def _architecture_for_repository(architecture: str, repository_format: str) -> str:
        value = architecture.casefold()
        if repository_format == RepositoryFormat.apt.value:
            return {
                "x86_64": "amd64",
                "x64": "amd64",
                "aarch64": "arm64",
                "armv8": "arm64",
            }.get(value, value)
        return {
            "amd64": "x86_64",
            "x64": "x86_64",
            "arm64": "aarch64",
            "armv8": "aarch64",
        }.get(value, value)

    @staticmethod
    def _version_matches(host_version: str, repository_version: str) -> bool:
        if not host_version:
            return False
        left = host_version.casefold()
        right = repository_version.casefold()
        return left == right or left.startswith(f"{right}.") or left.startswith(f"{right} ") or left.startswith(f"{right}-")

    def _group(self, group_id: str) -> dict[str, Any]:
        group = next((item for item in hosts_registry().list_groups() if str(item.get("id")) == group_id), None)
        if not group:
            raise KeyError("Hosts Manager group not found")
        return group

    def compatibility(self, group_id: str, repository_ids: list[str]) -> dict[str, Any]:
        group = self._group(group_id)
        repositories: list[dict[str, Any]] = []
        for repository_id in list(dict.fromkeys(repository_ids)):
            repository = self.service.base.repository(repository_id)
            if not repository:
                raise KeyError(f"repository not found: {repository_id}")
            repositories.append(repository)

        signatures: Counter[str] = Counter()
        compatible: list[dict[str, Any]] = []
        incompatible: list[dict[str, Any]] = []
        for host_id in group.get("host_ids", []):
            host = hosts_registry().host(str(host_id))
            if not host:
                incompatible.append({"host_id": str(host_id), "reason": "host not found"})
                continue
            distribution, version, architecture = self._host_identity(host)
            signature = f"{distribution or 'unknown'} {version or 'unknown'} {architecture or 'unknown'}"
            signatures[signature] += 1
            matches: list[dict[str, str]] = []
            for repository in repositories:
                target_architecture = self._architecture_for_repository(architecture, str(repository["format"]))
                if distribution != str(repository["distribution"]).casefold():
                    continue
                if not self._version_matches(version, str(repository["distribution_version"])):
                    continue
                if target_architecture not in repository["architectures"]:
                    continue
                matches.append({"repository_id": str(repository["id"]), "architecture": target_architecture})
            if matches:
                compatible.append(
                    {
                        "host_id": str(host["id"]),
                        "host_name": str(host.get("name") or host["id"]),
                        "distribution": distribution,
                        "distribution_version": version,
                        "architecture": architecture,
                        "matches": matches,
                    }
                )
            else:
                incompatible.append(
                    {
                        "host_id": str(host["id"]),
                        "host_name": str(host.get("name") or host["id"]),
                        "distribution": distribution,
                        "distribution_version": version,
                        "architecture": architecture,
                        "reason": "no compatible repository",
                    }
                )

        return {
            "group_id": group_id,
            "group_name": str(group.get("name") or group_id),
            "total_hosts": len(group.get("host_ids", [])),
            "compatible_hosts": len(compatible),
            "incompatible_hosts": len(incompatible),
            "signatures": [{"signature": key, "count": count} for key, count in sorted(signatures.items())],
            "compatible": compatible,
            "incompatible": incompatible,
        }

    def generate_targets(self, payload: OfflineHostGroupTargetInput, actor: str) -> dict[str, Any]:
        if not payload.confirm:
            raise ValueError("Hosts Manager target generation requires confirmation")
        compatibility = self.compatibility(payload.host_group_id, payload.repository_ids)
        matched: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for host in compatibility["compatible"]:
            first = host["matches"][0]
            matched.setdefault((str(first["repository_id"]), str(first["architecture"])), []).append(host)

        existing = self.service.targets()
        created: list[dict[str, Any]] = []
        for (repository_id, architecture), hosts in matched.items():
            repository = self.service.base.repository(repository_id)
            if not repository:
                continue
            safe_repository_name = re.sub(r"[^A-Za-z0-9_. -]+", "-", str(repository["name"])).strip()[:48]
            target_name = f"{payload.name_prefix} {safe_repository_name} {architecture}"[:128]
            previous = next(
                (
                    item
                    for item in existing
                    if item.get("host_group_id") == payload.host_group_id
                    and item.get("repository_id") == repository_id
                    and item.get("architecture") == architecture
                    and item.get("channel") == payload.channel.value
                ),
                None,
            )
            target = self.service.save_target(
                OfflineTargetInput(
                    name=target_name,
                    repository_id=repository_id,
                    channel=payload.channel,
                    distribution=str(repository["distribution"]),
                    distribution_version=str(repository["distribution_version"]),
                    architecture=architecture,
                    package_names=payload.package_names,
                    include_dependencies=payload.include_dependencies,
                    signing_key_id=repository.get("signing_key_id"),
                    host_group_id=payload.host_group_id,
                ),
                actor,
                str(previous["id"]) if previous else None,
            )
            created.append(target | {"matched_hosts": len(hosts)})

        self.service.base._audit(
            actor,
            "offline_targets_generated_from_hosts_group",
            payload.host_group_id,
            {"targets": len(created), "compatible_hosts": compatibility["compatible_hosts"], "incompatible_hosts": compatibility["incompatible_hosts"]},
        )
        return {"compatibility": compatibility, "targets": created}


def offline_hosts_integration() -> OfflineHostsIntegration:
    return OfflineHostsIntegration()
