from .models import (
    LdapAccessPolicyInput,
    LdapAuthenticationSettingsInput,
    LdapDiagnosticsRequest,
    LdapGroupMappingInput,
    LdapRefreshRequest,
    LdapServerInput,
)
from .repository import LdapAuthenticationRepository, repository
from .service import (
    AuthenticatedIdentity,
    LdapAuthenticationError,
    LdapConfigurationError,
    LdapInvalidCredentials,
    LdapServiceUnavailable,
    authenticate_ldap as _authenticate_ldap,
    diagnostics,
    is_ldap_identity,
    ldap_enabled,
    ldap_group_search_filter,
    ldap_home,
    ldap_user_search_filter,
    refresh_identity_policy,
    validate_ldap_session as _validate_ldap_session,
)


def _project(identity_id: str, username: str) -> None:
    # Delayed import avoids an authentication<->RBAC import cycle. Projection
    # uses only the already persisted LDAP cache and never performs network I/O.
    from ..identity.ldap_projection import project_cached_ldap_identity

    project_cached_ldap_identity(identity_id, username)


def authenticate_ldap(username: str, password: str) -> AuthenticatedIdentity:
    identity = _authenticate_ldap(username, password)
    _project(identity.identity_id, identity.username)
    return identity


def validate_ldap_session(
    identity_id: str,
    username: str,
    *,
    force_refresh: bool = False,
) -> bool:
    valid = _validate_ldap_session(
        identity_id,
        username,
        force_refresh=force_refresh,
    )
    if valid:
        _project(identity_id, username)
    return valid


__all__ = [
    "AuthenticatedIdentity",
    "LdapAccessPolicyInput",
    "LdapAuthenticationError",
    "LdapAuthenticationRepository",
    "LdapAuthenticationSettingsInput",
    "LdapConfigurationError",
    "LdapDiagnosticsRequest",
    "LdapGroupMappingInput",
    "LdapInvalidCredentials",
    "LdapRefreshRequest",
    "LdapServerInput",
    "LdapServiceUnavailable",
    "authenticate_ldap",
    "diagnostics",
    "is_ldap_identity",
    "ldap_enabled",
    "ldap_group_search_filter",
    "ldap_home",
    "ldap_user_search_filter",
    "refresh_identity_policy",
    "repository",
    "validate_ldap_session",
]
