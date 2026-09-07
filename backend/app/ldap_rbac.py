from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ldap3 import SUBTREE
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from pydantic import BaseModel, Field

from .identity.permission_service import permission_service
from .ldap_authentication import diagnostics, repository as ldap_repository
from .ldap_authentication.service import (
    LdapAuthenticationError,
    _bind_password,
    _close,
    _immutable_id,
    _service_connection,
    _text_attribute,
    _values,
)
from .rbac import rbac_read, rbac_write
from .security import SessionUser

router = APIRouter(prefix="/api/ldap", tags=["ldap", "rbac"])
MAX_DISCOVERY_RESULTS = 500
MAX_SYNC_RESULTS = 10000
MAX_NESTED_DEPTH = 16
MAX_NESTED_NODES = 10000


class LdapSyncInput(BaseModel):
    nested_groups: bool = True
    max_depth: int = Field(default=8, ge=1, le=MAX_NESTED_DEPTH)
    max_nodes: int = Field(default=5000, ge=1, le=MAX_NESTED_NODES)
    auto_create_local_groups: bool = False


class LdapMappingInput(BaseModel):
    external_group_id: str
    role_id: str


class RoleFromLdapGroupInput(BaseModel):
    external_group_id: str
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    permissions: list[dict[str, Any]] = Field(default_factory=list, max_length=1024)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _directory_connection(purpose: str):
    store = ldap_repository()
    settings = store.settings(include_secret_id=True)
    if not bool(settings.get("enabled")):
        raise HTTPException(409, "LDAP Authentication is disabled")
    try:
        password = _bind_password(settings, purpose=purpose)
        connection, endpoint = _service_connection(settings, password)
        return connection, endpoint, settings
    except LdapAuthenticationError as exc:
        raise HTTPException(
            502,
            detail={
                "code": "LDAP_UNAVAILABLE",
                "stage": getattr(exc, "stage", "connect"),
            },
        ) from exc


def _entries(connection) -> list[dict[str, Any]]:
    return [
        item
        for item in connection.response
        if isinstance(item, dict) and item.get("type") == "searchResEntry"
    ]


def _group_attributes(settings: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            filter(
                None,
                [
                    "cn",
                    "distinguishedName",
                    "objectGUID",
                    "entryUUID",
                    "ipaUniqueID",
                    "member",
                    "uniqueMember",
                    "memberUid",
                    str(settings.get("group_membership_attribute") or "memberOf"),
                ],
            )
        )
    )


def _user_attributes(settings: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            filter(
                None,
                [
                    str(settings.get("username_attribute") or "uid"),
                    str(settings.get("display_name_attribute") or "displayName"),
                    str(settings.get("email_attribute") or "mail"),
                    str(settings.get("immutable_id_attribute") or ""),
                    "objectGUID",
                    "entryUUID",
                    "ipaUniqueID",
                    "distinguishedName",
                    "uidNumber",
                    "gidNumber",
                    "homeDirectory",
                    str(settings.get("group_membership_attribute") or "memberOf"),
                ],
            )
        )
    )


def _safe_contains_filter(attribute: str, query: str) -> str:
    safe_attribute = "".join(
        character
        for character in attribute
        if character.isalnum() or character in {"-", "."}
    )
    if not safe_attribute or safe_attribute != attribute:
        raise HTTPException(422, "Invalid LDAP attribute")
    value = escape_filter_chars(query.strip())
    if not value:
        return "(objectClass=*)"
    return f"({safe_attribute}=*{value}*)"


