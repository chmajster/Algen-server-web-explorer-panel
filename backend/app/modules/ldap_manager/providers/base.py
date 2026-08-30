from __future__ import annotations

import base64
from typing import Any

from ldap3 import BASE, LEVEL, MODIFY_DELETE, MODIFY_REPLACE, SUBTREE
from ldap3.core.exceptions import LDAPException

from ..connection import bind, close
from ..security import sanitize_attributes, validate_attribute, validate_dn


class ProviderOperationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UnsupportedDirectoryOperation(ProviderOperationError):
    def __init__(self, operation: str) -> None:
        super().__init__("LDAP_OPERATION_UNSUPPORTED", f"Directory provider does not support {operation}")


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)


def _entry(item: dict[str, Any]) -> dict[str, Any]:
    raw_attributes = item.get("attributes")
    attributes: dict[str, Any] = raw_attributes if isinstance(raw_attributes, dict) else {}
    return {
        "dn": str(item.get("dn") or ""),
        "attributes": {str(key): _json_value(value) for key, value in attributes.items()},
    }


class LdapDirectoryProvider:
    user_filter = "(objectClass=person)"
    group_filter = "(|(objectClass=groupOfNames)(objectClass=groupOfUniqueNames)(objectClass=posixGroup))"
    ou_filter = "(|(objectClass=organizationalUnit)(objectClass=container))"
    user_attributes = ["uid", "cn", "sn", "mail", "uidNumber", "gidNumber", "homeDirectory", "loginShell", "memberOf", "entryUUID"]
    group_attributes = ["cn", "member", "uniqueMember", "memberUid", "gidNumber", "entryUUID"]

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "users": True,
            "groups": True,
            "ous": True,
            "password_reset": False,
            "force_password_change": False,
            "enable_disable": False,
            "unlock": False,
            "schema": True,
            "nested_groups": True,
        }

    def search(
        self,
        *,
        base_dn: str = "",
        scope: str = "subtree",
        ldap_filter: str = "(objectClass=*)",
        attributes: list[str] | None = None,
        page_size: int = 100,
        cookie: str = "",
    ) -> dict[str, Any]:
        search_base = validate_dn(base_dn or str(self.config["base_dn"]))
        scope_value = {"base": BASE, "one": LEVEL, "subtree": SUBTREE}.get(scope)
        if scope_value is None:
            raise ValueError("Invalid LDAP search scope")
        requested = ["*"] if not attributes else [validate_attribute(item) if item != "*" else "*" for item in attributes]
        raw_cookie = b""
        if cookie:
            try:
                raw_cookie = base64.urlsafe_b64decode(cookie.encode("ascii"))
            except Exception as error:
                raise ValueError("Invalid LDAP paging cookie") from error
        bound = bind(self.config, purpose="ldap-manager-search")
        try:
            ok = bound.connection.search(
                search_base=search_base,
                search_filter=ldap_filter,
                search_scope=scope_value,
                attributes=requested,
                paged_size=page_size,
                paged_cookie=raw_cookie or None,
                time_limit=max(1, int(float(self.config.get("operation_timeout") or 15))),
            )
            if not ok and int(bound.connection.result.get("result", 0)) != 0:
                raise ProviderOperationError("LDAP_SEARCH_FAILED", str(bound.connection.result.get("description") or "LDAP search failed"))
            items = [_entry(item) for item in bound.connection.response if isinstance(item, dict) and item.get("type") == "searchResEntry"]
            controls = bound.connection.result.get("controls") if isinstance(bound.connection.result, dict) else {}
            page = controls.get("1.2.840.113556.1.4.319", {}).get("value", {}) if isinstance(controls, dict) else {}
            next_cookie = page.get("cookie") if isinstance(page, dict) else b""
            encoded = base64.urlsafe_b64encode(bytes(next_cookie)).decode("ascii") if next_cookie else ""
            return {"items": items, "count": len(items), "cookie": encoded, "endpoint": bound.endpoint}
        except LDAPException as error:
            raise ProviderOperationError("LDAP_SEARCH_FAILED", "LDAP search failed") from error
        finally:
            close(bound)

    def users(self, *, search: str = "", page_size: int = 100, cookie: str = "") -> dict[str, Any]:
        ldap_filter = self.user_filter if not search else self.user_search_filter(search)
        return self.search(ldap_filter=ldap_filter, attributes=self.user_attributes, page_size=page_size, cookie=cookie)

    def groups(self, *, search: str = "", page_size: int = 100, cookie: str = "") -> dict[str, Any]:
        ldap_filter = self.group_filter if not search else self.group_search_filter(search)
        return self.search(ldap_filter=ldap_filter, attributes=self.group_attributes, page_size=page_size, cookie=cookie)

    def ous(self, *, page_size: int = 200, cookie: str = "") -> dict[str, Any]:
        return self.search(ldap_filter=self.ou_filter, attributes=["ou", "cn", "objectClass"], page_size=page_size, cookie=cookie)

    def user_search_filter(self, search: str) -> str:
        from ..security import escaped_filter_value

        value = escaped_filter_value(search)
        return f"(&{self.user_filter}(|(uid=*{value}*)(cn=*{value}*)(mail=*{value}*)))"

    def group_search_filter(self, search: str) -> str:
        from ..security import escaped_filter_value

        value = escaped_filter_value(search)
        return f"(&{self.group_filter}(cn=*{value}*))"

    def entry(self, dn: str) -> dict[str, Any]:
        result = self.search(base_dn=dn, scope="base", ldap_filter="(objectClass=*)", attributes=["*"], page_size=1)
        if len(result["items"]) != 1:
            raise LookupError("LDAP entry not found")
        return result["items"][0]

    def create(self, dn: str, object_classes: list[str], attributes: dict[str, Any]) -> dict[str, Any]:
        dn = validate_dn(dn)
        safe = sanitize_attributes(attributes)
        bound = bind(self.config, purpose="ldap-manager-create")
        try:
            if not bound.connection.add(dn, object_class=object_classes, attributes=safe):
                raise ProviderOperationError("LDAP_ADD_FAILED", str(bound.connection.result.get("description") or "LDAP add failed"))
        finally:
            close(bound)
        return self.entry(dn)

    def update(self, dn: str, attributes: dict[str, Any], delete_attributes: list[str]) -> dict[str, Any]:
        dn = validate_dn(dn)
        safe = sanitize_attributes(attributes)
        changes: dict[str, list[tuple[int, list[Any]]]] = {}
        for name, value in safe.items():
            values = value if isinstance(value, list) else [value]
            changes[name] = [(MODIFY_REPLACE, values)]
        for raw_name in delete_attributes:
            name = validate_attribute(raw_name)
            if name.casefold() in {"userpassword", "unicodepwd", "objectguid", "entryuuid", "ipauniqueid"}:
                raise ValueError(f"LDAP attribute {name} cannot be removed with generic update")
            changes[name] = [(MODIFY_DELETE, [])]
        if not changes:
            return self.entry(dn)
        bound = bind(self.config, purpose="ldap-manager-update")
        try:
            if not bound.connection.modify(dn, changes):
                raise ProviderOperationError("LDAP_MODIFY_FAILED", str(bound.connection.result.get("description") or "LDAP modify failed"))
        finally:
            close(bound)
        return self.entry(dn)

    def delete(self, dn: str) -> None:
        dn = validate_dn(dn)
        bound = bind(self.config, purpose="ldap-manager-delete")
        try:
            if not bound.connection.delete(dn):
                raise ProviderOperationError("LDAP_DELETE_FAILED", str(bound.connection.result.get("description") or "LDAP delete failed"))
        finally:
            close(bound)

    def move(self, dn: str, new_rdn: str, new_superior: str = "") -> str:
        dn = validate_dn(dn)
        if "=" not in new_rdn or "\x00" in new_rdn:
            raise ValueError("Invalid new RDN")
        superior = validate_dn(new_superior) if new_superior else None
        bound = bind(self.config, purpose="ldap-manager-move")
        try:
            if not bound.connection.modify_dn(dn, new_rdn, delete_old_dn=True, new_superior=superior):
                raise ProviderOperationError("LDAP_MOVE_FAILED", str(bound.connection.result.get("description") or "LDAP move failed"))
        finally:
            close(bound)
        return f"{new_rdn},{superior}" if superior else new_rdn

    def _membership_value(self, attribute: str, member_dn: str) -> str:
        if attribute != "memberUid":
            return member_dn
        member = self.entry(member_dn)
        raw_uid = member.get("attributes", {}).get("uid")
        if isinstance(raw_uid, list):
            raw_uid = raw_uid[0] if raw_uid else ""
        uid = str(raw_uid or "").strip()
        if not uid:
            raise ProviderOperationError("LDAP_MEMBER_UID_MISSING", "POSIX group membership requires the member uid attribute")
        return uid

    def add_member(self, group_dn: str, member_dn: str) -> None:
        group_dn = validate_dn(group_dn)
        member_dn = validate_dn(member_dn)
        attribute = self.membership_attribute(group_dn)
        membership_value = self._membership_value(attribute, member_dn)
        bound = bind(self.config, purpose="ldap-manager-group-membership")
        try:
            from ldap3 import MODIFY_ADD

            if not bound.connection.modify(group_dn, {attribute: [(MODIFY_ADD, [membership_value])]}):
                raise ProviderOperationError("LDAP_MEMBERSHIP_ADD_FAILED", str(bound.connection.result.get("description") or "LDAP membership update failed"))
        finally:
            close(bound)

    def remove_member(self, group_dn: str, member_dn: str) -> None:
        group_dn = validate_dn(group_dn)
        member_dn = validate_dn(member_dn)
        attribute = self.membership_attribute(group_dn)
        membership_value = self._membership_value(attribute, member_dn)
        bound = bind(self.config, purpose="ldap-manager-group-membership")
        try:
            if not bound.connection.modify(group_dn, {attribute: [(MODIFY_DELETE, [membership_value])]}):
                raise ProviderOperationError("LDAP_MEMBERSHIP_REMOVE_FAILED", str(bound.connection.result.get("description") or "LDAP membership update failed"))
        finally:
            close(bound)

    def membership_attribute(self, group_dn: str) -> str:
        entry = self.entry(group_dn)
        classes = {str(item).casefold() for item in entry.get("attributes", {}).get("objectClass", [])}
        if "groupofuniquenames" in classes:
            return "uniqueMember"
        if "posixgroup" in classes and "groupofnames" not in classes:
            return "memberUid"
        return "member"

    def reset_password(self, dn: str, password: str, force_change: bool) -> None:
        raise UnsupportedDirectoryOperation("password reset")

    def set_enabled(self, dn: str, enabled: bool) -> None:
        raise UnsupportedDirectoryOperation("enable/disable")

    def unlock(self, dn: str) -> None:
        raise UnsupportedDirectoryOperation("unlock")

    def schema(self) -> dict[str, Any]:
        bound = bind(self.config, purpose="ldap-manager-schema")
        try:
            schema = bound.connection.server.schema
            if schema is None:
                return {"available": False, "object_classes": [], "attribute_types": []}
            object_classes = []
            for name, value in sorted(schema.object_classes.items()):
                object_classes.append({
                    "name": str(name),
                    "oid": str(getattr(value, "oid", "") or ""),
                    "must": [str(item) for item in getattr(value, "must_contain", []) or []],
                    "may": [str(item) for item in getattr(value, "may_contain", []) or []],
                    "description": str(getattr(value, "description", "") or ""),
                })
            attribute_types = []
            for name, value in sorted(schema.attribute_types.items()):
                attribute_types.append({
                    "name": str(name),
                    "oid": str(getattr(value, "oid", "") or ""),
                    "syntax": str(getattr(value, "syntax", "") or ""),
                    "description": str(getattr(value, "description", "") or ""),
                })
            return {"available": True, "object_classes": object_classes, "attribute_types": attribute_types}
        finally:
            close(bound)

    def root_dse(self) -> dict[str, Any]:
        bound = bind(self.config, purpose="ldap-manager-diagnostics")
        try:
            ok = bound.connection.search(
                search_base="",
                search_filter="(objectClass=*)",
                search_scope=BASE,
                attributes=["supportedControl", "supportedLDAPVersion", "vendorName", "vendorVersion", "namingContexts", "defaultNamingContext", "rootDomainNamingContext"],
                size_limit=1,
            )
            entries = [_entry(item) for item in bound.connection.response if isinstance(item, dict) and item.get("type") == "searchResEntry"] if ok else []
            return {"endpoint": bound.endpoint, "entry": entries[0] if entries else {}}
        finally:
            close(bound)
