"""DCST permission registration using the shared Identity permission registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

DCST_READ = "dcst.read"
DCST_MANAGE_SERVICES = "dcst.manage_services"
DCST_MANAGE_PORTS = "dcst.manage_ports"
DCST_MANAGE_IPSETS = "dcst.manage_ipsets"
DCST_MANAGE_TAGS = "dcst.manage_tags"
DCST_BLOCK_TRAFFIC = "dcst.block_traffic"
DCST_SYNC = "dcst.sync"
DCST_VIEW_LOGS = "dcst.view_logs"
DCST_ADMIN = "dcst.admin"

DCST_PERMISSIONS = {
    DCST_READ: ("read", PermissionRisk.low, False),
    DCST_MANAGE_SERVICES: ("manage_services", PermissionRisk.high, True),
    DCST_MANAGE_PORTS: ("manage_ports", PermissionRisk.high, True),
    DCST_MANAGE_IPSETS: ("manage_ipsets", PermissionRisk.high, True),
    DCST_MANAGE_TAGS: ("manage_tags", PermissionRisk.high, True),
    DCST_BLOCK_TRAFFIC: ("block_traffic", PermissionRisk.critical, True),
    DCST_SYNC: ("sync", PermissionRisk.critical, True),
    DCST_VIEW_LOGS: ("view_logs", PermissionRisk.low, False),
    DCST_ADMIN: ("admin", PermissionRisk.critical, True),
}


def register_permissions() -> None:
    for permission, (operation, risk, mutating) in DCST_PERMISSIONS.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="dcst",
                operation=operation,
                applications=["module:dcst"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.dcst.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(DCST_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update({
        DCST_READ, DCST_MANAGE_SERVICES, DCST_MANAGE_PORTS, DCST_MANAGE_IPSETS,
        DCST_MANAGE_TAGS, DCST_BLOCK_TRAFFIC, DCST_SYNC, DCST_VIEW_LOGS,
    })
    ROLE_PERMISSIONS[Role.auditor].update({DCST_READ, DCST_VIEW_LOGS})


register_permissions()

__all__ = [
    "DCST_ADMIN", "DCST_BLOCK_TRAFFIC", "DCST_MANAGE_IPSETS", "DCST_MANAGE_PORTS",
    "DCST_MANAGE_SERVICES", "DCST_MANAGE_TAGS", "DCST_READ", "DCST_SYNC",
    "DCST_VIEW_LOGS", "register_permissions",
]