def _search(
    connection,
    *,
    base: str,
    search_filter: str,
    attributes: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    bounded = min(max(int(limit), 1), MAX_DISCOVERY_RESULTS)
    try:
        connection.search(
            search_base=base,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=attributes,
            size_limit=bounded,
            time_limit=15,
            paged_size=min(bounded, 200),
        )
    except LDAPException as exc:
        raise HTTPException(
            502,
            detail={"code": "LDAP_SEARCH_FAILED"},
        ) from exc
    return _entries(connection)[:bounded]


def _paged_search(
    connection,
    *,
    base: str,
    search_filter: str,
    attributes: list[str],
    max_results: int = MAX_SYNC_RESULTS,
) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    cookie: bytes | str | None = None
    complete = False
    while len(result) < max_results:
        try:
            connection.search(
                search_base=base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=attributes,
                size_limit=0,
                time_limit=30,
                paged_size=200,
                paged_cookie=cookie,
            )
        except LDAPException as exc:
            raise HTTPException(
                502,
                detail={"code": "LDAP_SEARCH_FAILED"},
            ) from exc
        page = _entries(connection)
        result.extend(page[: max_results - len(result)])
        controls = (connection.result or {}).get("controls", {})
        paged = controls.get("1.2.840.113556.1.4.319", {})
        value = paged.get("value", {}) if isinstance(paged, dict) else {}
        cookie = value.get("cookie") if isinstance(value, dict) else None
        if not cookie:
            complete = True
            break
        if not page:
            break
    return result, complete


def _group_id(settings: dict[str, Any], entry: dict[str, Any]) -> str:
    try:
        return _immutable_id(settings, entry)
    except (KeyError, ValueError, TypeError):
        dn = str(entry.get("dn") or "").strip()
        if not dn:
            raise HTTPException(422, "LDAP group has no immutable ID or DN")
        return f"dn:{dn.casefold()}"


def _group_name(entry: dict[str, Any]) -> str:
    return _text_attribute(entry, "cn") or str(entry.get("dn") or "")


def _group_members(entry: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for attribute in ("member", "uniqueMember"):
        values.update(
            value.strip().casefold()
            for value in _values(entry, attribute)
            if value.strip()
        )
    return values


def _group_member_uids(entry: dict[str, Any]) -> set[str]:
    return {
        value.strip().casefold()
        for value in _values(entry, "memberUid")
        if value.strip()
    }


def expand_nested_groups(
    direct_dns: set[str],
    parent_map: dict[str, set[str]],
    *,
    max_depth: int,
    max_nodes: int,
) -> set[str]:
    """Return direct and ancestor DNs with cycle/depth/tree guards."""
    normalized = {item.casefold() for item in direct_dns if item}
    result = set(normalized)
    queue: deque[tuple[str, int]] = deque((item, 0) for item in normalized)
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for parent in parent_map.get(current, set()):
            parent = parent.casefold()
            if parent in result:
                continue
            if len(result) >= max_nodes:
                raise HTTPException(
                    422,
                    detail={
                        "code": "LDAP_NESTED_GROUP_LIMIT",
                        "max_nodes": max_nodes,
                    },
                )
            result.add(parent)
            queue.append((parent, depth + 1))
    return result


def _group_filter(settings: dict[str, Any]) -> str:
    if str(settings.get("directory_type") or "auto") == "active_directory":
        return "(objectCategory=group)"
    return (
        "(|(objectClass=groupOfNames)(objectClass=groupOfUniqueNames)"
        "(objectClass=posixGroup)(objectClass=group))"
    )


def _user_filter(settings: dict[str, Any]) -> str:
    if str(settings.get("directory_type") or "auto") == "active_directory":
        return "(&(objectCategory=person)(objectClass=user))"
    return "(|(objectClass=inetOrgPerson)(objectClass=posixAccount)(objectClass=person))"


def _optional_int(entry: dict[str, Any], attribute: str) -> int | None:
    value = _text_attribute(entry, attribute)
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _direct_group_dns(
    entry: dict[str, Any],
    settings: dict[str, Any],
    dn_memberships: dict[str, set[str]],
    uid_memberships: dict[str, set[str]],
) -> set[str]:
    result = {
        str(value).casefold()
        for value in _values(
            entry,
            str(settings.get("group_membership_attribute") or "memberOf"),
        )
        if str(value).strip()
    }
    dn = str(entry.get("dn") or "").casefold()
    username = _text_attribute(
        entry,
        str(settings.get("username_attribute") or "uid"),
    ).casefold()
    result.update(dn_memberships.get(dn, set()))
    result.update(uid_memberships.get(username, set()))
    return result


def sync_directory(
    payload: LdapSyncInput,
    actor: str,
    source_ip: str = "",
) -> dict[str, Any]:
    connection = None
    started = time.time()
    central = permission_service()
    store = central.repository
    ldap_store = ldap_repository()
    try:
        connection, endpoint, settings = _directory_connection("ldap-rbac-sync")
        group_base = str(
            settings.get("group_search_base") or settings.get("base_dn") or ""
        )
        groups, groups_complete = _paged_search(
            connection,
            base=group_base,
            search_filter=_group_filter(settings),
            attributes=_group_attributes(settings),
        )

        dn_to_group_id: dict[str, str] = {}
        dn_to_entry: dict[str, dict[str, Any]] = {}
        parent_map: dict[str, set[str]] = defaultdict(set)
        dn_memberships: dict[str, set[str]] = defaultdict(set)
        uid_memberships: dict[str, set[str]] = defaultdict(set)
        seen_ids: set[str] = set()
        for entry in groups:
            dn = str(entry.get("dn") or "").strip()
            if not dn:
                continue
            external_id = _group_id(settings, entry)
            group_id = store.upsert_external_group(
                "ldap",
                external_id,
                dn,
                _group_name(entry),
            )
            seen_ids.add(group_id)
            normalized_dn = dn.casefold()
            dn_to_group_id[normalized_dn] = group_id
            dn_to_entry[normalized_dn] = entry
            for member_dn in _group_members(entry):
                dn_memberships[member_dn].add(normalized_dn)
            for member_uid in _group_member_uids(entry):
                uid_memberships[member_uid].add(normalized_dn)

        for parent_dn, entry in dn_to_entry.items():
            for child_dn in _group_members(entry):
                if child_dn in dn_to_group_id:
                    parent_map[child_dn].add(parent_dn)

        for dn, group_id in dn_to_group_id.items():
            parent_ids = [
                dn_to_group_id[parent_dn]
                for parent_dn in parent_map.get(dn, set())
                if parent_dn in dn_to_group_id
            ]
            entry = dn_to_entry[dn]
            store.upsert_external_group(
                "ldap",
                _group_id(settings, entry),
                str(entry.get("dn") or ""),
                _group_name(entry),
                parent_ids=parent_ids,
            )

        user_base = str(
            settings.get("user_search_base") or settings.get("base_dn") or ""
        )
        users, users_complete = _paged_search(
            connection,
            base=user_base,
            search_filter=_user_filter(settings),
            attributes=_user_attributes(settings),
        )
        membership_count = 0
        identity_count = 0
        for entry in users:
            username = _text_attribute(
                entry,
                str(settings.get("username_attribute") or "uid"),
            )
            if not username:
                continue
            try:
                immutable_id = _immutable_id(settings, entry)
            except (KeyError, ValueError, TypeError):
                immutable_id = f"dn:{str(entry.get('dn') or '').casefold()}"
            direct_dns = _direct_group_dns(
                entry,
                settings,
                dn_memberships,
                uid_memberships,
            )
            effective_dns = direct_dns
            if payload.nested_groups:
                effective_dns = expand_nested_groups(
                    direct_dns,
                    parent_map,
                    max_depth=payload.max_depth,
                    max_nodes=payload.max_nodes,
                )
            direct_ids = {
                dn_to_group_id[dn]
                for dn in direct_dns
                if dn in dn_to_group_id
            }
            effective_ids = {
                dn_to_group_id[dn]
                for dn in effective_dns
                if dn in dn_to_group_id
            }
            groups_for_cache = sorted(direct_dns)
            ldap_store.remember_identity(
                immutable_id,
                username,
                str(entry.get("dn") or ""),
                display_name=_text_attribute(
                    entry,
                    str(settings.get("display_name_attribute") or "displayName"),
                ),
                email=_text_attribute(
                    entry,
                    str(settings.get("email_attribute") or "mail"),
                ),
                uid=_optional_int(entry, "uidNumber"),
                gid=_optional_int(entry, "gidNumber"),
                home=_text_attribute(entry, "homeDirectory"),
                groups=groups_for_cache,
                logged_in=False,
            )
            store.replace_external_memberships(
                "ldap",
                immutable_id,
                username,
                effective_ids,
                direct_ids,
            )
            membership_count += len(effective_ids)
            identity_count += 1

        mapping_count = 0
        for mapping in ldap_store.mappings():
            group_id = dn_to_group_id.get(str(mapping["group_dn"]).casefold())
            if not group_id:
                continue
            role_name = {
                "admin": "Administrator",
                "operator": "Operator",
                "auditor": "Auditor",
                "user": "User",
            }.get(str(mapping.get("role") or "user"), "User")
            role_id = f"system:{role_name.casefold().replace(' ', '-')}"
            store.map_external_group_role(
                group_id,
                role_id,
                actor,
                source_ip,
            )
            mapping_count += 1

        if payload.auto_create_local_groups:
            existing = {group["name"].casefold() for group in store.groups()}
            for group in store.external_groups():
                local_name = f"LDAP/{group['name']}"
                if local_name.casefold() in existing:
                    continue
                store.create_group(
                    {
                        "name": local_name,
                        "description": (
                            "Managed mirror of "
                            f"{group['distinguished_name']}"
                        ),
                        "source": "ldap",
                        "external_id": group["external_id"],
                        "distinguished_name": group["distinguished_name"],
                    },
                    actor,
                    source_ip,
                )
                existing.add(local_name.casefold())

        with store._lock, store._connect() as audit_connection:
            store._audit(
                audit_connection,
                actor,
                "ldap.sync",
                "ldap",
                {},
                {
                    "groups": len(seen_ids),
                    "identities": identity_count,
                    "memberships": membership_count,
                    "groups_complete": groups_complete,
                    "users_complete": users_complete,
                },
                source_ip,
            )
        central.invalidate()
        return {
            "status": "Online" if groups_complete and users_complete else "Degraded",
            "server": endpoint.label,
            "groups": len(seen_ids),
            "identities": identity_count,
            "effective_memberships": membership_count,
            "mappings_migrated": mapping_count,
            "nested_groups": payload.nested_groups,
            "groups_complete": groups_complete,
            "users_complete": users_complete,
            "duration_ms": round((time.time() - started) * 1000, 2),
        }
    except HTTPException:
        raise
    except LdapAuthenticationError as exc:
        return {
            "status": "Offline",
            "error": getattr(exc, "code", "LDAP_UNAVAILABLE"),
            "groups": 0,
            "identities": 0,
        }
    finally:
        _close(connection)


@router.post("/test")
def test_connection(_user: SessionUser = Depends(rbac_write)):
    result = diagnostics("")
    if result.get("overall") == "healthy":
        status = "Online"
    elif result.get("overall") == "degraded":
        status = "Degraded"
    else:
        status = "Offline"
    return {"status": status, "diagnostics": result}


@router.get("/groups")
def find_groups(
    q: str = Query(default="", max_length=256),
    limit: int = Query(default=100, ge=1, le=MAX_DISCOVERY_RESULTS),
    _user: SessionUser = Depends(rbac_read),
):
    connection = None
    try:
        connection, endpoint, settings = _directory_connection("ldap-rbac-discovery")
        base = str(
            settings.get("group_search_base") or settings.get("base_dn") or ""
        )
        search_filter = _safe_contains_filter("cn", q)
        entries = _search(
            connection,
            base=base,
            search_filter=search_filter,
            attributes=_group_attributes(settings),
            limit=limit,
        )
        items = []
        for entry in entries:
            external_id = _group_id(settings, entry)
            dn = str(entry.get("dn") or "")
            group_id = permission_service().repository.upsert_external_group(
                "ldap",
                external_id,
                dn,
                _group_name(entry),
            )
            items.append(
                {
                    "id": group_id,
                    "external_id": external_id,
                    "dn": dn,
                    "name": _group_name(entry),
                    "attributes": {"cn": _values(entry, "cn")},
                }
            )
        return {"server": endpoint.label, "items": items}
    finally:
        _close(connection)


@router.get("/users")
def find_users(
    q: str = Query(default="", max_length=256),
    limit: int = Query(default=100, ge=1, le=MAX_DISCOVERY_RESULTS),
    _user: SessionUser = Depends(rbac_read),
):
    connection = None
    try:
        connection, endpoint, settings = _directory_connection("ldap-rbac-discovery")
        username_attribute = str(settings.get("username_attribute") or "uid")
        base = str(
            settings.get("user_search_base") or settings.get("base_dn") or ""
        )
        entries = _search(
            connection,
            base=base,
            search_filter=_safe_contains_filter(username_attribute, q),
            attributes=_user_attributes(settings),
            limit=limit,
        )
        items = []
        for entry in entries:
            try:
                immutable_id = _immutable_id(settings, entry)
            except (KeyError, ValueError, TypeError):
                immutable_id = ""
            items.append(
                {
                    "external_id": immutable_id,
                    "dn": str(entry.get("dn") or ""),
                    "username": _text_attribute(entry, username_attribute),
                    "name": _text_attribute(
                        entry,
                        str(
                            settings.get("display_name_attribute")
                            or "displayName"
                        ),
                    ),
                    "email": _text_attribute(
                        entry,
                        str(settings.get("email_attribute") or "mail"),
                    ),
                    "groups": _values(
                        entry,
                        str(
                            settings.get("group_membership_attribute")
                            or "memberOf"
                        ),
                    ),
                }
            )
        return {"server": endpoint.label, "items": items}
    finally:
        _close(connection)


@router.post("/sync")
def sync(
    payload: LdapSyncInput,
    request: Request,
    user: SessionUser = Depends(rbac_write),
):
    return sync_directory(payload, user.username, _ip(request))


@router.get("/mappings")
def mappings(_user: SessionUser = Depends(rbac_read)):
    groups = {
        group["id"]: group
        for group in permission_service().repository.external_groups()
    }
    items = []
    for group in groups.values():
        for role_id in group.get("role_ids") or []:
            items.append(
                {
                    "external_group_id": group["id"],
                    "group_dn": group["distinguished_name"],
                    "group_name": group["name"],
                    "role_id": role_id,
                }
            )
    return {"items": items}


@router.post("/mappings")
def create_mapping(
    payload: LdapMappingInput,
    request: Request,
    user: SessionUser = Depends(rbac_write),
):
    permission_service().repository.map_external_group_role(
        payload.external_group_id,
        payload.role_id,
        user.username,
        _ip(request),
    )
    permission_service().invalidate()
    return {"ok": True}


@router.delete("/mappings/{group_id}/{role_id}")
def delete_mapping(
    group_id: str,
    role_id: str,
    request: Request,
    user: SessionUser = Depends(rbac_write),
):
    permission_service().repository.unmap_external_group_role(
        group_id,
        role_id,
        user.username,
        _ip(request),
    )
    permission_service().invalidate()
    return {"ok": True}


@router.post("/roles/from-group")
def role_from_group(
    payload: RoleFromLdapGroupInput,
    request: Request,
    user: SessionUser = Depends(rbac_write),
):
    group = next(
        (
            item
            for item in permission_service().repository.external_groups()
            if item["id"] == payload.external_group_id
        ),
        None,
    )
    if not group:
        raise HTTPException(404, "LDAP group not found")
    role = permission_service().repository.create_role(
        {
            "name": payload.name,
            "description": payload.description,
            "permissions": payload.permissions,
        },
        user.username,
        _ip(request),
    )
    permission_service().repository.map_external_group_role(
        group["id"],
        role["id"],
        user.username,
        _ip(request),
    )
    permission_service().invalidate()
    return {
        "role": role,
        "mapping": {
            "external_group_id": group["id"],
            "role_id": role["id"],
        },
    }
