from __future__ import annotations

import json
from typing import Any

from ..service import _clean_text, _number, _safe_device_path
from .probe import LVS_ARGS, PVS_ARGS, VGS_ARGS, StorageReadOnlyProbe


def _bytes_value(value: Any) -> int:
    text = str(value or "").strip().lstrip("<>")
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


class LvmCollector:
    def __init__(self, probe: StorageReadOnlyProbe) -> None:
        self.probe = probe

    @staticmethod
    def _rows(payload: str, section: str) -> list[dict[str, Any]]:
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        reports = decoded.get("report") if isinstance(decoded, dict) else None
        if not isinstance(reports, list):
            return []
        rows: list[dict[str, Any]] = []
        for report in reports:
            if not isinstance(report, dict):
                continue
            values = report.get(section)
            if isinstance(values, list):
                rows.extend(item for item in values if isinstance(item, dict))
        return rows

    def collect(self) -> dict[str, Any]:
        commands = {
            "pvs": PVS_ARGS,
            "vgs": VGS_ARGS,
            "lvs": LVS_ARGS,
        }
        raw: dict[str, list[dict[str, Any]]] = {}
        for tool, args in commands.items():
            result = self.probe.run(tool, args, timeout=12.0)
            raw[tool] = self._rows(result.stdout, tool[:-1]) if result is not None and result.returncode == 0 else []

        physical_volumes: list[dict[str, Any]] = []
        for item in raw["pvs"]:
            path = _safe_device_path(item.get("pv_name"))
            if path is None:
                continue
            physical_volumes.append(
                {
                    "path": path,
                    "volume_group": _clean_text(item.get("vg_name"), 128),
                    "size": _bytes_value(item.get("pv_size")),
                    "free": _bytes_value(item.get("pv_free")),
                    "attributes": _clean_text(item.get("pv_attr"), 32),
                }
            )

        volume_groups = [
            {
                "name": _clean_text(item.get("vg_name"), 128),
                "size": _bytes_value(item.get("vg_size")),
                "free": _bytes_value(item.get("vg_free")),
                "pv_count": int(_number(item.get("pv_count")) or 0),
                "lv_count": int(_number(item.get("lv_count")) or 0),
                "attributes": _clean_text(item.get("vg_attr"), 32),
            }
            for item in raw["vgs"]
            if _clean_text(item.get("vg_name"), 128)
        ]

        logical_volumes: list[dict[str, Any]] = []
        for item in raw["lvs"]:
            name = _clean_text(item.get("lv_name"), 128)
            volume_group = _clean_text(item.get("vg_name"), 128)
            if not name or not volume_group:
                continue
            path = _safe_device_path(item.get("lv_path"))
            attributes = _clean_text(item.get("lv_attr"), 32)
            pool = _clean_text(item.get("pool_lv"), 128)
            data_percent = _number(item.get("data_percent"))
            metadata_percent = _number(item.get("metadata_percent"))
            logical_volumes.append(
                {
                    "name": name,
                    "volume_group": volume_group,
                    "path": path or "",
                    "size": _bytes_value(item.get("lv_size")),
                    "attributes": attributes,
                    "pool": pool,
                    "origin": _clean_text(item.get("origin"), 128),
                    "data_percent": data_percent,
                    "metadata_percent": metadata_percent,
                    "thin_pool": bool(pool) or (len(attributes) > 0 and attributes[0] in {"t", "V"}),
                }
            )

        pv_by_vg: dict[str, list[str]] = {}
        for item in physical_volumes:
            group = str(item["volume_group"])
            if group:
                pv_by_vg.setdefault(group, []).append(str(item["path"]))
        lv_by_vg: dict[str, list[str]] = {}
        for item in logical_volumes:
            group = str(item["volume_group"])
            lv_by_vg.setdefault(group, []).append(str(item["name"]))

        relationships = [
            {
                "volume_group": group["name"],
                "physical_volumes": sorted(pv_by_vg.get(str(group["name"]), [])),
                "logical_volumes": sorted(lv_by_vg.get(str(group["name"]), [])),
            }
            for group in volume_groups
        ]

        return {
            "available": all(self.probe.tool_available(name) for name in {"pvs", "vgs", "lvs"}),
            "physical_volumes": physical_volumes,
            "volume_groups": volume_groups,
            "logical_volumes": logical_volumes,
            "relationships": relationships,
        }
