from __future__ import annotations

from collections import deque

from ..ldap_authentication import repository as ldap_repository
from ..security import SessionUser
from .permission_service import PermissionRepository


def refresh_cached_ldap_memberships(
    repository: PermissionRepository,
    user: SessionUser,
    *,
    max_depth: int = 16,
    max_nodes: int = 10000,
) -> None:
    """Project the login-refreshed LDAP cache into the RBAC membership graph.

    This performs no network I/O. If LDAP is offline the last successful cached
    membership remains available until a newer successful login/sync replaces it.
    """
    if user.auth_provider != "ldap":
        return
    ldap_store = ldap_repository()
    identity = None
    if user.identity_id:
        identity = ldap_store.identity_by_id(user.identity_id)
    if identity is None:
        identity = ldap_store.identity_by_username(user.username)
    if identity is None:
        return

    external_groups = repository.external_groups()
    by_dn = {
        str(group["distinguished_name"]).casefold(): group
        for group in external_groups
        if group.get("distinguished_name")
    }
    by_id = {str(group["id"]): group for group in external_groups}
    direct_ids = {
        str(by_dn[dn.casefold()]["id"])
        for dn in identity.get("groups") or []
        if str(dn).casefold() in by_dn
    }
    effective_ids = set(direct_ids)
    queue: deque[tuple[str, int]] = deque((group_id, 0) for group_id in direct_ids)
    while queue:
        group_id, depth = queue.popleft()
        if depth >= max_depth:
            continue
        group = by_id.get(group_id)
        if not group:
            continue
        for parent_id in group.get("parent_ids") or []:
            parent_id = str(parent_id)
            if parent_id in effective_ids:
                continue
            if len(effective_ids) >= max_nodes:
                return
            effective_ids.add(parent_id)
            queue.append((parent_id, depth + 1))

    repository.replace_external_memberships(
        "ldap",
        str(identity["immutable_id"]),
        str(identity["username"]),
        effective_ids,
        direct_ids,
    )
