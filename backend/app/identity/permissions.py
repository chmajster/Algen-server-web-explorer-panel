from __future__ import annotations

from enum import StrEnum
from typing import Any, Callable

from fastapi import Depends, Request

from ..security import SessionUser, get_session_user, require_csrf
from .exceptions import identity_error
from .models import PermissionMetadata, PermissionRisk, Role


class Permission(StrEnum):
    FILES_VIEW = "files.view"
    FILES_READ = "files.read"
    FILES_DOWNLOAD = "files.download"
    FILES_UPLOAD = "files.upload"
    FILES_CREATE = "files.create"
    FILES_EDIT = "files.edit"
    FILES_RENAME = "files.rename"
    FILES_COPY = "files.copy"
    FILES_MOVE = "files.move"
    FILES_DELETE = "files.delete"
    FILES_CHMOD = "files.chmod"
    FILES_CHOWN = "files.chown"
    TRANSFERS_VIEW_OWN = "transfers.view_own"
    TRANSFERS_VIEW_ALL = "transfers.view_all"
    TRANSFERS_CREATE = "transfers.create"
    TRANSFERS_PAUSE = "transfers.pause"
    TRANSFERS_RESUME = "transfers.resume"
    TRANSFERS_CANCEL = "transfers.cancel"
    TRANSFERS_RETRY = "transfers.retry"
    TRANSFERS_CHANGE_PRIORITY = "transfers.change_priority"
    SETTINGS_VIEW_OWN = "settings.view_own"
    SETTINGS_EDIT_OWN = "settings.edit_own"
    # These are permission identifiers, not embedded credentials.
    SETTINGS_CHANGE_OWN_PASSWORD = "settings.change_own_password"  # nosec B105
    SETTINGS_VIEW_SYSTEM = "settings.view_system"
    SETTINGS_EDIT_SYSTEM = "settings.edit_system"
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_UPDATE = "users.update"
    USERS_RENAME = "users.rename"
    USERS_LOCK = "users.lock"
    USERS_UNLOCK = "users.unlock"
    USERS_CHANGE_PASSWORD = "users.change_password"  # nosec B105
    USERS_MANAGE_GROUPS = "users.manage_groups"
    USERS_MANAGE_QUOTA = "users.manage_quota"
    USERS_DELETE = "users.delete"
    GROUPS_VIEW = "groups.view"
    GROUPS_CREATE = "groups.create"
    GROUPS_RENAME = "groups.rename"
    GROUPS_MANAGE_MEMBERS = "groups.manage_members"
    GROUPS_DELETE = "groups.delete"
    ACCESS_VIEW = "access.view"
    ACCESS_MANAGE_ROLES = "access.manage_roles"
    ACCESS_MANAGE_USER_PERMISSIONS = "access.manage_user_permissions"
    ACCESS_MANAGE_GROUP_PERMISSIONS = "access.manage_group_permissions"
    AUDIT_VIEW_OWN = "audit.view_own"
    AUDIT_VIEW_ALL = "audit.view_all"
    AUDIT_EXPORT = "audit.export"
    MODULES_VIEW = "modules.view"
    MODULES_INSTALL = "modules.install"
    MODULES_UPDATE = "modules.update"
    MODULES_UNINSTALL = "modules.uninstall"
    MODULES_CONFIGURE = "modules.configure"
    MODULES_DIAGNOSTICS = "modules.diagnostics"
    MODULES_LOGS = "modules.logs"
    MODULES_BACKUP_CREATE = "modules.backup_create"
    MODULES_BACKUP_RESTORE = "modules.backup_restore"
    MODULES_BACKUP_DELETE = "modules.backup_delete"
    SERVICES_VIEW = "services.view"
    SERVICES_START = "services.start"
    SERVICES_STOP = "services.stop"
    SERVICES_RESTART = "services.restart"
    SERVICES_ENABLE = "services.enable"
    SERVICES_DISABLE = "services.disable"
    SERVICES_LOGS = "services.logs"
    UPDATES_VIEW = "updates.view"
    UPDATES_APPLY = "updates.apply"
    UPDATES_CONFIGURE_AUTO = "updates.configure_auto_update"
    NETWORK_VIEW = "network_resources.view"
    NETWORK_CREATE = "network_resources.create"
    NETWORK_UPDATE = "network_resources.update"
    NETWORK_MOUNT = "network_resources.mount"
    NETWORK_UNMOUNT = "network_resources.unmount"
    NETWORK_DELETE = "network_resources.delete"
    DOCKER_VIEW = "docker.view"
    DOCKER_CONTAINERS = "docker.manage_containers"
    DOCKER_IMAGES = "docker.manage_images"
    DOCKER_COMPOSE = "docker.manage_compose"
    DOCKER_INSTALL_ENGINE = "docker.install_engine"
    DOCKER_START_SERVICE = "docker.start_service"
    DOCKER_STOP_SERVICE = "docker.stop_service"
    DOCKER_UPDATE_ENGINE = "docker.update_engine"
    DOCKER_VIEW_CONTAINERS = "docker.view_containers"
    DOCKER_CREATE_CONTAINER = "docker.create_container"
    DOCKER_START_CONTAINER = "docker.start_container"
    DOCKER_STOP_CONTAINER = "docker.stop_container"
    DOCKER_RESTART_CONTAINER = "docker.restart_container"
    DOCKER_REMOVE_CONTAINER = "docker.remove_container"
    DOCKER_INSPECT_CONTAINER = "docker.inspect_container"
    DOCKER_VIEW_LOGS = "docker.view_logs"
    DOCKER_VIEW_STATS = "docker.view_stats"
    DOCKER_VIEW_IMAGES = "docker.view_images"
    DOCKER_PULL_IMAGE = "docker.pull_image"
    DOCKER_REMOVE_IMAGE = "docker.remove_image"
    DOCKER_MANAGE_REGISTRIES = "docker.manage_registries"
    DOCKER_MANAGE_VOLUMES = "docker.manage_volumes"
    DOCKER_MANAGE_NETWORKS = "docker.manage_networks"
    DOCKER_EXPORT_BACKUP = "docker.export_backup"
    DOCKER_RESTORE_BACKUP = "docker.restore_backup"
    DOCKER_PRUNE = "docker.prune"
    DOCKER_DIAGNOSTICS = "docker.diagnostics"
    DOCKER_HIGH_RISK = "docker.high_risk"
    DNS_VIEW = "dns.view"
    DNS_CONFIGURE = "dns.configure"
    DATABASES_VIEW = "databases.view"
    DATABASES_CONFIGURE = "databases.configure"
    DATABASES_BACKUP = "databases.backup"
    DATABASES_RESTORE = "databases.restore"
    HOMEASSISTANT_VIEW = "homeassistant.view"
    HOMEASSISTANT_OPERATE = "homeassistant.operate"
    ANSIBLE_VIEW = "ansible-controller.view"
    ANSIBLE_INSTALL = "ansible-controller.install"
    ANSIBLE_CONFIGURE = "ansible-controller.configure"
    ANSIBLE_HOSTS_VIEW = "ansible-controller.hosts.view"
    ANSIBLE_HOSTS_MANAGE = "ansible-controller.hosts.manage"
    ANSIBLE_DISCOVERY = "ansible-controller.discovery"
    ANSIBLE_CREDENTIALS_VIEW = "ansible-controller.credentials.view"
    ANSIBLE_CREDENTIALS_MANAGE = "ansible-controller.credentials.manage"
    ANSIBLE_PROJECTS_VIEW = "ansible-controller.projects.view"
    ANSIBLE_PROJECTS_MANAGE = "ansible-controller.projects.manage"
    ANSIBLE_PLAYBOOKS_VIEW = "ansible-controller.playbooks.view"
    ANSIBLE_PLAYBOOKS_MANAGE = "ansible-controller.playbooks.manage"
    ANSIBLE_JOBS_LAUNCH = "ansible-controller.jobs.launch"
    ANSIBLE_JOBS_CANCEL = "ansible-controller.jobs.cancel"
    ANSIBLE_SCHEDULES_MANAGE = "ansible-controller.schedules.manage"
    ANSIBLE_AUDIT_VIEW = "ansible-controller.audit.view"
    ANSIBLE_BACKUP = "ansible-controller.backup"
    ANSIBLE_RESTORE = "ansible-controller.restore"
    LOGS_VIEW_OWN = "logs.view_own"
    LOGS_VIEW_SYSTEM = "logs.view_system"
    LOGS_VIEW_KERNEL = "logs.view_kernel"
    LOGS_VIEW_SERVICES = "logs.view_services"
    LOGS_VIEW_SECURITY = "logs.view_security"
    LOGS_VIEW_WEBNAS = "logs.view_webnas"
    LOGS_VIEW_CONTAINERS = "logs.view_containers"
    LOGS_LIVE = "logs.live"
    LOGS_EXPORT = "logs.export"
    LOGS_SAVED_VIEWS_MANAGE = "logs.saved_views.manage"
    SYSTEM_STATUS = "system.status"
    SYSTEM_LOGS = "system.logs"
    SYSTEM_RESTART = "system.restart"


