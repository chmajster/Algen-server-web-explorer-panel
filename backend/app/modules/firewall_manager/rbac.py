"""Firewall Manager permissions registered in the shared Identity registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

FIREWALL_VIEW = "firewall.view"
FIREWALL_RULE_CREATE = "firewall.rules.create"
FIREWALL_RULE_EDIT = "firewall.rules.edit"
FIREWALL_RULE_DELETE = "firewall.rules.delete"
FIREWALL_ENABLE = "firewall.enable"
FIREWALL_DISABLE = "firewall.disable"
FIREWALL_RELOAD = "firewall.reload"
FIREWALL_BACKUP = "firewall.backup"
FIREWALL_RESTORE = "firewall.restore"

_PERMISSIONS = {
    FIREWALL_VIEW: ("view", PermissionRisk.low, False),
    FIREWALL_RULE_CREATE: ("rules.create", PermissionRisk.high, True),
    FIREWALL_RULE_EDIT: ("rules.edit", PermissionRisk.high, True),
    FIREWALL_RULE_DELETE: ("rules.delete", PermissionRisk.critical, True),
    FIREWALL_ENABLE: ("enable", PermissionRisk.critical, True),
    FIREWALL_DISABLE: ("disable", PermissionRisk.critical, True),
    FIREWALL_RELOAD: ("reload", PermissionRisk.high, True),
    FIREWALL_BACKUP: ("backup", PermissionRisk.high, True),
    FIREWALL_RESTORE: ("restore", PermissionRisk.critical, True),
}


def register_permissions() -> None:
    for permission, (operation, risk, mutating) in _PERMISSIONS.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="firewall",
                operation=operation,
                applications=["module:firewall-manager"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.firewall.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update({FIREWALL_VIEW, FIREWALL_RULE_CREATE, FIREWALL_RULE_EDIT, FIREWALL_RULE_DELETE, FIREWALL_ENABLE, FIREWALL_RELOAD, FIREWALL_BACKUP})
    ROLE_PERMISSIONS[Role.auditor].add(FIREWALL_VIEW)


register_permissions()
