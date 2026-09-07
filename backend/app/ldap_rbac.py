from __future__ import annotations

import time
import uuid
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
    _attribute,
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
        raise HTTPException(502, detail={"code": "LDAP_UNAVAILABLE", "stage": getattr(exc, "stage", "connect")}) from exc


def _entries(connection) -> list[dict[str, Any]]:
    return [item for item in connection.response if isinstance(item, dict) and item.get("type") == "searchResEntry"]


def _group_attributes(settings: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(filter(None, [
        "cn", "distinguishedName", "objectGUID", "entryUUID", "ipaUniqueID", "member", "uniqueMember", "memberUid",
        str(settings.get("group_membership_attribute") or "memberOf"),
    ])))


def _user_attributes(settings: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(filter(None, [
        str(settings.get("username_attribute") or "uid"), str(settings.get("display_name_attribute") or "displayName"),
        str(settings.get("email_attribute") or "mail"), str(settings.get("immutable_id_attribute") or ""),
        "objectGUID", "entryUUID", "ipaUniqueID", "distinguishedName", str(settings.get("group_membership_attribute") or "memberOf"),
    ])))


def _search(connection, *, base: str, search_filter: str, attributes: list[str], limit: int) -> list[dict[str, Any]]:
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
        raise HTTPException(502, detail={"code": "LDAP_SEARCH_FAILED"}) from exc
    return _entries(connection)[:bounded]


def _safe_contains_filter(attribute: str, query: str) -> str:
    safe_attribute = "".join(ch for ch in attribute if ch.isalnum() or ch in {"-", "."})
    if not safe_attribute or safe_attribute != attribute:
        raise HTTPException(422, "Invalid LDAP attribute")
    value = escape_filter_chars(query.strip())
    return f"({safe_attribute}=*{value}*)" if value else "(objectClass=*)"


def _group_id(settings: dict[str, Any], entry: dict[str, Any]) -> str:
    try:
        return _immutable_id(settings, entry)
    except Exception:
        dn = str(entry.get("dn") or "").strip()
        if not dn:
            raise HTTPException(422, "LDAP group has no immutable ID or DN")
        return f"dn:{dn.casefold()}"


def _group_name(entry: dict[str, Any]) -> str:
    return _text_attribute(entry, "cn") or str(entry.get("dn") or "")


