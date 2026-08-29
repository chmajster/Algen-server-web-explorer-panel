from __future__ import annotations

from ..identity import permissions as registry
from ..identity.models import PermissionMetadata, PermissionRisk, Role

PERMISSION_DEFAULTS: dict[str, tuple[str, PermissionRisk, bool, tuple[Role, ...]]] = {
    "secrets-manager.view": ("secrets-manager", PermissionRisk.low, False, (Role.admin, Role.auditor)),
    "secrets-manager.manage": ("secrets-manager", PermissionRisk.high, True, (Role.admin,)),
    "secrets-manager.use": ("secrets-manager", PermissionRisk.high, True, (Role.admin,)),
    "secrets-manager.audit.view": ("secrets-manager", PermissionRisk.low, False, (Role.admin, Role.auditor)),
    "secrets-manager.backup": ("secrets-manager", PermissionRisk.high, True, (Role.admin,)),
    "secrets-manager.restore": ("secrets-manager", PermissionRisk.critical, True, (Role.admin,)),
    "secrets-manager.rotate": ("secrets-manager", PermissionRisk.critical, True, (Role.admin,)),
    "fail2ban-manager.view": ("fail2ban-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "fail2ban-manager.manage": ("fail2ban-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "fail2ban-manager.ban": ("fail2ban-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "fail2ban-manager.unban": ("fail2ban-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "fail2ban-manager.logs.view": ("fail2ban-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "fail2ban-manager.configure": ("fail2ban-manager", PermissionRisk.critical, True, (Role.admin,)),
    "webhook-manager.view": ("webhook-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "webhook-manager.manage": ("webhook-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "webhook-manager.test": ("webhook-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "webhook-manager.deliveries.view": ("webhook-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "webhook-manager.configure": ("webhook-manager", PermissionRisk.critical, True, (Role.admin,)),
    "jobs.view": ("job-queue-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "jobs.manage": ("job-queue-manager", PermissionRisk.high, True, (Role.admin,)),
    "jobs.cancel": ("job-queue-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "jobs.retry": ("job-queue-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "ntp.view": ("ntp-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "ntp.manage": ("ntp-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "ntp.resync": ("ntp-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "routing.view": ("routing-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "routing.manage": ("routing-manager", PermissionRisk.high, False, (Role.admin, Role.operator)),
    "routing.commit": ("routing-manager", PermissionRisk.critical, True, (Role.admin, Role.operator)),
    "login_history.view": ("login-history", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "login_history.sessions.terminate": ("login-history", PermissionRisk.critical, True, (Role.admin,)),
    "gitops.view": ("gitops-config-manager", PermissionRisk.low, False, (Role.admin, Role.operator, Role.auditor)),
    "gitops.manage": ("gitops-config-manager", PermissionRisk.high, True, (Role.admin,)),
    "gitops.commit": ("gitops-config-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "gitops.pull": ("gitops-config-manager", PermissionRisk.high, True, (Role.admin, Role.operator)),
    "gitops.push": ("gitops-config-manager", PermissionRisk.critical, True, (Role.admin,)),
    "gitops.rollback": ("gitops-config-manager", PermissionRisk.critical, True, (Role.admin,)),
}


def register_infrastructure_permissions() -> None:
    for permission_id, (application, risk, mutating, roles) in PERMISSION_DEFAULTS.items():
        if permission_id not in registry.PERMISSION_REGISTRY:
            category, operation = permission_id.split(".", 1)
            registry.PERMISSION_REGISTRY[permission_id] = PermissionMetadata(
                id=permission_id,
                category=category,
                operation=operation,
                applications=[f"module:{application}"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission_id}",
                description_key=f"permissions.category.{category}.description",
            )
        registry.ALL_PERMISSIONS.add(permission_id)
        for role in roles:
            registry.ROLE_PERMISSIONS[role].add(permission_id)


register_infrastructure_permissions()
