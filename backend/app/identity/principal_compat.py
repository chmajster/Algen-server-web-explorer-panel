"""Compatibility normalization at the legacy identity/RBAC boundary.

The central RBAC graph keys users by (provider, immutable identity id). Older
WebNAS call sites and a small number of extension modules still pass objects
that contain only ``username``. Normalize those objects before they reach the
central resolver; never collapse an explicit LDAP principal back to a username.

This module is transitional and can be removed after all legacy call sites use
``SessionUser`` directly.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException

from ..security import SessionUser


def coerce_session_user(user: Any) -> SessionUser:
    if isinstance(user, SessionUser):
        return user
    username = str(getattr(user, "username", "") or "").strip()
    provider_raw = str(getattr(user, "auth_provider", "") or "pam").strip()
    provider: Literal["local", "pam", "ldap"]
    if provider_raw == "local":
        provider = "local"
    elif provider_raw == "ldap":
        provider = "ldap"
    else:
        provider = "pam"
    identity_id = str(getattr(user, "identity_id", "") or "").strip() or username
    csrf_token = str(getattr(user, "csrf_token", "") or "")
    return SessionUser(
        username=username,
        csrf_token=csrf_token,
        auth_provider=provider,
        identity_id=identity_id,
    )


def install_principal_compatibility() -> None:
    from . import permissions as permissions_module
    from .permission_service import PermissionRepository, PermissionService

    if getattr(PermissionService, "_webnas_principal_compat", False):
        return

    original_sources = PermissionService.sources
    original_effective = PermissionService.effective
    original_effective_sources = PermissionRepository.effective_sources
    original_assign = PermissionRepository.assign_user_role
    original_revoke = PermissionRepository.revoke_user_role
    original_legacy_migrate = permissions_module._legacy_migrate
    original_authorize = permissions_module.authorize

    def sources(self: PermissionService, user: Any):
        return original_sources(self, coerce_session_user(user))

    def effective(self: PermissionService, user: Any):
        return original_effective(self, coerce_session_user(user))

    def effective_sources(self: PermissionRepository, user: Any):
        return original_effective_sources(self, coerce_session_user(user))

    def assign_user_role(
        self: PermissionRepository,
        user: Any,
        role_id: str,
        actor: str,
        source_ip: str = "",
    ):
        subject = coerce_session_user(user)
        # Legacy migration is username-based by definition. Never let that
        # compatibility path grant a local/PAM legacy role to an LDAP identity.
        if actor == "legacy-migration" and subject.auth_provider == "ldap":
            return None
        return original_assign(self, subject, role_id, actor, source_ip)

    def revoke_user_role(
        self: PermissionRepository,
        user: Any,
        role_id: str,
        actor: str,
        source_ip: str = "",
    ):
        return original_revoke(
            self,
            coerce_session_user(user),
            role_id,
            actor,
            source_ip,
        )

    def safe_legacy_migrate(user: Any) -> bool:
        subject = coerce_session_user(user)
        if subject.auth_provider == "ldap":
            return False
        return original_legacy_migrate(subject)

    def compatibility_authorize(user: Any, permission: Any) -> None:
        """Keep old monkeypatchable permission probes working during migration.

        Explicit LDAP principals stay on the provider-aware central resolver.
        Legacy PAM/local callers continue through ``has_permission`` so existing
        modules and tests that replace that facade do not silently bypass their
        authorization seam.
        """
        subject = coerce_session_user(user)
        if subject.auth_provider == "ldap":
            original_authorize(subject, permission)
            return
        if permissions_module.has_permission(subject.username, permission):
            return
        raise HTTPException(status_code=403, detail="Permission denied")

    setattr(PermissionService, "sources", sources)
    setattr(PermissionService, "effective", effective)
    setattr(PermissionService, "_webnas_principal_compat", True)
    setattr(PermissionRepository, "effective_sources", effective_sources)
    setattr(PermissionRepository, "assign_user_role", assign_user_role)
    setattr(PermissionRepository, "revoke_user_role", revoke_user_role)
    setattr(permissions_module, "_legacy_migrate", safe_legacy_migrate)
    setattr(permissions_module, "authorize", compatibility_authorize)
