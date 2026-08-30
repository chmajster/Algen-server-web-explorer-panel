from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS


LDAP_CONNECTIONS_READ = "ldap.connections.read"
LDAP_CONNECTIONS_MANAGE = "ldap.connections.manage"
LDAP_DIRECTORY_READ = "ldap.directory.read"
LDAP_USERS_READ = "ldap.users.read"
LDAP_USERS_CREATE = "ldap.users.create"
LDAP_USERS_UPDATE = "ldap.users.update"
LDAP_USERS_DELETE = "ldap.users.delete"
LDAP_USERS_PASSWORD_RESET = "ldap.users.password_reset"
LDAP_GROUPS_READ = "ldap.groups.read"
LDAP_GROUPS_CREATE = "ldap.groups.create"
LDAP_GROUPS_UPDATE = "ldap.groups.update"
LDAP_GROUPS_DELETE = "ldap.groups.delete"
LDAP_OU_READ = "ldap.ou.read"
LDAP_OU_MANAGE = "ldap.ou.manage"
LDAP_SCHEMA_READ = "ldap.schema.read"
LDAP_IMPORT = "ldap.import"
LDAP_EXPORT = "ldap.export"
LDAP_BULK_EXECUTE = "ldap.bulk.execute"
LDAP_DIAGNOSTICS_READ = "ldap.diagnostics.read"

ALL_LDAP_PERMISSIONS = {
    LDAP_CONNECTIONS_READ,
    LDAP_CONNECTIONS_MANAGE,
    LDAP_DIRECTORY_READ,
    LDAP_USERS_READ,
    LDAP_USERS_CREATE,
    LDAP_USERS_UPDATE,
    LDAP_USERS_DELETE,
    LDAP_USERS_PASSWORD_RESET,
    LDAP_GROUPS_READ,
    LDAP_GROUPS_CREATE,
    LDAP_GROUPS_UPDATE,
    LDAP_GROUPS_DELETE,
    LDAP_OU_READ,
    LDAP_OU_MANAGE,
    LDAP_SCHEMA_READ,
    LDAP_IMPORT,
    LDAP_EXPORT,
    LDAP_BULK_EXECUTE,
    LDAP_DIAGNOSTICS_READ,
}

_READ = {
    LDAP_CONNECTIONS_READ,
    LDAP_DIRECTORY_READ,
    LDAP_USERS_READ,
    LDAP_GROUPS_READ,
    LDAP_OU_READ,
    LDAP_SCHEMA_READ,
    LDAP_EXPORT,
    LDAP_DIAGNOSTICS_READ,
}
_OPERATOR = _READ | {
    LDAP_USERS_CREATE,
    LDAP_USERS_UPDATE,
    LDAP_GROUPS_CREATE,
    LDAP_GROUPS_UPDATE,
    LDAP_OU_MANAGE,
}
_CRITICAL = {
    LDAP_USERS_DELETE,
    LDAP_USERS_PASSWORD_RESET,
    LDAP_GROUPS_DELETE,
    LDAP_IMPORT,
    LDAP_BULK_EXECUTE,
}


def register_permissions() -> None:
    for permission in sorted(ALL_LDAP_PERMISSIONS):
        if permission not in PERMISSION_REGISTRY:
            operation = permission.removeprefix("ldap.")
            mutating = permission not in _READ
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="ldap",
                operation=operation,
                applications=["module:ldap-manager"],
                risk=PermissionRisk.critical if permission in _CRITICAL else PermissionRisk.high if mutating else PermissionRisk.low,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.ldap.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(ALL_LDAP_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update(_OPERATOR)
    ROLE_PERMISSIONS[Role.auditor].update(_READ)


register_permissions()
