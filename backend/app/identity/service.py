from __future__ import annotations

import pwd
import threading
from typing import Any

from fastapi import HTTPException

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..audit import logger
from . import linux_accounts
from .exceptions import identity_error
from .models import GroupCreateRequest, GroupPolicy, GroupPolicyRequest, Role, UserCreateRequest, UserPatchRequest, UserPolicy, UserPolicyRequest, UserQuotaRequest
from .permissions import ALL_PERMISSIONS, Permission, ROLE_PERMISSIONS
from .repository import IdentityRepository, repository


class IdentityService:
    def __init__(self, policy_repository: IdentityRepository) -> None:
        self.repository = policy_repository
        self._lock = threading.RLock()

    def _profile(self, username: str, *, user_override: UserPolicy | None = None, group_override: GroupPolicy | None = None, groups_override: tuple[str, set[str]] | None = None) -> dict[str, Any]:
        if linux_accounts.is_linux_admin(username):
            return {
                "username": username, "role": Role.admin.value, "role_source": "linux-admin", "linux_admin": True, "is_admin": True,
                "permissions": sorted(ALL_PERMISSIONS), "effective_permissions": sorted(ALL_PERMISSIONS), "denied_permissions": [],
                "permission_sources": {permission: ["linux-admin"] for permission in sorted(ALL_PERMISSIONS)},
            }
        stored = user_override if user_override and user_override.username == username else self.repository.user_policy(username)
        policy = stored or UserPolicy(username=username)
        role_permissions = set(ROLE_PERMISSIONS[policy.role])
        allowed = set(role_permissions)
        denied: set[str] = set()
        sources: dict[str, list[str]] = {permission: [f"role:{policy.role.value}"] for permission in role_permissions}
        try:
            groups = sorted(groups_override[1]) if groups_override and groups_override[0] == username else linux_accounts.groups_for(username)
        except HTTPException:
            groups = []
        for groupname in groups:
            group_policy = group_override if group_override and group_override.groupname == groupname else self.repository.group_policy(groupname)
            if not group_policy:
                continue
            for permission in group_policy.allow:
                allowed.add(permission)
                sources.setdefault(permission, []).append(f"group:{groupname}")
            for permission in group_policy.deny:
                denied.add(permission)
                sources.setdefault(permission, []).append(f"deny:group:{groupname}")
        for permission in policy.allow:
            allowed.add(permission)
            sources.setdefault(permission, []).append("user")
        for permission in policy.deny:
            denied.add(permission)
            sources.setdefault(permission, []).append("deny:user")
        permissions = allowed - denied
        for permission in denied:
            sources.setdefault(permission, []).append("deny")
        return {
            "username": username, "role": policy.role.value, "role_source": "assignment" if stored else "default", "linux_admin": False,
            "is_admin": policy.role == Role.admin and Permission.ACCESS_MANAGE_ROLES.value in permissions,
            "permissions": sorted(permissions), "effective_permissions": sorted(permissions), "denied_permissions": sorted(denied), "permission_sources": {key: list(dict.fromkeys(value)) for key, value in sorted(sources.items())},
        }

    def access_profile(self, username: str) -> dict[str, Any]:
        return self._profile(username)

    def user(self, username: str) -> dict[str, Any]:
        record = linux_accounts.user_record(username)
        policy = self.repository.user_policy(username) or UserPolicy(username=username)
        profile = self._profile(username)
        return {**record, **profile, "allow": policy.allow, "deny": policy.deny}

    def users(self, *, include_system: bool = False, search: str = "", role: str = "", status: str = "") -> list[dict[str, Any]]:
        result = []
        for record in linux_accounts.list_users(include_system=include_system, search=search):
            user = self.user(record["username"])
            if role and user["role"] != role:
                continue
            if status == "locked" and not user["locked"]:
                continue
            if status == "active" and user["locked"]:
                continue
            result.append(user)
        return result

    def group(self, groupname: str) -> dict[str, Any]:
        record = linux_accounts.group_record(groupname)
        policy = self.repository.group_policy(groupname) or GroupPolicy(groupname=groupname)
        inheritors = []
        for account in pwd.getpwall():
            try:
                if groupname in linux_accounts.groups_for(account.pw_name):
                    inheritors.append(account.pw_name)
            except HTTPException:
                continue
        return {**record, "allow": policy.allow, "deny": policy.deny, "inheriting_users": sorted(inheritors), "inheriting_count": len(inheritors)}

    def groups(self, *, include_system: bool = False, search: str = "") -> list[dict[str, Any]]:
        return [self.group(item["name"]) for item in linux_accounts.list_groups(include_system=include_system, search=search)]

    def _effective_administrators(self, *, user_override: UserPolicy | None = None, group_override: GroupPolicy | None = None, groups_override: tuple[str, set[str]] | None = None, excluding: str = "") -> list[str]:
        result = []
        for account in pwd.getpwall():
            if account.pw_name == excluding:
                continue
            profile = self._profile(account.pw_name, user_override=user_override, group_override=group_override, groups_override=groups_override)
            if profile["linux_admin"] or (profile["role"] == Role.admin.value and Permission.ACCESS_MANAGE_ROLES.value in profile["permissions"]):
                result.append(account.pw_name)
        return result

    def _protect_admin_continuity(self, *, user_override: UserPolicy | None = None, group_override: GroupPolicy | None = None, groups_override: tuple[str, set[str]] | None = None, excluding: str = "", field: str = "role", actor: str = "") -> None:
        if self._effective_administrators(user_override=user_override, group_override=group_override, groups_override=groups_override, excluding=excluding):
            return
        record_activity(ActivityCategory.administration, "last_admin_protection", actor or "unknown", target=excluding or (user_override.username if user_override else group_override.groupname if group_override else ""), status=ActivityStatus.failure, summary="LAST_ADMIN_PROTECTION", source="identity")
        identity_error(409, "LAST_ADMIN_PROTECTION", "The operation would remove the last effective administrator", field=field)

    @staticmethod
    def _audit(actor: str, action: str, target: str, *, previous: dict[str, Any] | None = None, current: dict[str, Any] | None = None) -> None:
        details: dict[str, Any] = {}
        if previous is not None:
            details["previous"] = previous
        if current is not None:
            details["current"] = current
        logger.info("identity_action actor=%s action=%s target=%s", actor, action, target)
        record_activity(ActivityCategory.administration, action, actor, target=target, details=details, source="identity")

    def _assert_actor_can_manage_target(self, actor: str, username: str) -> None:
        target = self._profile(username)
        actor_profile = self._profile(actor)
        if (target["linux_admin"] or target["role"] == Role.admin.value) and not actor_profile["is_admin"]:
            identity_error(403, "ADMIN_TARGET_PROTECTED", "Only an administrator can modify another effective administrator")

    def save_user_policy(self, username: str, payload: UserPolicyRequest, actor: str) -> dict[str, Any]:
        with self._lock:
            linux_accounts.local_user(username)
            previous = self.repository.user_policy(username) or UserPolicy(username=username)
            if linux_accounts.is_linux_admin(username):
                if payload.role != Role.admin or payload.deny:
                    identity_error(409, "LINUX_ADMIN_COMPATIBILITY", "A Linux administrator always retains full administrator access", field="role" if payload.role != Role.admin else "deny")
                policy = UserPolicy(username=username, role=Role.admin, allow=payload.allow, deny=[])
            else:
                policy = UserPolicy(username=username, role=payload.role, allow=payload.allow, deny=payload.deny)
                self._protect_admin_continuity(user_override=policy, actor=actor)
            saved = self.repository.save_user_policy(policy, actor)
        self._audit(actor, "user_policy_update", username, previous=previous.model_dump(mode="json"), current=saved.model_dump(mode="json"))
        return self.user(username)

    def save_group_policy(self, groupname: str, payload: GroupPolicyRequest, actor: str) -> dict[str, Any]:
        with self._lock:
            group = linux_accounts.local_group(groupname)
            if linux_accounts.is_protected_group(groupname, group.gr_gid):
                identity_error(403, "PROTECTED_LINUX_GROUP", "Protected Linux groups cannot receive application policy")
            previous = self.repository.group_policy(groupname) or GroupPolicy(groupname=groupname)
            policy = GroupPolicy(groupname=groupname, allow=payload.allow, deny=payload.deny)
            self._protect_admin_continuity(group_override=policy, actor=actor)
            saved = self.repository.save_group_policy(policy, actor)
        self._audit(actor, "group_policy_update", groupname, previous=previous.model_dump(mode="json"), current=saved.model_dump(mode="json"))
        return self.group(groupname)

    def create_user(self, payload: UserCreateRequest, actor: str) -> dict[str, Any]:
        linux_accounts.create_user(payload)
        try:
            self.repository.save_user_policy(UserPolicy(username=payload.username, role=payload.role, allow=payload.allow, deny=payload.deny), actor, action="create")
        except Exception:
            try:
                linux_accounts.delete_user(payload.username, remove_home=payload.create_home)
            except Exception:
                logger.exception("identity_create_user_compensation_failed username=%s", payload.username)
            raise
        result = self.user(payload.username)
        self._audit(actor, "user_create", payload.username, current={key: value for key, value in result.items() if key not in {"permission_sources"}})
        return result

    def update_user(self, username: str, payload: UserPatchRequest, actor: str) -> dict[str, Any]:
        self._assert_actor_can_manage_target(actor, username)
        previous = self.user(username)
        with self._lock:
            if payload.groups_add or payload.groups_remove:
                next_groups = set(linux_accounts.groups_for(username))
                next_groups.update(payload.groups_add)
                next_groups.difference_update(payload.groups_remove)
                self._protect_admin_continuity(groups_override=(username, next_groups), field="groups", actor=actor)
            next_username = linux_accounts.update_user(username, payload)
        if next_username != username:
            try:
                self.repository.rename_user_policy(username, next_username, actor)
            except Exception:
                try:
                    linux_accounts.update_user(next_username, UserPatchRequest(new_username=username))
                except Exception:
                    logger.exception("identity_rename_user_compensation_failed old=%s new=%s", username, next_username)
                raise
        result = self.user(next_username)
        self._audit(actor, "user_rename" if next_username != username else "user_update", next_username, previous=previous, current=result)
        return result

    def delete_user(self, username: str, actor: str, *, current_username: str, remove_home: bool) -> None:
        if username == current_username:
            identity_error(409, "CURRENT_USER_PROTECTION", "The currently signed-in user cannot be deleted")
        self._assert_actor_can_manage_target(actor, username)
        with self._lock:
            linux_accounts.assert_manageable_user(username, "delete")
            self._protect_admin_continuity(excluding=username, actor=actor)
            previous = self.user(username)
            stored_policy = self.repository.user_policy(username)
            self.repository.delete_user_policy(username, actor)
            try:
                linux_accounts.delete_user(username, remove_home=remove_home)
            except Exception:
                if stored_policy:
                    self.repository.save_user_policy(stored_policy, actor, action="delete_rollback")
                raise
        self._audit(actor, "user_delete", username, previous=previous)

    def set_user_lock(self, username: str, actor: str, *, current_username: str, locked: bool) -> None:
        if locked and username == current_username:
            identity_error(409, "CURRENT_USER_PROTECTION", "The currently signed-in user cannot be locked")
        self._assert_actor_can_manage_target(actor, username)
        with self._lock:
            if locked:
                self._protect_admin_continuity(excluding=username, actor=actor)
            linux_accounts.set_lock(username, locked)
        self._audit(actor, "user_lock" if locked else "user_unlock", username)

    def change_user_password(self, username: str, password: str, force_change: bool, actor: str) -> None:
        self._assert_actor_can_manage_target(actor, username)
        linux_accounts.change_password(username, password, force_change)
        self._audit(actor, "user_password_change", username, current={"force_change": force_change})

    def set_user_quota(self, username: str, payload: UserQuotaRequest, actor: str) -> None:
        self._assert_actor_can_manage_target(actor, username)
        linux_accounts.set_quota(username, payload)
        self._audit(actor, "user_quota_update", username, current={"soft_mb": payload.soft_mb, "hard_mb": payload.hard_mb, "mountpoint": payload.mountpoint})

    def create_group(self, payload: GroupCreateRequest, actor: str) -> dict[str, Any]:
        linux_accounts.create_group(payload)
        try:
            if payload.allow or payload.deny:
                self.repository.save_group_policy(GroupPolicy(groupname=payload.groupname, allow=payload.allow, deny=payload.deny), actor, action="create")
        except Exception:
            try:
                linux_accounts.delete_group(payload.groupname)
            except Exception:
                logger.exception("identity_create_group_compensation_failed group=%s", payload.groupname)
            raise
        result = self.group(payload.groupname)
        self._audit(actor, "group_create", payload.groupname, current=result)
        return result

    def rename_group(self, groupname: str, new_name: str, actor: str) -> dict[str, Any]:
        previous = self.group(groupname)
        linux_accounts.rename_group(groupname, new_name)
        try:
            self.repository.rename_group_policy(groupname, new_name, actor)
        except Exception:
            try:
                linux_accounts.rename_group(new_name, groupname)
            except Exception:
                logger.exception("identity_rename_group_compensation_failed old=%s new=%s", groupname, new_name)
            raise
        result = self.group(new_name)
        self._audit(actor, "group_rename", new_name, previous=previous, current=result)
        return result

    def delete_group(self, groupname: str, actor: str) -> None:
        previous = self.group(groupname)
        linux_accounts.assert_manageable_group(groupname, "delete")
        if previous["primary_users"]:
            identity_error(409, "GROUP_IS_PRIMARY", "Group is the primary group of one or more users")
        with self._lock:
            stored_policy = self.repository.group_policy(groupname)
            self.repository.delete_group_policy(groupname, actor)
            try:
                linux_accounts.delete_group(groupname)
            except Exception:
                if stored_policy:
                    self.repository.save_group_policy(stored_policy, actor, action="delete_rollback")
                raise
        self._audit(actor, "group_delete", groupname, previous=previous)

    def set_group_member(self, groupname: str, username: str, actor: str, present: bool) -> dict[str, Any]:
        with self._lock:
            next_groups = set(linux_accounts.groups_for(username))
            if present:
                next_groups.add(groupname)
            else:
                next_groups.discard(groupname)
            self._protect_admin_continuity(groups_override=(username, next_groups), field="groups", actor=actor)
            linux_accounts.set_group_member(groupname, username, present)
        self._audit(actor, "group_member_add" if present else "group_member_remove", f"{groupname}:{username}")
        return self.group(groupname)


_service: IdentityService | None = None
_service_path = ""
_service_lock = threading.Lock()


def service() -> IdentityService:
    global _service, _service_path
    current_repository = repository()
    with _service_lock:
        if _service is None or _service_path != str(current_repository.path):
            _service = IdentityService(current_repository)
            _service_path = str(current_repository.path)
        return _service


def access_profile(username: str) -> dict[str, Any]:
    return service().access_profile(username)
