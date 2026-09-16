from __future__ import annotations

import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .offline_models import OfflineBundleType
from .offline_service import BUNDLE_FORMAT_VERSION, MAX_ARCHIVE_FILES, MAX_EXTRACTED_BYTES, MAX_MANIFEST_BYTES, OfflineRepositoryService

_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_ARCH_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,32}$")
_DIST_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DIST_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _int_field(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"bundle manifest field {name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"bundle manifest field {name} is out of range")
    return value


def _float_field(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"bundle manifest field {name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"bundle manifest field {name} is out of range")
    return parsed


def _string_field(value: Any, name: str, *, pattern: re.Pattern[str] | None = None, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise ValueError(f"bundle manifest field {name} must be a string")
    if not value or len(value) > maximum or (pattern is not None and not pattern.fullmatch(value)):
        raise ValueError(f"bundle manifest field {name} is invalid")
    return value


def _relative_path(value: Any, name: str) -> str:
    text = _string_field(value, name, maximum=1024)
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or "\\" in text or "\x00" in text or not pure.parts:
        raise ValueError(f"bundle manifest field {name} contains an unsafe path")
    return text


def validate_offline_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be an object")

    _int_field(manifest.get("bundle_format_version"), "bundle_format_version", minimum=1, maximum=BUNDLE_FORMAT_VERSION)
    if manifest.get("bundle_format_version") != BUNDLE_FORMAT_VERSION:
        raise ValueError("unsupported offline bundle format version")

    _string_field(manifest.get("bundle_id"), "bundle_id", pattern=_ID_RE, maximum=32)
    _string_field(manifest.get("repository_id"), "repository_id", pattern=_ID_RE, maximum=32)
    _string_field(manifest.get("snapshot_id"), "snapshot_id", pattern=_ID_RE, maximum=32)
    _string_field(manifest.get("repository_name"), "repository_name", maximum=128)
    _string_field(manifest.get("distribution"), "distribution", pattern=_DIST_RE, maximum=64)
    _string_field(manifest.get("distribution_version"), "distribution_version", pattern=_DIST_VERSION_RE, maximum=64)
    _string_field(manifest.get("architecture"), "architecture", pattern=_ARCH_RE, maximum=32)

    repository_format = manifest.get("format")
    if repository_format not in {"apt", "rpm"}:
        raise ValueError("bundle repository format is invalid")

    bundle_type = manifest.get("bundle_type")
    allowed_bundle_types = {item.value for item in OfflineBundleType}
    if bundle_type not in allowed_bundle_types:
        raise ValueError("bundle type is invalid")

    base_snapshot_id = manifest.get("base_snapshot_id")
    if base_snapshot_id is not None:
        _string_field(base_snapshot_id, "base_snapshot_id", pattern=_ID_RE, maximum=32)
    if bundle_type == OfflineBundleType.delta.value and base_snapshot_id is None:
        raise ValueError("delta bundle requires a base snapshot identifier")

    _float_field(manifest.get("created_at"), "created_at")

    files = manifest.get("files")
    if not isinstance(files, list) or len(files) > MAX_ARCHIVE_FILES:
        raise ValueError("bundle file manifest is invalid")
    seen_files: set[str] = set()
    declared_bytes = 0
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise ValueError("bundle file manifest entry is invalid")
        path = _relative_path(item.get("path"), f"files[{index}].path")
        folded = path.casefold()
        if folded in seen_files:
            raise ValueError("bundle file manifest contains duplicate paths")
        seen_files.add(folded)
        declared_bytes += _int_field(item.get("size"), f"files[{index}].size", minimum=0, maximum=MAX_EXTRACTED_BYTES)
        if declared_bytes > MAX_EXTRACTED_BYTES:
            raise ValueError("bundle file manifest exceeds the maximum extracted size")
        _string_field(item.get("sha256"), f"files[{index}].sha256", pattern=_SHA256_RE, maximum=64)

    packages = manifest.get("packages")
    if not isinstance(packages, list) or len(packages) > MAX_ARCHIVE_FILES:
        raise ValueError("bundle package metadata is invalid")
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise ValueError("bundle package metadata entry is invalid")
        _relative_path(package.get("bundle_path"), f"packages[{index}].bundle_path")
        _string_field(package.get("sha256"), f"packages[{index}].sha256", pattern=_SHA256_RE, maximum=64)
        _string_field(package.get("name"), f"packages[{index}].name", maximum=256)
        _string_field(package.get("version"), f"packages[{index}].version", maximum=256)
        _string_field(package.get("architecture"), f"packages[{index}].architecture", maximum=64)

    package_count = _int_field(manifest.get("package_count"), "package_count", minimum=0, maximum=MAX_ARCHIVE_FILES)
    if package_count != len(packages):
        raise ValueError("bundle package_count does not match package metadata")

    target_packages = manifest.get("target_packages")
    if not isinstance(target_packages, list) or len(target_packages) > MAX_ARCHIVE_FILES:
        raise ValueError("bundle target package metadata is invalid")
    for index, descriptor in enumerate(target_packages):
        if not isinstance(descriptor, dict):
            raise ValueError("bundle target package metadata entry is invalid")
        _string_field(descriptor.get("sha256"), f"target_packages[{index}].sha256", pattern=_SHA256_RE, maximum=64)
        if "name" in descriptor:
            _string_field(descriptor.get("name"), f"target_packages[{index}].name", maximum=256)

    target_count = manifest.get("target_package_count")
    if target_count is not None:
        parsed_target_count = _int_field(target_count, "target_package_count", minimum=0, maximum=MAX_ARCHIVE_FILES)
        if parsed_target_count != len(target_packages):
            raise ValueError("bundle target_package_count does not match target package metadata")

    return manifest


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("bundle manifest is missing or oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("bundle manifest is invalid JSON") from error
    return validate_offline_manifest(value)


def install_offline_hardening() -> None:
    if getattr(OfflineRepositoryService, "_runtime_audit_10_hardened", False):
        return
    original: Callable[[OfflineRepositoryService, Path], dict[str, Any]] = OfflineRepositoryService._verify_extracted

    def hardened(self: OfflineRepositoryService, root: Path) -> dict[str, Any]:
        _load_manifest(root)
        return original(self, root)

    OfflineRepositoryService._verify_extracted = hardened  # type: ignore[method-assign]
    setattr(OfflineRepositoryService, "_runtime_audit_10_hardened", True)
