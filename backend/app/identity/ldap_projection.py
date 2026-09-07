"""Project cached LDAP identity state into the central RBAC graph.

Authentication owns directory connectivity and persists verified identity/group
state. RBAC consumes that state; it does not perform a second network lookup on
an authorization request. This keeps login-time synchronization deterministic
and preserves the last known memberships while LDAP is unavailable.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from ..audit import logger
from ..ldap_authentication.repository import repository as ldap_repository
from .permission_service import permission_service

MAX_LOGIN_NESTED_DEPTH = 16
MAX_LOGIN_NESTED_NODES = 10000


def _system_role_id(role: str) -> str:
    name = {
        "admin": "Administrator",
        "operator": "Operator",
        "auditor": "Auditor",
        "user": "User",
    }.get(role.casefold(), "User")
    return f"system:{name.casefold().replace(' ', '-')}"


def _expand_parent_ids(
    direct_ids: set[str],
    groups: dict[str, dict[str, Any]],
) -> set[str]:
    result = set(direct_ids)
    queue: deque[tuple[str, int]] = deque((item, 0) for item in direct_ids)
    while queue:
        group_id, depth = queue.popleft()
        if depth >= MAX_LOGIN_NESTED_DEPTH:
            continue
        for parent_id in groups.get(group_id, {}).get("parent_ids") or []:
            parent_id = str(parent_id)
            if not parent_id or parent_id in result:
                continue
            if len(result) >= MAX_LOGIN_NESTED_NODES:
                logger.warning("ldap_rbac_login_projection_limit identity_group=%s", group_id)
                return result
            result.add(parent_id)
            queue.append((parent_id, depth + 1))
    return result


def project_cached_ldap_identity(identity_id: str, username: str) -> None:
    """Synchronize one cached LDAP principal into RBAC without network I/O."""
    if not identity_id or not username:
        return
    ldap_store = ldap_repository()
    identity = ldap_store.identity_by_id(identity_id) or ldap_store.identity_by_username(username)
    if not identity:
        return

    central = permission_service()
    store = central.repository
    direct_ids: set[str] = set()
    dn_to_id: dict[str, str] = {}
    for group_dn in identity.get("groups") or []:
        dn = str(group_dn).strip()
        if not dn:
            continue
        external_id = f"dn:{dn.casefold()}"
        group_id = store.upsert_external_group("ldap", external_id, dn, dn)
        direct_ids.add(group_id)
        dn_to_id[dn.casefold()] = group_id

    # Existing discovery/sync may know immutable IDs and parent relationships.
    # Prefer those records for DNs already present and keep the DN fallback only
    # when the directory has never been fully synchronized.
    external_groups = store.external_groups()
    for group in external_groups:
        dn = str(group.get("distinguished_name") or "").casefold()
        if dn and dn in dn_to_id:
            direct_ids.discard(dn_to_id[dn])
            direct_ids.add(str(group["id"]))
            dn_to_id[dn] = str(group["id"])

    groups_by_id = {str(group["id"]): group for group in store.external_groups()}
    effective_ids = _expand_parent_ids(direct_ids, groups_by_id)
    store.replace_external_memberships(
        "ldap",
        identity_id,
        username,
        effective_ids,
        direct_ids,
    )

    for mapping in ldap_store.mappings():
        group_id = dn_to_id.get(str(mapping.get("group_dn") or "").casefold())
        if not group_id:
            continue
        store.map_external_group_role(
            group_id,
            _system_role_id(str(mapping.get("role") or "user")),
            "ldap-login-sync",
        )
    central.invalidate()
