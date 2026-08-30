from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

OFFLINE_VIEW = "os-repositories.offline.view"
OFFLINE_EXPORT = "os-repositories.offline.export"
OFFLINE_IMPORT = "os-repositories.offline.import"
OFFLINE_VERIFY = "os-repositories.offline.verify"
OFFLINE_DELETE = "os-repositories.offline.delete"
OFFLINE_TARGETS_MANAGE = "os-repositories.offline.targets.manage"
OFFLINE_FREEZE = "os-repositories.offline.freeze"
OFFLINE_DELTA = "os-repositories.offline.delta"
OFFLINE_CONFIGURE = "os-repositories.offline.configure"
OFFLINE_AIRGAP_MANAGE = "os-repositories.offline.airgap.manage"

OFFLINE_PERMISSIONS = {
    OFFLINE_VIEW: ("offline.view", PermissionRisk.low, False),
    OFFLINE_EXPORT: ("offline.export", PermissionRisk.high, True),
    OFFLINE_IMPORT: ("offline.import", PermissionRisk.high, True),
    OFFLINE_VERIFY: ("offline.verify", PermissionRisk.low, False),
    OFFLINE_DELETE: ("offline.delete", PermissionRisk.critical, True),
    OFFLINE_TARGETS_MANAGE: ("offline.targets.manage", PermissionRisk.high, True),
    OFFLINE_FREEZE: ("offline.freeze", PermissionRisk.high, True),
    OFFLINE_DELTA: ("offline.delta", PermissionRisk.high, True),
    OFFLINE_CONFIGURE: ("offline.configure", PermissionRisk.high, True),
    OFFLINE_AIRGAP_MANAGE: ("offline.airgap.manage", PermissionRisk.critical, True),
}


def register_offline_repository_permissions() -> None:
    for permission_id, (operation, risk, mutating) in OFFLINE_PERMISSIONS.items():
        if permission_id in PERMISSION_REGISTRY:
            continue
        PERMISSION_REGISTRY[permission_id] = PermissionMetadata(
            id=permission_id,
            category="os-repositories",
            operation=operation,
            applications=["module:os-repositories"],
            risk=risk,
            mutating=mutating,
            label_key=f"permissions.{permission_id}",
            description_key="permissions.category.os-repositories.description",
        )
        ALL_PERMISSIONS.add(permission_id)
        ROLE_PERMISSIONS[Role.admin].add(permission_id)

    ROLE_PERMISSIONS[Role.operator].update(
        {
            OFFLINE_VIEW,
            OFFLINE_EXPORT,
            OFFLINE_IMPORT,
            OFFLINE_VERIFY,
            OFFLINE_TARGETS_MANAGE,
            OFFLINE_FREEZE,
            OFFLINE_DELTA,
            OFFLINE_CONFIGURE,
        }
    )
    ROLE_PERMISSIONS[Role.auditor].add(OFFLINE_VIEW)
