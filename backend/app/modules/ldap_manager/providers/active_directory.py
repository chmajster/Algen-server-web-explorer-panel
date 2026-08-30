from __future__ import annotations

from ldap3 import MODIFY_REPLACE

from ..connection import bind, close
from ..security import escaped_filter_value, validate_dn
from .base import LdapDirectoryProvider, ProviderOperationError


ACCOUNT_DISABLED = 0x0002


class ActiveDirectoryProvider(LdapDirectoryProvider):
    user_filter = "(&(objectCategory=person)(objectClass=user))"
    group_filter = "(&(objectCategory=group)(objectClass=group))"
    ou_filter = "(|(objectClass=organizationalUnit)(objectClass=container))"
    user_attributes = [
        "sAMAccountName", "userPrincipalName", "cn", "displayName", "givenName", "sn", "mail",
        "objectGUID", "objectSid", "memberOf", "userAccountControl", "pwdLastSet", "lockoutTime",
        "accountExpires", "uidNumber", "gidNumber", "unixHomeDirectory",
    ]
    group_attributes = ["cn", "sAMAccountName", "member", "memberOf", "objectGUID", "objectSid", "groupType"]

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            **super().capabilities,
            "password_reset": True,
            "force_password_change": True,
            "enable_disable": True,
            "unlock": True,
        }

    def user_search_filter(self, search: str) -> str:
        value = escaped_filter_value(search)
        return f"(&{self.user_filter}(|(sAMAccountName=*{value}*)(userPrincipalName=*{value}*)(displayName=*{value}*)(mail=*{value}*)))"

    def membership_attribute(self, group_dn: str) -> str:
        _ = group_dn
        return "member"

    def reset_password(self, dn: str, password: str, force_change: bool) -> None:
        dn = validate_dn(dn)
        bound = bind(self.config, purpose="ldap-manager-password-reset")
        try:
            changed = bound.connection.extend.microsoft.modify_password(dn, password)
            if not changed:
                raise ProviderOperationError("LDAP_PASSWORD_RESET_FAILED", "Active Directory password reset failed")
            if force_change and not bound.connection.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])] }):
                raise ProviderOperationError("LDAP_FORCE_PASSWORD_CHANGE_FAILED", "Password was reset but pwdLastSet could not be changed")
        finally:
            close(bound)

    def _uac(self, dn: str) -> int:
        entry = self.entry(validate_dn(dn))
        raw = entry.get("attributes", {}).get("userAccountControl", 0)
        if isinstance(raw, list):
            raw = raw[0] if raw else 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ProviderOperationError("LDAP_UAC_UNAVAILABLE", "userAccountControl is unavailable")

    def set_enabled(self, dn: str, enabled: bool) -> None:
        dn = validate_dn(dn)
        current = self._uac(dn)
        next_value = current & ~ACCOUNT_DISABLED if enabled else current | ACCOUNT_DISABLED
        bound = bind(self.config, purpose="ldap-manager-account-state")
        try:
            if not bound.connection.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [next_value])] }):
                raise ProviderOperationError("LDAP_ACCOUNT_STATE_FAILED", "Active Directory account state update failed")
        finally:
            close(bound)

    def unlock(self, dn: str) -> None:
        dn = validate_dn(dn)
        bound = bind(self.config, purpose="ldap-manager-unlock")
        try:
            if not bound.connection.modify(dn, {"lockoutTime": [(MODIFY_REPLACE, [0])] }):
                raise ProviderOperationError("LDAP_UNLOCK_FAILED", "Active Directory unlock failed")
        finally:
            close(bound)