def _group_members(entry: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for attr in ("member", "uniqueMember"):
        values.update(value.strip().casefold() for value in _values(entry, attr) if value.strip())
    return values


def expand_nested_groups(direct_dns: set[str], parent_map: dict[str, set[str]], *, max_depth: int, max_nodes: int) -> set[str]:
    """Return direct + ancestor DNs with cycle/depth/tree guards."""
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
                raise HTTPException(422, detail={"code": "LDAP_NESTED_GROUP_LIMIT", "max_nodes": max_nodes})
            result.add(parent)
            queue.append((parent, depth + 1))
    return result


def _discover_all_groups(connection, settings: dict[str, Any], limit: int = MAX_DISCOVERY_RESULTS) -> list[dict[str, Any]]:
    base = str(settings.get("group_search_base") or settings.get("base_dn") or "")
    directory_type = str(settings.get("directory_type") or "auto")
    if directory_type == "active_directory":
        group_filter = "(objectCategory=group)"
    else:
        group_filter = "(|(objectClass=groupOfNames)(objectClass=groupOfUniqueNames)(objectClass=posixGroup)(objectClass=group))"
    return _search(connection, base=base, search_filter=group_filter, attributes=_group_attributes(settings), limit=limit)


def _legacy_role_id(role: str) -> str:
    role_name = {"admin": "Administrator", "operator": "Operator", "auditor": "Auditor", "user": "User"}.get(role, "User")
    return f"system:{role_name.casefold().replace(' ', '-')}"


def sync_directory(payload: LdapSyncInput, actor: str, source_ip: str = "") -> dict[str, Any]:
    connection = None
    started = time.time()
    central = permission_service()
    store = central.repository
    ldap_store = ldap_repository()
    try:
        connection, endpoint, settings = _directory_connection("ldap-rbac-sync")
        groups = _discover_all_groups(connection, settings)
        dn_to_group_id: dict[str, str] = {}
        dn_to_entry: dict[str, dict[str, Any]] = {}
        parent_map: dict[str, set[str]] = defaultdict(set)
        seen_ids: set[str] = set()
        for entry in groups:
            dn = str(entry.get("dn") or "").strip()
            if not dn:
                continue
            external_id = _group_id(settings, entry)
            group_id = store.upsert_external_group("ldap", external_id, dn, _group_name(entry))
            seen_ids.add(group_id)
            dn_to_group_id[dn.casefold()] = group_id
            dn_to_entry[dn.casefold()] = entry
        for parent_dn, entry in dn_to_entry.items():
            for child_dn in _group_members(entry):
                if child_dn in dn_to_group_id:
                    parent_map[child_dn].add(parent_dn)

        # Preserve external group records not seen during a successful bounded
        # sync, but mark them missing instead of deleting them.
        with store._lock, store._connect() as db:
            if seen_ids:
                marks = ",".join("?" for _ in seen_ids)
                db.execute(f"UPDATE rbac_external_groups SET status='missing_from_source' WHERE provider_id='ldap' AND id NOT IN ({marks})", tuple(seen_ids))

        identities = []
        with ldap_store.connect() as db:
            identities = [ldap_store._identity(row) for row in db.execute("SELECT * FROM ldap_auth_identities_v2 ORDER BY username")]
        membership_count = 0
        for identity in identities:
            direct_dns = {str(dn).casefold() for dn in identity.get("groups") or [] if str(dn).strip()}
            effective_dns = expand_nested_groups(direct_dns, parent_map, max_depth=payload.max_depth, max_nodes=payload.max_nodes) if payload.nested_groups else direct_dns
            effective_ids = {dn_to_group_id[dn] for dn in effective_dns if dn in dn_to_group_id}
            direct_ids = {dn_to_group_id[dn] for dn in direct_dns if dn in dn_to_group_id}
            store.replace_external_memberships("ldap", str(identity["immutable_id"]), str(identity["username"]), effective_ids, direct_ids)
            membership_count += len(effective_ids)

        # Migrate the existing LDAP group->legacy role mappings into the dynamic
        # many-to-many graph. Permissions are never guessed from group names.
        mapping_count = 0
        for mapping in ldap_store.mappings():
            group_id = dn_to_group_id.get(str(mapping["group_dn"]).casefold())
            if group_id:
                store.map_external_group_role(group_id, _legacy_role_id(str(mapping.get("role") or "user")), actor, source_ip)
                mapping_count += 1

        if payload.auto_create_local_groups:
            existing = {g["name"].casefold() for g in store.groups()}
            for group in store.external_groups():
                local_name = f"LDAP/{group['name']}"
                if local_name.casefold() not in existing:
                    try:
                        store.create_group({"name": local_name, "description": f"Managed mirror of {group['distinguished_name']}", "source": "ldap", "external_id": group["external_id"], "distinguished_name": group["distinguished_name"]}, actor, source_ip)
                        existing.add(local_name.casefold())
                    except Exception:
                        pass
        central.invalidate()
        return {
            "status": "Online", "server": endpoint.label, "groups": len(seen_ids), "identities": len(identities),
            "effective_memberships": membership_count, "mappings_migrated": mapping_count,
            "nested_groups": payload.nested_groups, "duration_ms": round((time.time() - started) * 1000, 2),
        }
    except HTTPException:
        raise
    except LdapAuthenticationError as exc:
        return {"status": "Offline", "error": getattr(exc, "code", "LDAP_UNAVAILABLE"), "groups": 0, "identities": 0}
    finally:
        _close(connection)


@router.post("/test")
def test_connection(_user: SessionUser = Depends(rbac_write)):
    result = diagnostics("")
    status = "Online" if result.get("overall") == "healthy" else "Degraded" if result.get("overall") == "degraded" else "Offline"
    return {"status": status, "diagnostics": result}


@router.get("/groups")
def find_groups(q: str = Query(default="", max_length=256), limit: int = Query(default=100, ge=1, le=MAX_DISCOVERY_RESULTS), _user: SessionUser = Depends(rbac_read)):
    connection = None
    try:
        connection, endpoint, settings = _directory_connection("ldap-rbac-discovery")
        base = str(settings.get("group_search_base") or settings.get("base_dn") or "")
        entries = _search(connection, base=base, search_filter=_safe_contains_filter("cn", q), attributes=_group_attributes(settings), limit=limit)
        return {"server": endpoint.label, "items": [{"external_id": _group_id(settings,e), "dn": str(e.get("dn") or ""), "name": _group_name(e), "attributes": {"cn": _values(e,"cn")}} for e in entries]}
    finally:
        _close(connection)


@router.get("/users")
def find_users(q: str = Query(default="", max_length=256), limit: int = Query(default=100, ge=1, le=MAX_DISCOVERY_RESULTS), _user: SessionUser = Depends(rbac_read)):
    connection = None
    try:
        connection, endpoint, settings = _directory_connection("ldap-rbac-discovery")
        attr = str(settings.get("username_attribute") or "uid")
        base = str(settings.get("user_search_base") or settings.get("base_dn") or "")
        entries = _search(connection, base=base, search_filter=_safe_contains_filter(attr,q), attributes=_user_attributes(settings), limit=limit)
        items = []
        for entry in entries:
            try: immutable = _immutable_id(settings,entry)
            except Exception: immutable = ""
            items.append({"external_id": immutable, "dn": str(entry.get("dn") or ""), "username": _text_attribute(entry,attr), "name": _text_attribute(entry,str(settings.get("display_name_attribute") or "displayName")), "email": _text_attribute(entry,str(settings.get("email_attribute") or "mail")), "groups": _values(entry,str(settings.get("group_membership_attribute") or "memberOf"))})
        return {"server": endpoint.label, "items": items}
    finally:
        _close(connection)


@router.post("/sync")
def sync(payload: LdapSyncInput, request: Request, user: SessionUser = Depends(rbac_write)):
    return sync_directory(payload, user.username, _ip(request))


@router.get("/mappings")
def mappings(_user: SessionUser = Depends(rbac_read)):
    groups = {g["id"]: g for g in permission_service().repository.external_groups()}
    items = []
    for group in groups.values():
        for role_id in group.get("role_ids") or []:
            items.append({"external_group_id": group["id"], "group_dn": group["distinguished_name"], "group_name": group["name"], "role_id": role_id})
    return {"items": items}


@router.post("/mappings")
def create_mapping(payload: LdapMappingInput, request: Request, user: SessionUser = Depends(rbac_write)):
    permission_service().repository.map_external_group_role(payload.external_group_id,payload.role_id,user.username,_ip(request)); permission_service().invalidate(); return {"ok": True}


@router.post("/roles/from-group")
def role_from_group(payload: RoleFromLdapGroupInput, request: Request, user: SessionUser = Depends(rbac_write)):
    group = next((g for g in permission_service().repository.external_groups() if g["id"] == payload.external_group_id), None)
    if not group: raise HTTPException(404,"LDAP group not found")
    role = permission_service().repository.create_role({"name":payload.name,"description":payload.description,"permissions":payload.permissions},user.username,_ip(request))
    permission_service().repository.map_external_group_role(group["id"],role["id"],user.username,_ip(request)); permission_service().invalidate()
    return {"role": role, "mapping": {"external_group_id": group["id"], "role_id": role["id"]}}
