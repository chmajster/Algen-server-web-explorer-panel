from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..service import _clean_text, _integer, _number, _safe_device_path, _safe_mount_path
from .probe import ZFS_LIST_ARGS, ZPOOL_LIST_ARGS, StorageReadOnlyProbe


_POOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ZFS_STATES = {"ONLINE", "DEGRADED", "FAULTED", "OFFLINE", "UNAVAIL", "REMOVED", "AVAIL", "SUSPENDED"}


def _bytes_value(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "0").strip())))
    except (TypeError, ValueError):
        return 0


class PoolCollector:
    def __init__(
        self,
        probe: StorageReadOnlyProbe,
        *,
        mdstat_path: Path = Path("/proc/mdstat"),
    ) -> None:
        self.probe = probe
        self.mdstat_path = mdstat_path

    @staticmethod
    def parse_mdstat(content: str) -> list[dict[str, Any]]:
        arrays: list[dict[str, Any]] = []
        lines = content.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            match = re.match(r"^(md\S+)\s*:\s*(\S+)\s+(raid\S+)\s+(.+)$", line)
            if not match:
                index += 1
                continue
            name, activity, level, raw_members = match.groups()
            details: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor].strip()
                if re.match(r"^md\S+\s*:", candidate) or candidate.startswith("unused devices"):
                    break
                if candidate:
                    details.append(candidate)
                cursor += 1
            detail = " ".join(details)
            bitmap_match = re.search(r"\[([U_]+)\]", detail)
            member_state = bitmap_match.group(1) if bitmap_match else ""
            counts = re.search(r"\[(\d+)/(\d+)\]", detail)
            expected_members = int(counts.group(1)) if counts else len(member_state)
            active_members = int(counts.group(2)) if counts else member_state.count("U")
            blocks_match = re.search(r"(\d+)\s+blocks", detail)
            sync = re.search(r"\b(resync|recovery|reshape|check|repair)\s*=\s*([0-9.]+)%", detail, re.IGNORECASE)
            finish = re.search(r"finish=([^\s]+)", detail)
            speed = re.search(r"speed=([^\s]+)", detail)
            members = raw_members.split()
            failed_members = [item for item in members if "(F)" in item or "faulty" in item.lower()]
            missing_members = max(expected_members - active_members, member_state.count("_"), len(failed_members))
            arrays.append(
                {
                    "name": _clean_text(name, 128),
                    "activity": _clean_text(activity, 32),
                    "level": _clean_text(level, 32),
                    "members": [_clean_text(item, 128) for item in members],
                    "failed_members": [_clean_text(item, 128) for item in failed_members],
                    "member_state": member_state,
                    "expected_members": expected_members,
                    "active_members": active_members,
                    "missing_members": missing_members,
                    "blocks": int(blocks_match.group(1)) if blocks_match else 0,
                    "operation": sync.group(1).lower() if sync else "",
                    "progress_percent": _number(sync.group(2)) if sync else None,
                    "finish": _clean_text(finish.group(1), 64) if finish else "",
                    "speed": _clean_text(speed.group(1), 64) if speed else "",
                    "state": "degraded" if missing_members > 0 else "ok",
                }
            )
            index = max(cursor, index + 1)
        return arrays

    def raid(self) -> list[dict[str, Any]]:
        try:
            content = self.mdstat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.parse_mdstat(content)

    @staticmethod
    def parse_zpool_list(content: str) -> list[dict[str, Any]]:
        pools: list[dict[str, Any]] = []
        for line in content.splitlines():
            fields = line.split("\t")
            if len(fields) != 5:
                fields = line.split()
            if len(fields) != 5:
                continue
            name, health, size, allocated, free = fields
            if not _POOL_RE.fullmatch(name):
                continue
            normalized_health = _clean_text(health, 32).upper()
            pools.append(
                {
                    "name": name,
                    "health": normalized_health,
                    "size": _bytes_value(size),
                    "allocated": _bytes_value(allocated),
                    "free": _bytes_value(free),
                    "state": "ok" if normalized_health == "ONLINE" else "degraded",
                    "members": [],
                    "scan": {"action": "", "state": "unknown", "progress_percent": None, "raw": ""},
                    "errors": "",
                }
            )
        return pools

    @staticmethod
    def parse_zpool_status(content: str, pool_name: str) -> dict[str, Any]:
        state = ""
        scan_lines: list[str] = []
        errors = ""
        members: list[dict[str, Any]] = []
        in_config = False
        collecting_scan = False
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("state:"):
                state = _clean_text(stripped.partition(":")[2], 32).upper()
                collecting_scan = False
                continue
            if stripped.startswith("scan:"):
                scan_lines = [_clean_text(stripped.partition(":")[2], 512)]
                collecting_scan = True
                continue
            if stripped.startswith("config:"):
                in_config = True
                collecting_scan = False
                continue
            if stripped.startswith("errors:"):
                errors = _clean_text(stripped.partition(":")[2], 512)
                in_config = False
                collecting_scan = False
                continue
            if collecting_scan and stripped:
                scan_lines.append(_clean_text(stripped, 512))
            if not in_config or not stripped or stripped.startswith("NAME"):
                continue
            fields = stripped.split()
            if len(fields) < 5 or fields[1].upper() not in _ZFS_STATES:
                continue
            name = _clean_text(fields[0], 512)
            if name == pool_name:
                continue
            try:
                read_errors = int(fields[-3])
                write_errors = int(fields[-2])
                checksum_errors = int(fields[-1])
            except ValueError:
                continue
            members.append(
                {
                    "name": name,
                    "path": _safe_device_path(name) or "",
                    "state": fields[1].upper(),
                    "read_errors": read_errors,
                    "write_errors": write_errors,
                    "checksum_errors": checksum_errors,
                }
            )

        scan_raw = " ".join(item for item in scan_lines if item)
        scan_lower = scan_raw.lower()
        if "scrub" in scan_lower:
            action = "scrub"
        elif "resilver" in scan_lower:
            action = "resilver"
        else:
            action = ""
        progress = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s+done", scan_raw, re.IGNORECASE)
        if "in progress" in scan_lower:
            scan_state = "in_progress"
        elif "none requested" in scan_lower or not scan_raw:
            scan_state = "none"
        elif "repaired" in scan_lower or "resilvered" in scan_lower or "completed" in scan_lower:
            scan_state = "completed"
        else:
            scan_state = "unknown"
        return {
            "health": state,
            "members": members,
            "scan": {
                "action": action,
                "state": scan_state,
                "progress_percent": _number(progress.group(1)) if progress else None,
                "raw": _clean_text(scan_raw, 1000),
            },
            "errors": errors,
        }

    @staticmethod
    def parse_zfs_datasets(content: str) -> list[dict[str, Any]]:
        datasets: list[dict[str, Any]] = []
        for line in content.splitlines():
            fields = line.split("\t")
            if len(fields) != 6:
                fields = line.split(None, 5)
            if len(fields) != 6:
                continue
            name, kind, used, available, referenced, mountpoint = fields
            datasets.append(
                {
                    "name": _clean_text(name, 256),
                    "type": _clean_text(kind, 32),
                    "used": _bytes_value(used),
                    "available": _bytes_value(available),
                    "referenced": _bytes_value(referenced),
                    "mount_point": _clean_text(mountpoint, 512),
                }
            )
        return [item for item in datasets if item["name"]]

    def zfs(self) -> dict[str, Any]:
        result = self.probe.run("zpool", ZPOOL_LIST_ARGS, timeout=12.0)
        pools = self.parse_zpool_list(result.stdout) if result is not None and result.returncode == 0 else []
        for pool in pools:
            status = self.probe.run("zpool", ("status", "-P", str(pool["name"])), timeout=12.0)
            if status is None or status.returncode != 0:
                continue
            detail = self.parse_zpool_status(status.stdout, str(pool["name"]))
            if detail["health"]:
                pool["health"] = detail["health"]
                pool["state"] = "ok" if detail["health"] == "ONLINE" else "degraded"
            pool["members"] = detail["members"]
            pool["scan"] = detail["scan"]
            pool["errors"] = detail["errors"]

        datasets_result = self.probe.run("zfs", ZFS_LIST_ARGS, timeout=12.0)
        datasets = self.parse_zfs_datasets(datasets_result.stdout) if datasets_result is not None and datasets_result.returncode == 0 else []
        return {
            "available": self.probe.tool_available("zpool"),
            "datasets_available": self.probe.tool_available("zfs"),
            "pools": pools,
            "datasets": datasets,
        }

    @staticmethod
    def parse_btrfs_device_stats(content: str) -> dict[str, Any]:
        devices: dict[str, dict[str, int]] = {}
        for line in content.splitlines():
            match = re.match(r"^\[(?P<device>/dev/[^\]]+)\]\.(?P<metric>[A-Za-z0-9_]+)\s+(?P<value>\d+)$", line.strip())
            if not match:
                continue
            device = _safe_device_path(match.group("device"))
            if device is None:
                continue
            devices.setdefault(device, {})[match.group("metric")] = int(match.group("value"))
        total_errors = sum(value for metrics in devices.values() for value in metrics.values())
        return {
            "devices": [{"path": path, "errors": metrics} for path, metrics in sorted(devices.items())],
            "total_errors": total_errors,
        }

    @staticmethod
    def parse_btrfs_show(content: str) -> dict[str, Any]:
        uuid_match = re.search(r"\buuid:\s*([^\s]+)", content, re.IGNORECASE)
        label_match = re.search(r"Label:\s*(?:'([^']*)'|([^\s]+))", content)
        devices: list[dict[str, Any]] = []
        for line in content.splitlines():
            match = re.search(r"devid\s+(\d+)\s+size\s+(\d+)\s+used\s+(\d+)\s+path\s+(.+)$", line.strip())
            if not match:
                continue
            path = _safe_device_path(match.group(4).strip())
            if path is None:
                continue
            devices.append(
                {
                    "id": int(match.group(1)),
                    "size": int(match.group(2)),
                    "used": int(match.group(3)),
                    "path": path,
                }
            )
        label = (label_match.group(1) or label_match.group(2)) if label_match else ""
        if label == "none":
            label = ""
        return {
            "uuid": _clean_text(uuid_match.group(1), 160) if uuid_match else "",
            "label": _clean_text(label, 160),
            "devices": devices,
        }

    @staticmethod
    def parse_btrfs_usage(content: str) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for line in content.splitlines():
            match = re.match(r"^(Data|Metadata|System),([^:]+):\s*Size:(\d+),\s*Used:(\d+)", line.strip())
            if not match:
                continue
            profiles.append(
                {
                    "kind": match.group(1).lower(),
                    "profile": _clean_text(match.group(2), 64),
                    "size": int(match.group(3)),
                    "used": int(match.group(4)),
                }
            )
        return profiles

    @staticmethod
    def parse_btrfs_scrub(content: str) -> dict[str, Any]:
        status_match = re.search(r"^Status:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        progress_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", content)
        error_match = re.search(r"^Error summary:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
        status = _clean_text(status_match.group(1), 128).lower() if status_match else "unknown"
        if "running" in status:
            state = "in_progress"
        elif "finished" in status or "completed" in status:
            state = "completed"
        elif "never" in status or "no stats" in status:
            state = "none"
        else:
            state = "unknown"
        return {
            "state": state,
            "status": status,
            "progress_percent": _number(progress_match.group(1)) if progress_match else None,
            "error_summary": _clean_text(error_match.group(1), 256) if error_match else "",
        }

    def btrfs(self, filesystems: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in filesystems or []:
            if item.get("filesystem") != "btrfs":
                continue
            mount_point = _safe_mount_path(item.get("mount_point"))
            if mount_point is None:
                continue
            stats_result = self.probe.run("btrfs", ("device", "stats", "-c", mount_point), timeout=12.0)
            show_result = self.probe.run("btrfs", ("filesystem", "show", "--raw", mount_point), timeout=12.0)
            usage_result = self.probe.run("btrfs", ("filesystem", "usage", "-b", mount_point), timeout=12.0)
            scrub_result = self.probe.run("btrfs", ("scrub", "status", "-R", mount_point), timeout=12.0)

            stats = self.parse_btrfs_device_stats(stats_result.stdout) if stats_result is not None and stats_result.stdout else {"devices": [], "total_errors": 0}
            show = self.parse_btrfs_show(show_result.stdout) if show_result is not None and show_result.returncode == 0 else {"uuid": "", "label": "", "devices": []}
            profiles = self.parse_btrfs_usage(usage_result.stdout) if usage_result is not None and usage_result.returncode == 0 else []
            scrub = self.parse_btrfs_scrub(scrub_result.stdout) if scrub_result is not None and scrub_result.stdout else {"state": "unknown", "status": "unknown", "progress_percent": None, "error_summary": ""}
            total_errors = _integer(stats.get("total_errors"))
            results.append(
                {
                    "mount_point": mount_point,
                    "available": any(result is not None for result in (stats_result, show_result, usage_result, scrub_result)),
                    "state": "degraded" if total_errors > 0 else "ok",
                    "uuid": show["uuid"],
                    "label": show["label"],
                    "devices": show["devices"],
                    "device_errors": stats["devices"],
                    "total_errors": total_errors,
                    "profiles": profiles,
                    "scrub": scrub,
                }
            )
        return results

    def collect(self, *, filesystems: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "raid": self.raid(),
            "zfs": self.zfs(),
            "btrfs": self.btrfs(filesystems),
        }
