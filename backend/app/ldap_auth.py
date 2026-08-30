"""Compatibility import for the LDAP Authentication subsystem.

LDAP Authentication now lives in :mod:`app.ldap_authentication`.  Keep this
module only as an import bridge for third-party integrations and older tests;
it owns no state, credentials, connection handling, or directory-management
logic.  LDAP Manager is a separate subsystem under ``app.modules.ldap_manager``.
"""

from .ldap_authentication import *  # noqa: F401,F403
from .ldap_authentication import repository as settings_repository
from .ldap_authentication.models import LdapAuthenticationSettingsInput as LdapSettingsInput

# Deliberately do not expose LDAP Manager APIs or credentials here.