_READ_OPERATIONS = {"view", "read", "download", "view_own", "view_all", "logs", "status", "diagnostics", "live", "export"}
_CRITICAL = {Permission.USERS_DELETE, Permission.GROUPS_DELETE, Permission.ACCESS_MANAGE_ROLES, Permission.SYSTEM_RESTART, Permission.MODULES_UNINSTALL, Permission.MODULES_BACKUP_RESTORE, Permission.DOCKER_INSTALL_ENGINE, Permission.DOCKER_UPDATE_ENGINE, Permission.DOCKER_RESTORE_BACKUP, Permission.DOCKER_PRUNE, Permission.DOCKER_HIGH_RISK}
_APPLICATIONS: dict[str, list[str]] = {
    "files": ["files"],
    "transfers": ["transfers"],
    "settings": ["settings"],
    "users": ["identity"],
    "groups": ["identity"],
    "access": ["identity"],
    "audit": ["activity"],
    "modules": ["modules", "store"],
    "services": ["services"],
    "updates": ["modules", "settings"],
    "network_resources": ["settings"],
    "docker": ["module:docker"],
    "dns": ["module:pihole", "module:adguard-home"],
    "databases": ["module:postgresql", "module:mariadb", "module:redis"],
    "homeassistant": ["module:home-assistant"],
    "ansible-controller": ["module:ansible-controller"],
    "logs": ["logs"],
    "system": ["monitor", "logs", "settings"],
}


