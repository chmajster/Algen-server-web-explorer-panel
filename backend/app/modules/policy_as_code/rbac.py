"""Policy-as-Code Engine permissions registered in the shared Identity registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

POLICY_VIEW = "policy.view"
POLICY_EVALUATE = "policy.evaluate"
POLICY_MANAGE = "policy.manage"

_PERMISSIONS = {
    POLICY_VIEW: ("view", PermissionRisk.low, False),
    POLICY_EVALUATE: ("evaluate", PermissionRisk.low, False),
    POLICY_MANAGE: ("manage", PermissionRisk.high, True),
}


def register_permissions() -> None:
    for permission, (operation, risk, mutating) in _PERMISSIONS.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="security",
                operation=operation,
                applications=["module:policy-as-code"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.security.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update({POLICY_VIEW, POLICY_EVALUATE})
    ROLE_PERMISSIONS[Role.auditor].add(POLICY_VIEW)


register_permissions()
