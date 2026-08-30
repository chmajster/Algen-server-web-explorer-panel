from __future__ import annotations

import json
from typing import Any

from ..service import StorageInventoryService, _clean_text, _integer, _number, _safe_device_path, _safe_mount_path, _mountpoint_is_protected


LSBLK_ARGS = (
    "--json",
    "--bytes",
    "--output",
    "NAME,KNAME,PATH,TYPE,SIZE,FSTYPE,FSVER,LABEL,UUID,PARTUUID,MOUNTPOINTS,RO,RM,HOTPLUG,ROTA,MODEL,SERIAL,TRAN,PKNAME,PARTTYPE,PARTLABEL",
)


def _smart_raw_attribute(payload: dict[str, Any], attribute_id: int) -> int | None:
    attributes = payload.get("ata_smart_attributes")
    table = attributes.get("table") if isinstance(attributes, dict) else None
    if not isinstance(table, list):
        return None
    for item in table:
        if not isinstance(item, dict) or _integer(item.get("id"), -1) != attribute_id:
            continue
        raw = item.get("raw")
        value = raw.get("value") if isinstance(raw, dict) else None
        return _integer(value) if value is not None else None
    return None


class ExtendedInventoryCollector:
    """Additive, read-only inventory on top of the stable StorageInventoryService API."""

    def __init__(self, inventory: StorageInventoryService) -> None:
        self.inventory = inventory

    @staticmethod
    def parse_lsblk(payload: str) -> list[dict[str, Any]]:
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        roots = decoded.get("blockdevices") if isinstance(decoded, dict) else None
        if not isinstance(roots, list):
            return []

        def normalize(raw: Any) -> dict[str, Any] | None:
            if not isinstance(raw, dict):
                return None
            path = _safe_device_path(raw.get("path"))
            if path is None:
                return None
            raw_mounts = raw.get("mountpoints")
            if not isinstance(raw_mounts, list):
                single = raw.get("mountpoint")
                raw_mounts = [single] if single else []
            mounts = [point for item in raw_mounts if (point := _safe_mount_path(item)) is not None]
            children = [child for item in raw.get("children") or [] if (child := normalize(item)) is not None]
            protected = any(_mountpoint_is_protected(point) for point in mounts) or any(bool(child["protected"]) for child in children)
            device_type = _clean_text(raw.get("type"), 32)
            filesystem = _clean_text(raw.get("fstype"), 64)
            rotational_raw = raw.get("rota")
            rotational = bool(_integer(rotational_raw)) if rotational_raw is not None else None
            transport = _clean_text(raw.get("tran"), 32)
            if transport == "nvme" or path.startswith("/dev/nvme"):
                media_type = "nvme"
            elif device_type == "disk" and rotational is False:
                media_type = "ssd"
            elif device_type == "disk" and rotational is True:
                media_type = "hdd"
            else:
                media_type = "unknown"
            device_mapper = path.startswith("/dev/mapper/") or device_type in {"crypt", "lvm", "dm"}
            encrypted = device_type == "crypt" or filesystem == "crypto_LUKS"
            return {
                "name": _clean_text(raw.get("name"), 128),
                "kernel_name": _clean_text(raw.get("kname"), 128),
                "path": path,
                "type": device_type,
                "size": _integer(raw.get("size")),
                "filesystem": filesystem,
                "filesystem_version": _clean_text(raw.get("fsver"), 64),
                "label": _clean_text(raw.get("label"), 128),
                "uuid": _clean_text(raw.get("uuid"), 160),
                "partuuid": _clean_text(raw.get("partuuid"), 160),
                "mountpoints": mounts,
                "read_only": bool(_integer(raw.get("ro"))),
                "removable": bool(_integer(raw.get("rm"))),
                "hotplug": bool(_integer(raw.get("hotplug"))),
                "rotational": rotational,
                "media_type": media_type,
                "device_mapper": device_mapper,
                "encrypted": encrypted,
                "model": _clean_text(raw.get("model"), 160),
                "serial": _clean_text(raw.get("serial"), 160),
                "transport": transport,
                "parent_kernel_name": _clean_text(raw.get("pkname"), 128),
                "partition_type": _clean_text(raw.get("parttype"), 128),
                "partition_label": _clean_text(raw.get("partlabel"), 128),
                "protected": protected,
                "children": children,
            }

        return [item for root in roots if (item := normalize(root)) is not None]

    def devices(self) -> list[dict[str, Any]]:
        result = self.inventory._run("lsblk", LSBLK_ARGS)  # noqa: SLF001 - fixed read-only argv through the existing safety boundary.
        if result is None or result.returncode != 0:
            return []
        return self.parse_lsblk(result.stdout)

    @staticmethod
    def _physical_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        physical: list[dict[str, Any]] = []

        def visit(item: dict[str, Any]) -> None:
            if item.get("type") == "disk" and _safe_device_path(item.get("path")):
                physical.append(item)
            for child in item.get("children") or []:
                if isinstance(child, dict):
                    visit(child)

        for item in devices:
            visit(item)
        return physical

    def _smart(self, device: str) -> dict[str, Any] | None:
        result = self.inventory._run("smartctl", ("-a", "-j", device), timeout=12.0)  # noqa: SLF001
        if result is None or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"provider": "smartctl", "available": True, "state": "unknown", "warnings": []}
        if not isinstance(payload, dict):
            return {"provider": "smartctl", "available": True, "state": "unknown", "warnings": []}
        smart_status = payload.get("smart_status")
        passed = smart_status.get("passed") if isinstance(smart_status, dict) else None
        temperature_value = payload.get("temperature")
        temperature = temperature_value.get("current") if isinstance(temperature_value, dict) else None
        power_value = payload.get("power_on_time")
        hours = power_value.get("hours") if isinstance(power_value, dict) else None
        reallocated = _smart_raw_attribute(payload, 5)
        pending = _smart_raw_attribute(payload, 197)
        uncorrectable = _smart_raw_attribute(payload, 198)
        warnings: list[str] = []
        if reallocated and reallocated > 0:
            warnings.append("reallocated-sectors")
        if pending and pending > 0:
            warnings.append("pending-sectors")
        if uncorrectable and uncorrectable > 0:
            warnings.append("uncorrectable-sectors")
        state = "failed" if passed is False else "warning" if warnings else "ok" if passed is True else "unknown"
        return {
            "provider": "smartctl",
            "available": True,
            "state": state,
            "passed": passed if isinstance(passed, bool) else None,
            "temperature_c": _number(temperature),
            "power_on_hours": _integer(hours) if hours is not None else None,
            "reallocated_sectors": reallocated,
            "pending_sectors": pending,
            "uncorrectable_sectors": uncorrectable,
            "warnings": warnings,
            "tool_exit_code": result.returncode,
        }

    def _nvme(self, device: str) -> dict[str, Any] | None:
        result = self.inventory._run("nvme", ("smart-log", "-o", "json", device), timeout=12.0)  # noqa: SLF001
        if result is None or not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"provider": "nvme", "available": True, "state": "unknown", "warnings": []}
        if not isinstance(payload, dict):
            return {"provider": "nvme", "available": True, "state": "unknown", "warnings": []}
        critical = _integer(payload.get("critical_warning"))
        percentage_used = _number(payload.get("percentage_used"))
        available_spare = _number(payload.get("avail_spare"))
        spare_threshold = _number(payload.get("spare_thresh"))
        media_errors = _integer(payload.get("media_errors"))
        warnings: list[str] = []
        if percentage_used is not None and percentage_used >= 90:
            warnings.append("wear-high")
        if media_errors > 0:
            warnings.append("media-errors")
        if available_spare is not None and spare_threshold is not None and available_spare <= spare_threshold:
            warnings.append("available-spare-low")
        return {
            "provider": "nvme",
            "available": True,
            "state": "failed" if critical else "warning" if warnings else "ok",
            "critical_warning": critical,
            "temperature_c": _number(payload.get("temperature")),
            "percentage_used": percentage_used,
            "available_spare_percent": available_spare,
            "available_spare_threshold_percent": spare_threshold,
            "media_errors": media_errors,
            "unsafe_shutdowns": _integer(payload.get("unsafe_shutdowns")),
            "error_log_entries": _integer(payload.get("num_err_log_entries")),
            "warnings": warnings,
            "tool_exit_code": result.returncode,
        }

    def health(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self._physical_devices(devices):
            device = _safe_device_path(item.get("path"))
            if device is None:
                continue
            is_nvme = device.startswith("/dev/nvme") or item.get("transport") == "nvme"
            health = self._nvme(device) if is_nvme else None
            if health is None:
                health = self._smart(device)
            if health is None:
                health = {"provider": "none", "available": False, "state": "unavailable", "warnings": []}
            result.append(
                {
                    "device": device,
                    "model": item.get("model", ""),
                    "serial": item.get("serial", ""),
                    "protected": bool(item.get("protected")),
                    **health,
                }
            )
        return result