def _metadata(permission: Permission) -> PermissionMetadata:
    category, operation = permission.value.split(".", 1)
    mutating = operation not in _READ_OPERATIONS and not operation.startswith("view") and not operation.endswith(".view")
    risk = PermissionRisk.critical if permission in _CRITICAL else PermissionRisk.high if mutating else PermissionRisk.low
    return PermissionMetadata(
        id=permission.value,
        category=category,
        operation=operation,
        applications=_APPLICATIONS[category],
        risk=risk,
        mutating=mutating,
        label_key=f"permissions.{permission.value}",
        description_key=f"permissions.category.{category}.description",
    )


PERMISSION_REGISTRY: dict[str, PermissionMetadata] = {item.value: _metadata(item) for item in Permission}

LEGACY_PERMISSION_MAP: dict[str, str] = {
    "apps.files": Permission.FILES_VIEW.value,
    "apps.settings": Permission.SETTINGS_VIEW_OWN.value,
    "apps.monitor": Permission.SYSTEM_STATUS.value,
    "apps.transfers": Permission.TRANSFERS_VIEW_OWN.value,
    "modules.operate": Permission.MODULES_CONFIGURE.value,
    "modules.configure": Permission.MODULES_CONFIGURE.value,
    "modules.install": Permission.MODULES_INSTALL.value,
    "updates.view": Permission.UPDATES_VIEW.value,
    "updates.apply": Permission.UPDATES_APPLY.value,
    "docker.view": Permission.DOCKER_VIEW.value,
    "docker.operate": Permission.DOCKER_CONTAINERS.value,
    "docker.compose": Permission.DOCKER_COMPOSE.value,
    "dns.view": Permission.DNS_VIEW.value,
    "dns.configure": Permission.DNS_CONFIGURE.value,
    "databases.view": Permission.DATABASES_VIEW.value,
    "databases.backup": Permission.DATABASES_BACKUP.value,
    "databases.restore": Permission.DATABASES_RESTORE.value,
    "homeassistant.view": Permission.HOMEASSISTANT_VIEW.value,
    "homeassistant.operate": Permission.HOMEASSISTANT_OPERATE.value,
    "rbac.manage": Permission.ACCESS_MANAGE_ROLES.value,
    "audit.view": Permission.AUDIT_VIEW_ALL.value,
    "widgets.manage": Permission.SETTINGS_EDIT_OWN.value,
}


def normalize_permission(value: str | Permission) -> str:
    raw = value.value if isinstance(value, Permission) else str(value)
    normalized = LEGACY_PERMISSION_MAP.get(raw, raw)
    if normalized not in PERMISSION_REGISTRY:
        raise ValueError(f"unknown permission: {raw}")
    return normalized


def normalize_permissions(values: list[str]) -> list[str]:
    return list(dict.fromkeys(normalize_permission(item) for item in values))


ALL_PERMISSIONS = set(PERMISSION_REGISTRY)

