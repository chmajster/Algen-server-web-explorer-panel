"""Compliance Manager permissions registered in the shared Identity registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

COMPLIANCE_VIEW = "compliance.view"
COMPLIANCE_SCAN = "compliance.scan"

_PERMISSIONS = {
    COMPLIANCE_VIEW: ("view", PermissionRisk.low, False),
    COMPLIANCE_SCAN: ("scan", PermissionRisk.medium, True),
}


def register_permissions() -> None:
    for permission, (operation, risk, mutating) in _PERMISSIONS.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="security",
                operation=operation,
                applications=["module:compliance-manager"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.security.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update({COMPLIANCE_VIEW, COMPLIANCE_SCAN})
    ROLE_PERMISSIONS[Role.auditor].add(COMPLIANCE_VIEW)


register_permissions()
