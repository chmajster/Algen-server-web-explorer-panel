from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..service import _clean_text


SECTOR_BYTES = 512


class DiskIoCollector:
    def __init__(self, *, diskstats_path: Path = Path("/proc/diskstats")) -> None:
        self.diskstats_path = diskstats_path

    @staticmethod
    def parse_diskstats(content: str, names: set[str] | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line in content.splitlines():
            fields = line.split()
            if len(fields) < 14:
                continue
            name = _clean_text(fields[2], 128)
            if not name:
                continue
            if names is not None and name not in names:
                continue
            if names is None and (name.startswith("loop") or name.startswith("ram")):
                continue
            try:
                reads = int(fields[3])
                reads_merged = int(fields[4])
                sectors_read = int(fields[5])
                read_ms = int(fields[6])
                writes = int(fields[7])
                writes_merged = int(fields[8])
                sectors_written = int(fields[9])
                write_ms = int(fields[10])
                in_flight = int(fields[11])
                io_ms = int(fields[12])
                weighted_io_ms = int(fields[13])
                discards = int(fields[14]) if len(fields) > 17 else 0
                sectors_discarded = int(fields[16]) if len(fields) > 17 else 0
                discard_ms = int(fields[17]) if len(fields) > 17 else 0
                flushes = int(fields[18]) if len(fields) > 19 else 0
                flush_ms = int(fields[19]) if len(fields) > 19 else 0
            except ValueError:
                continue
            entries.append(
                {
                    "name": name,
                    "reads_completed": reads,
                    "reads_merged": reads_merged,
                    "bytes_read": sectors_read * SECTOR_BYTES,
                    "read_ms": read_ms,
                    "writes_completed": writes,
                    "writes_merged": writes_merged,
                    "bytes_written": sectors_written * SECTOR_BYTES,
                    "write_ms": write_ms,
                    "io_in_progress": in_flight,
                    "io_ms": io_ms,
                    "weighted_io_ms": weighted_io_ms,
                    "discards_completed": discards,
                    "bytes_discarded": sectors_discarded * SECTOR_BYTES,
                    "discard_ms": discard_ms,
                    "flushes_completed": flushes,
                    "flush_ms": flush_ms,
                }
            )
        return entries

    @staticmethod
    def _physical_kernel_names(devices: list[dict[str, Any]] | None) -> set[str] | None:
        if devices is None:
            return None
        names: set[str] = set()

        def visit(item: dict[str, Any]) -> None:
            if item.get("type") == "disk":
                kernel_name = _clean_text(item.get("kernel_name"), 128)
                if kernel_name:
                    names.add(kernel_name)
            for child in item.get("children") or []:
                if isinstance(child, dict):
                    visit(child)

        for item in devices:
            if isinstance(item, dict):
                visit(item)
        return names

    def collect(self, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        try:
            content = self.diskstats_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return self.parse_diskstats(content, self._physical_kernel_names(devices))

    def sample(self, devices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "read_only": True,
            "sampled_at": time.time(),
            "monotonic_ns": time.monotonic_ns(),
            "counter_mode": "cumulative",
            "sector_bytes": SECTOR_BYTES,
            "delta_ready": True,
            "devices": self.collect(devices),
        }
