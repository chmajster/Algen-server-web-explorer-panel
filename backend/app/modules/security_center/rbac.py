"""Security Center permissions registered in the shared Identity registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

SECURITY_VIEW = "security.view"
SECURITY_SCAN = "security.scan"
SECURITY_FINDINGS_MANAGE = "security.findings.manage"

_PERMISSIONS = {
    SECURITY_VIEW: ("view", PermissionRisk.low, False),
    SECURITY_SCAN: ("scan", PermissionRisk.high, True),
    SECURITY_FINDINGS_MANAGE: ("findings.manage", PermissionRisk.high, True),
}


def register_permissions() -> None:
    for permission, (operation, risk, mutating) in _PERMISSIONS.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="security",
                operation=operation,
                applications=["module:security-center"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.security.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update({SECURITY_VIEW, SECURITY_SCAN, SECURITY_FINDINGS_MANAGE})
    ROLE_PERMISSIONS[Role.auditor].add(SECURITY_VIEW)


register_permissions()
