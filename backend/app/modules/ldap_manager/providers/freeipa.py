from __future__ import annotations

from .openldap import OpenLdapProvider


class FreeIpaProvider(OpenLdapProvider):
    user_filter = "(&(objectClass=inetOrgPerson)(objectClass=posixAccount))"
    group_filter = "(|(objectClass=ipaUserGroup)(objectClass=posixGroup)(objectClass=groupOfNames))"
    user_attributes = [
        "uid", "cn", "sn", "givenName", "displayName", "mail", "uidNumber", "gidNumber",
        "homeDirectory", "loginShell", "memberOf", "entryUUID", "ipaUniqueID", "nsAccountLock",
        "krbPasswordExpiration",
    ]
    group_attributes = ["cn", "member", "memberUid", "gidNumber", "entryUUID", "ipaUniqueID"]
