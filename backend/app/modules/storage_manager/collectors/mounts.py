from __future__ import annotations

from pathlib import Path
from typing import Any

from ....local_disks import NETWORK_FILESYSTEMS
from ..service import _clean_text, _mountpoint_is_protected, _number, _safe_device_path, _safe_mount_path
from .probe import SWAPON_ARGS, StorageReadOnlyProbe


def _bytes_value(value: Any) -> int:
    text = str(value or "").strip().lstrip("<>")
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def _decode_fstab_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\043", "#")
        .replace("\\134", "\\")
    )


def _flatten_devices(devices: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    def visit(item: dict[str, Any]) -> None:
        flattened.append(item)
        for child in item.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for item in devices or []:
        if isinstance(item, dict):
            visit(item)
    return flattened


class MountCollector:
    def __init__(self, probe: StorageReadOnlyProbe, *, fstab_path: Path = Path("/etc/fstab")) -> None:
        self.probe = probe
        self.fstab_path = fstab_path

    def swap(self) -> list[dict[str, Any]]:
        result = self.probe.run("swapon", SWAPON_ARGS)
        if result is None or result.returncode != 0:
            return []
        entries: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            fields = line.split(None, 4)
            if len(fields) != 5:
                continue
            name, kind, size, used, priority = fields
            safe_name = _safe_device_path(name) if name.startswith("/dev/") else _safe_mount_path(name)
            if safe_name is None:
                continue
            entries.append(
                {
                    "name": safe_name,
                    "type": _clean_text(kind, 32),
                    "size": _bytes_value(size),
                    "used": _bytes_value(used),
                    "priority": int(_number(priority) or 0),
                }
            )
        return entries

    @staticmethod
    def _source_aliases(devices: list[dict[str, Any]] | None) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for item in _flatten_devices(devices):
            path = _safe_device_path(item.get("path"))
            if path is None:
                continue
            aliases[path] = path
            values = {
                "UUID": _clean_text(item.get("uuid"), 160),
                "LABEL": _clean_text(item.get("label"), 160),
                "PARTUUID": _clean_text(item.get("partuuid"), 160),
            }
            for prefix, value in values.items():
                if value:
                    aliases[f"{prefix}={value}"] = path
        return aliases

    @staticmethod
    def parse_fstab(
        content: str,
        filesystems: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        live = {
            str(item.get("mount_point")): item
            for item in filesystems or []
            if isinstance(item, dict) and item.get("mount_point")
        }
        aliases = MountCollector._source_aliases(devices)
        entries: list[dict[str, Any]] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                line = line.split("#", 1)[0].rstrip()
            fields = line.split()
            if len(fields) < 4:
                continue
            source = _decode_fstab_field(fields[0])
            target = _safe_mount_path(_decode_fstab_field(fields[1]))
            if target is None:
                continue
            fs_type = _clean_text(fields[2], 64)
            options = [_clean_text(item, 128) for item in fields[3].split(",") if _clean_text(item, 128)]
            current = live.get(target)
            noauto = "noauto" in options
            network = fs_type in NETWORK_FILESYSTEMS or source.startswith("//") or ":/" in source
            resolved_source = aliases.get(source, source if _safe_device_path(source) else "")
            current_source = _clean_text(current.get("source"), 512) if current else ""
            source_matches = bool(
                current
                and (
                    network
                    or current_source == source
                    or (resolved_source and current_source == resolved_source)
                )
            )
            entries.append(
                {
                    "source": _clean_text(source, 512),
                    "resolved_source": _clean_text(resolved_source, 512),
                    "mount_point": target,
                    "filesystem": fs_type,
                    "options": options,
                    "dump": int(_number(fields[4]) or 0) if len(fields) > 4 else 0,
                    "pass": int(_number(fields[5]) or 0) if len(fields) > 5 else 0,
                    "active": current is not None,
                    "current_source": current_source,
                    "current_filesystem": _clean_text(current.get("filesystem"), 64) if current else "",
                    "source_matches": source_matches,
                    "source_mismatch": bool(current and not source_matches and not network),
                    "network": network,
                    "noauto": noauto,
                    "automount": "x-systemd.automount" in options,
                    "protected": _mountpoint_is_protected(target),
                    "state": "active" if current else "disabled" if noauto else "inactive",
                }
            )
        return entries

    def fstab(
        self,
        filesystems: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            content = self.fstab_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.parse_fstab(content, filesystems, devices)

    def snapshot(
        self,
        *,
        filesystems: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "read_only": True,
            "active": filesystems or [],
            "persistent": self.fstab(filesystems, devices),
            "swap": self.swap(),
        }
