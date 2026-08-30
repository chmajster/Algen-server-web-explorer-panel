from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .offline_jobs import OFFLINE_OPERATIONS
from .offline_service import OfflineRepositoryService, offline_service


def _directory_check(identifier: str, path: Path) -> dict[str, str]:
    exists = path.is_dir() and not path.is_symlink()
    writable = exists and os.access(path, os.W_OK)
    return {
        "id": identifier,
        "status": "ok" if writable else "error",
        "message": f"{path} {'writable' if writable else 'unavailable'}",
    }


def offline_diagnostics(service: OfflineRepositoryService | None = None) -> dict[str, Any]:
    current = service or offline_service()
    placeholders = ",".join("?" for _ in OFFLINE_OPERATIONS)
    try:
        orphaned_payloads = int(
            (
                current.store.one(
                    "SELECT COUNT(*) AS count FROM offline_job_payloads p LEFT JOIN repository_sync_jobs j ON j.id=p.job_id WHERE j.id IS NULL"
                )
                or {"count": 0}
            )["count"]
        )
    except sqlite3.OperationalError:
        orphaned_payloads = 0
    missing_bundle_artifacts = 0
    for bundle in current.store.all("SELECT filename,status FROM offline_bundles WHERE status IN ('ready','verified')"):
        path = current.bundle_root / str(bundle["filename"])
        if not path.is_file() or path.is_symlink():
            missing_bundle_artifacts += 1
    active_offline_jobs = int(
        (
            current.store.one(
                f"SELECT COUNT(*) AS count FROM repository_sync_jobs WHERE operation IN ({placeholders}) AND status IN ('queued','running')",
                tuple(sorted(OFFLINE_OPERATIONS)),
            )
            or {"count": 0}
        )["count"]
    )
    usage = shutil.disk_usage(current.root)
    tools = {name: shutil.which(name) or "" for name in ("gpg", "dpkg-deb", "rpm", "createrepo_c")}
    checks = [
        _directory_check("offline_bundle_directory", current.bundle_root),
        _directory_check("offline_staging_directory", current.staging_root),
        _directory_check("offline_temporary_directory", current.temporary_root),
        {
            "id": "offline_free_space",
            "status": "ok" if usage.free >= 1024**3 else "warning",
            "message": str(usage.free),
        },
        {
            "id": "offline_bundle_artifacts",
            "status": "ok" if not missing_bundle_artifacts else "error",
            "message": f"missing={missing_bundle_artifacts}",
        },
        {
            "id": "offline_job_payloads",
            "status": "ok" if not orphaned_payloads else "error",
            "message": f"orphaned={orphaned_payloads}",
        },
        {
            "id": "air_gapped_mode",
            "status": "ok",
            "message": "enabled" if current.air_gapped_mode() else "disabled",
        },
    ]
    checks.extend(
        {
            "id": f"offline_tool_{name.replace('-', '_')}",
            "status": "ok" if path else "warning",
            "message": path or "not installed",
        }
        for name, path in tools.items()
    )
    return {
        "checks": checks,
        "tools": tools,
        "active_offline_jobs": active_offline_jobs,
        "storage": current.storage(),
        "air_gapped_mode": current.air_gapped_mode(),
    }
