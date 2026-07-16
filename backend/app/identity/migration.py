from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..audit import logger
from .models import Role, UserPolicy
from .permissions import normalize_permission

if TYPE_CHECKING:
    from .repository import IdentityRepository


def _permissions(values: Any, ignored: list[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        try:
            normalized = normalize_permission(str(value))
        except ValueError:
            ignored.append(str(value)[:128])
            continue
        if normalized not in result:
            result.append(normalized)
    return result


def migrate_legacy_rbac(repository: "IdentityRepository", path: Path) -> None:
    if repository.migration_applied("rbac-json-v1"):
        return
    if not path.is_file():
        repository.import_legacy([], {"source": str(path), "imported": 0, "ignored_permissions": []})
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("identity_rbac_migration_read_failed path=%s", path)
        return
    if not isinstance(raw, dict):
        logger.error("identity_rbac_migration_invalid path=%s", path)
        return
    ignored: list[str] = []
    policies: list[UserPolicy] = []
    for username, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            role = Role(value.get("role", Role.user.value))
            allow = _permissions(value.get("allow"), ignored)
            deny = _permissions(value.get("deny"), ignored)
            allow = [item for item in allow if item not in deny]
            policies.append(UserPolicy(username=str(username), role=role, allow=allow, deny=deny))
        except (TypeError, ValueError):
            logger.warning("identity_rbac_migration_skipped_user username=%s", str(username)[:64])
    backup = path.with_name(f"{path.name}.identity-v1.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass
    repository.import_legacy(policies, {"source": str(path), "backup": str(backup), "imported": len(policies), "ignored_permissions": sorted(set(ignored))})