_FILES = {item.value for item in Permission if item.value.startswith("files.")}
_TRANSFERS_OWN = {Permission.TRANSFERS_VIEW_OWN.value, Permission.TRANSFERS_CREATE.value, Permission.TRANSFERS_PAUSE.value, Permission.TRANSFERS_RESUME.value, Permission.TRANSFERS_CANCEL.value, Permission.TRANSFERS_RETRY.value, Permission.TRANSFERS_CHANGE_PRIORITY.value}
_SETTINGS_OWN = {Permission.SETTINGS_VIEW_OWN.value, Permission.SETTINGS_EDIT_OWN.value, Permission.SETTINGS_CHANGE_OWN_PASSWORD.value}
_DOCKER_OPERATOR = {
    Permission.DOCKER_VIEW.value, Permission.DOCKER_CONTAINERS.value, Permission.DOCKER_IMAGES.value, Permission.DOCKER_COMPOSE.value,
    Permission.DOCKER_VIEW_CONTAINERS.value, Permission.DOCKER_CREATE_CONTAINER.value, Permission.DOCKER_START_CONTAINER.value,
    Permission.DOCKER_STOP_CONTAINER.value, Permission.DOCKER_RESTART_CONTAINER.value, Permission.DOCKER_REMOVE_CONTAINER.value,
    Permission.DOCKER_INSPECT_CONTAINER.value, Permission.DOCKER_VIEW_LOGS.value, Permission.DOCKER_VIEW_STATS.value,
    Permission.DOCKER_VIEW_IMAGES.value, Permission.DOCKER_PULL_IMAGE.value, Permission.DOCKER_REMOVE_IMAGE.value,
    Permission.DOCKER_MANAGE_REGISTRIES.value, Permission.DOCKER_MANAGE_VOLUMES.value, Permission.DOCKER_MANAGE_NETWORKS.value,
    Permission.DOCKER_EXPORT_BACKUP.value, Permission.DOCKER_DIAGNOSTICS.value,
}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.admin: set(ALL_PERMISSIONS),
    Role.operator: _FILES | _TRANSFERS_OWN | _SETTINGS_OWN | {
        Permission.SYSTEM_STATUS.value, Permission.SYSTEM_LOGS.value, Permission.SETTINGS_VIEW_SYSTEM.value,
        Permission.LOGS_VIEW_OWN.value, Permission.LOGS_VIEW_SYSTEM.value, Permission.LOGS_VIEW_KERNEL.value,
        Permission.LOGS_VIEW_SERVICES.value, Permission.LOGS_VIEW_WEBNAS.value, Permission.LOGS_VIEW_CONTAINERS.value,
        Permission.LOGS_LIVE.value, Permission.LOGS_EXPORT.value, Permission.LOGS_SAVED_VIEWS_MANAGE.value,
        Permission.USERS_VIEW.value, Permission.USERS_UPDATE.value, Permission.USERS_LOCK.value, Permission.USERS_UNLOCK.value, Permission.USERS_CHANGE_PASSWORD.value, Permission.USERS_MANAGE_GROUPS.value, Permission.USERS_MANAGE_QUOTA.value,
        Permission.GROUPS_VIEW.value, Permission.GROUPS_CREATE.value, Permission.GROUPS_MANAGE_MEMBERS.value, Permission.ACCESS_VIEW.value,
        Permission.AUDIT_VIEW_OWN.value, Permission.MODULES_VIEW.value, Permission.MODULES_CONFIGURE.value, Permission.MODULES_DIAGNOSTICS.value, Permission.MODULES_LOGS.value, Permission.MODULES_BACKUP_CREATE.value, Permission.MODULES_BACKUP_RESTORE.value,
        Permission.SERVICES_VIEW.value, Permission.SERVICES_START.value, Permission.SERVICES_STOP.value, Permission.SERVICES_RESTART.value, Permission.SERVICES_ENABLE.value, Permission.SERVICES_DISABLE.value, Permission.SERVICES_LOGS.value,
        Permission.UPDATES_VIEW.value, Permission.UPDATES_APPLY.value, Permission.NETWORK_VIEW.value, Permission.NETWORK_CREATE.value, Permission.NETWORK_UPDATE.value, Permission.NETWORK_MOUNT.value, Permission.NETWORK_UNMOUNT.value,
        *_DOCKER_OPERATOR,
        Permission.DNS_VIEW.value, Permission.DNS_CONFIGURE.value, Permission.DATABASES_VIEW.value, Permission.DATABASES_CONFIGURE.value, Permission.DATABASES_BACKUP.value, Permission.DATABASES_RESTORE.value,
        Permission.HOMEASSISTANT_VIEW.value, Permission.HOMEASSISTANT_OPERATE.value,
        Permission.ANSIBLE_VIEW.value, Permission.ANSIBLE_CONFIGURE.value, Permission.ANSIBLE_HOSTS_VIEW.value, Permission.ANSIBLE_HOSTS_MANAGE.value,
        Permission.ANSIBLE_DISCOVERY.value, Permission.ANSIBLE_CREDENTIALS_VIEW.value, Permission.ANSIBLE_CREDENTIALS_MANAGE.value,
        Permission.ANSIBLE_PROJECTS_VIEW.value, Permission.ANSIBLE_PROJECTS_MANAGE.value, Permission.ANSIBLE_PLAYBOOKS_VIEW.value,
        Permission.ANSIBLE_PLAYBOOKS_MANAGE.value, Permission.ANSIBLE_JOBS_LAUNCH.value, Permission.ANSIBLE_JOBS_CANCEL.value,
        Permission.ANSIBLE_SCHEDULES_MANAGE.value, Permission.ANSIBLE_BACKUP.value,
    },
    Role.auditor: {
        Permission.FILES_VIEW.value, Permission.FILES_READ.value, Permission.FILES_DOWNLOAD.value, Permission.TRANSFERS_VIEW_OWN.value, Permission.TRANSFERS_VIEW_ALL.value,
        Permission.SETTINGS_VIEW_OWN.value, Permission.SETTINGS_VIEW_SYSTEM.value, Permission.USERS_VIEW.value, Permission.GROUPS_VIEW.value, Permission.ACCESS_VIEW.value,
        Permission.AUDIT_VIEW_OWN.value, Permission.AUDIT_VIEW_ALL.value, Permission.AUDIT_EXPORT.value, Permission.MODULES_VIEW.value, Permission.MODULES_DIAGNOSTICS.value, Permission.MODULES_LOGS.value,
        Permission.SERVICES_VIEW.value, Permission.SERVICES_LOGS.value, Permission.UPDATES_VIEW.value, Permission.NETWORK_VIEW.value,
        Permission.DOCKER_VIEW.value, Permission.DOCKER_VIEW_CONTAINERS.value, Permission.DOCKER_INSPECT_CONTAINER.value,
        Permission.DOCKER_VIEW_LOGS.value, Permission.DOCKER_VIEW_STATS.value, Permission.DOCKER_VIEW_IMAGES.value, Permission.DOCKER_DIAGNOSTICS.value,
        Permission.DNS_VIEW.value, Permission.DATABASES_VIEW.value, Permission.HOMEASSISTANT_VIEW.value, Permission.SYSTEM_STATUS.value, Permission.SYSTEM_LOGS.value,
        Permission.LOGS_VIEW_OWN.value, Permission.LOGS_VIEW_SYSTEM.value, Permission.LOGS_VIEW_KERNEL.value,
        Permission.LOGS_VIEW_SERVICES.value, Permission.LOGS_VIEW_WEBNAS.value, Permission.LOGS_VIEW_CONTAINERS.value,
        Permission.LOGS_EXPORT.value,
        Permission.ANSIBLE_VIEW.value, Permission.ANSIBLE_HOSTS_VIEW.value, Permission.ANSIBLE_CREDENTIALS_VIEW.value,
        Permission.ANSIBLE_PROJECTS_VIEW.value, Permission.ANSIBLE_PLAYBOOKS_VIEW.value, Permission.ANSIBLE_AUDIT_VIEW.value,
    },
    Role.user: _FILES | _TRANSFERS_OWN | _SETTINGS_OWN | {Permission.AUDIT_VIEW_OWN.value, Permission.LOGS_VIEW_OWN.value, Permission.LOGS_SAVED_VIEWS_MANAGE.value, Permission.SYSTEM_STATUS.value},
}


def has_permission(username: str, permission: str | Permission) -> bool:
    try:
        expected = normalize_permission(permission)
    except ValueError:
        return False
    from .service import access_profile

    return expected in access_profile(username)["permissions"]


def authorize(user: SessionUser, permission: str | Permission) -> None:
    expected = normalize_permission(permission)
    if not has_permission(user.username, expected):
        identity_error(403, "PERMISSION_REQUIRED", "The operation is not allowed for this role", field=expected)


def require_permission(permission: str | Permission, *, mutating: bool | None = None) -> Callable[..., SessionUser]:
    expected = normalize_permission(permission)
    metadata = PERMISSION_REGISTRY[expected]
    require_mutation = metadata.mutating if mutating is None else mutating

    def dependency(request: Request) -> SessionUser:
        user = get_session_user(request)
        if require_mutation:
            require_csrf(request, user)
        authorize(user, expected)
        return user

    return dependency


def permission_dependency(permission: str | Permission, *, mutating: bool | None = None) -> Any:
    return Depends(require_permission(permission, mutating=mutating))
