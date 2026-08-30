from __future__ import annotations

from ldap3 import MODIFY_REPLACE

from ..connection import bind, close
from ..security import validate_dn
from .base import LdapDirectoryProvider, ProviderOperationError


class OpenLdapProvider(LdapDirectoryProvider):
    user_filter = "(|(objectClass=inetOrgPerson)(objectClass=posixAccount))"
    group_filter = "(|(objectClass=groupOfNames)(objectClass=groupOfUniqueNames)(objectClass=posixGroup))"
    user_attributes = ["uid", "cn", "sn", "givenName", "mail", "uidNumber", "gidNumber", "homeDirectory", "loginShell", "memberOf", "entryUUID", "pwdReset"]
    group_attributes = ["cn", "member", "uniqueMember", "memberUid", "gidNumber", "entryUUID"]

    @property
    def capabilities(self) -> dict[str, bool]:
        return {**super().capabilities, "password_reset": True, "force_password_change": True}

    def reset_password(self, dn: str, password: str, force_change: bool) -> None:
        dn = validate_dn(dn)
        bound = bind(self.config, purpose="ldap-manager-password-reset")
        try:
            changed = bound.connection.extend.standard.modify_password(dn, new_password=password)
            if not changed:
                raise ProviderOperationError("LDAP_PASSWORD_RESET_FAILED", "OpenLDAP password modify operation failed")
            if force_change:
                # pwdReset is part of the common password-policy overlay. If
                # the server does not expose it, report the capability error
                # instead of pretending the flag was applied.
                if not bound.connection.modify(dn, {"pwdReset": [(MODIFY_REPLACE, ["TRUE"])]}):
                    raise ProviderOperationError("LDAP_FORCE_PASSWORD_CHANGE_FAILED", "Password was reset but pwdReset could not be set")
        finally:
            close(bound)
