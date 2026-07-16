from __future__ import annotations

import json
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from app.identity import linux_accounts
from app.identity.models import GroupCreateRequest, GroupPolicy, GroupPolicyRequest, Role, UserCreateRequest, UserPatchRequest, UserPolicy, UserPolicyRequest, UserQuotaRequest
from app.identity.permissions import PERMISSION_REGISTRY, Permission, normalize_permission, require_permission
from app.identity.repository import IdentityRepository
from app.identity.service import IdentityService
from app.security import create_session


def account(name: str, uid: int, gid: int, shell: str = "/bin/bash"):
    return SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid, pw_dir=f"/home/{name}", pw_shell=shell, pw_gecos=name.title())


def group(name: str, gid: int, members: list[str] | None = None):
    return SimpleNamespace(gr_name=name, gr_gid=gid, gr_mem=members or [], gr_passwd="x")


def fake_accounts(monkeypatch, users: list, groups: list) -> None:
    def get_user(name):
        found = next((item for item in users if item.pw_name == name), None)
        if found is None:
            raise KeyError(name)
        return found

    def get_group(name):
        found = next((item for item in groups if item.gr_name == name), None)
        if found is None:
            raise KeyError(name)
        return found

    def get_gid(gid):
        found = next((item for item in groups if item.gr_gid == gid), None)
        if found is None:
            raise KeyError(gid)
        return found

    monkeypatch.setattr(linux_accounts.pwd, "getpwall", lambda: users)
    monkeypatch.setattr(linux_accounts.pwd, "getpwnam", get_user)
    monkeypatch.setattr(linux_accounts.grp, "getgrall", lambda: groups)
    monkeypatch.setattr(linux_accounts.grp, "getgrnam", get_group)
    monkeypatch.setattr(linux_accounts.grp, "getgrgid", get_gid)
    monkeypatch.setattr(linux_accounts, "_account_status", lambda username: (False, False))


@pytest.mark.parametrize(
    ("users", "groups", "username"),
    [
        ([account("root", 0, 0)], [group("root", 0)], "root"),
        ([account("alice", 1001, 100)], [group("users", 100), group("sudo", 27, ["alice"])], "alice"),
        ([account("alice", 1001, 100)], [group("users", 100), group("wheel", 10, ["alice"])], "alice"),
        ([account("alice", 1001, 27)], [group("sudo", 27)], "alice"),
    ],
)
def test_detects_linux_administrators_including_primary_group(monkeypatch, users, groups, username):
    fake_accounts(monkeypatch, users, groups)
    assert linux_accounts.is_linux_admin(username) is True


def test_effective_permissions_include_group_sources_and_deny_wins(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0), account("alice", 1001, 100)]
    groups = [group("root", 0), group("users", 100), group("ops", 1100, ["alice"])]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_group_policy(GroupPolicy(groupname="ops", allow=[Permission.SERVICES_RESTART.value, Permission.SERVICES_VIEW.value]), "admin")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.user, allow=[Permission.DNS_VIEW.value], deny=[Permission.SERVICES_RESTART.value]), "admin")
    profile = IdentityService(repository).access_profile("alice")

    assert Permission.SERVICES_VIEW.value in profile["permissions"]
    assert Permission.DNS_VIEW.value in profile["permissions"]
    assert Permission.SERVICES_RESTART.value not in profile["permissions"]
    assert profile["permission_sources"][Permission.SERVICES_VIEW.value] == ["group:ops"]
    assert "deny:user" in profile["permission_sources"][Permission.SERVICES_RESTART.value]


def test_unknown_permissions_and_allow_deny_overlap_are_rejected():
    with pytest.raises(ValueError, match="unknown permission"):
        UserPolicy(username="alice", allow=["system.root_shell"])
    with pytest.raises(ValueError, match="both allowed and denied"):
        UserPolicy(username="alice", allow=[Permission.SERVICES_VIEW.value], deny=[Permission.SERVICES_VIEW.value])
    assert normalize_permission("rbac.manage") == Permission.ACCESS_MANAGE_ROLES.value


def test_permission_metadata_identifies_apps_operation_and_risk():
    metadata = PERMISSION_REGISTRY[Permission.USERS_CREATE.value]
    assert metadata.applications == ["identity"]
    assert metadata.operation == "create"
    assert metadata.mutating is True
    assert metadata.risk.value == "high"
    assert metadata.description_key == "permissions.category.users.description"


def test_linux_admin_cannot_be_degraded_or_denied(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0)]
    fake_accounts(monkeypatch, users, [group("root", 0)])
    service = IdentityService(IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json"))

    with pytest.raises(HTTPException) as error:
        service.save_user_policy("root", UserPolicyRequest(role=Role.user), "root")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        service.save_user_policy("root", UserPolicyRequest(role=Role.admin, deny=[Permission.FILES_DELETE.value]), "root")
    assert error.value.detail["code"] == "LINUX_ADMIN_COMPATIBILITY"


def test_last_effective_administrator_is_protected(monkeypatch, tmp_path: Path):
    users = [account("alice", 1001, 100), account("bob", 1002, 100)]
    groups = [group("users", 100)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.admin), "bootstrap")
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.save_user_policy("alice", UserPolicyRequest(role=Role.operator), "alice")

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "LAST_ADMIN_PROTECTION"


def test_group_deny_cannot_remove_last_administrator(monkeypatch, tmp_path: Path):
    users = [account("alice", 1001, 100)]
    groups = [group("users", 100), group("team", 1100, ["alice"])]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.admin), "bootstrap")
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.save_group_policy("team", GroupPolicyRequest(deny=[Permission.ACCESS_MANAGE_ROLES.value]), "alice")

    assert error.value.detail["code"] == "LAST_ADMIN_PROTECTION"


def test_group_membership_cannot_apply_a_deny_to_last_administrator(monkeypatch, tmp_path: Path):
    users = [account("alice", 1001, 100)]
    groups = [group("users", 100), group("quarantine", 1100)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.admin), "bootstrap")
    repository.save_group_policy(GroupPolicy(groupname="quarantine", deny=[Permission.ACCESS_MANAGE_ROLES.value]), "bootstrap")
    monkeypatch.setattr(linux_accounts, "set_group_member", lambda *args: pytest.fail("membership must not change after continuity check fails"))
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.set_group_member("quarantine", "alice", "alice", True)

    assert error.value.detail["code"] == "LAST_ADMIN_PROTECTION"


def test_legacy_rbac_migration_is_idempotent_and_creates_backup(tmp_path: Path):
    legacy = tmp_path / "rbac.json"
    legacy.write_text(json.dumps({"alice": {"role": "operator", "allow": ["audit.view", "unknown.old"], "deny": ["docker.operate"]}}), encoding="utf-8")
    path = tmp_path / "identity.sqlite3"

    first = IdentityRepository(path, legacy_path=legacy)
    second = IdentityRepository(path, legacy_path=legacy)
    policy = second.user_policy("alice")

    assert policy and policy.role == Role.operator
    assert policy.allow == [Permission.AUDIT_VIEW_ALL.value]
    assert policy.deny == [Permission.DOCKER_CONTAINERS.value]
    assert legacy.with_name("rbac.json.identity-v1.bak").is_file()
    assert len([item for item in first.changes() if item.subject_type == "migration"]) == 1


def test_permission_dependency_requires_csrf_for_mutation(monkeypatch):
    response = Response()
    csrf = create_session(response, "alice")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    monkeypatch.setattr("app.identity.permissions.has_permission", lambda username, permission: True)
    dependency = require_permission(Permission.USERS_CREATE)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", cookie.encode("latin-1"))]})

    with pytest.raises(HTTPException) as error:
        dependency(request)
    assert error.value.status_code == 403
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", cookie.encode("latin-1")), (b"x-csrf-token", csrf.encode("latin-1"))]})
    assert dependency(request).username == "alice"


def test_identity_admin_actions_accept_the_authenticated_session_without_a_second_password():
    assert "admin_password" not in UserCreateRequest.model_fields
    assert "admin_password" not in UserPatchRequest.model_fields
    assert "admin_password" not in GroupCreateRequest.model_fields


def test_password_value_never_reaches_activity_audit(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0), account("alice", 1001, 100)]
    fake_accounts(monkeypatch, users, [group("root", 0), group("users", 100)])
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(linux_accounts, "change_password", lambda username, password, force_change: None)
    service_module = importlib.import_module("app.identity.service")
    monkeypatch.setattr(service_module, "record_activity", lambda *args, **kwargs: events.append((args, kwargs)))
    service = IdentityService(IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json"))

    service.change_user_password("alice", "do-not-log-this-secret", True, "root")

    assert events
    assert "do-not-log-this-secret" not in repr(events)
    assert events[-1][1]["details"] == {"current": {"force_change": True}}


def test_linux_commands_use_closed_argument_arrays_and_password_stdin(monkeypatch):
    users = [account("alice", 1001, 100)]
    groups = [group("users", 100)]
    fake_accounts(monkeypatch, users, groups)
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(linux_accounts, "_tool", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(linux_accounts, "_run", lambda args, input_text=None, timeout=60: calls.append((args, input_text)) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    linux_accounts.change_password("alice", "new-password", True)

    assert calls[0][0] == ["/usr/sbin/chpasswd"]
    assert calls[0][1] == "alice:new-password\n"
    assert all("sh" not in command[0] for command, _ in calls)


def test_linux_user_and_group_operations_use_expected_tools(monkeypatch):
    users = [account("alice", 1001, 100)]
    groups = [group("users", 100), group("ops", 1100)]
    fake_accounts(monkeypatch, users, groups)
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(linux_accounts, "_tool", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(linux_accounts, "_run", lambda args, input_text=None, timeout=60: calls.append((args, input_text)) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(linux_accounts, "assert_admin_user_allowed", lambda *args: None)
    monkeypatch.setattr(linux_accounts, "assert_admin_group_allowed", lambda *args: None)

    linux_accounts.create_user(UserCreateRequest(username="bob", password="temporary", uid=1200, gid=1100, groups=["ops"], force_password_change=True))
    linux_accounts.update_user("alice", UserPatchRequest(gecos="Alice Operator", groups_add=["ops"], force_password_change=True))
    linux_accounts.set_lock("alice", True)
    linux_accounts.set_quota("alice", UserQuotaRequest(soft_mb=100, hard_mb=200, mountpoint="/"))
    linux_accounts.delete_user("alice", remove_home=False)
    linux_accounts.create_group(GroupCreateRequest(groupname="newteam", gid=1201))
    linux_accounts.rename_group("ops", "support")
    linux_accounts.set_group_member("ops", "alice", True)
    linux_accounts.delete_group("ops")

    tools = [Path(command[0]).name for command, _input in calls]
    assert {"useradd", "chpasswd", "chage", "usermod", "setquota", "userdel", "groupadd", "groupmod", "groupdel"} <= set(tools)
    useradd = next(command for command, _input in calls if Path(command[0]).name == "useradd")
    assert "--gid" in useradd and "--user-group" not in useradd
    assert all(command[0].startswith("/usr/sbin/") for command, _input in calls)


def test_system_uid_creation_is_rejected_before_running_a_command(monkeypatch):
    monkeypatch.setattr(linux_accounts.pwd, "getpwnam", lambda username: (_ for _ in ()).throw(KeyError(username)))
    monkeypatch.setattr(linux_accounts, "assert_admin_user_allowed", lambda *args: None)
    monkeypatch.setattr(linux_accounts, "_run", lambda *args, **kwargs: pytest.fail("system account creation must stop before executing useradd"))
    payload = UserCreateRequest(username="service-user", password="temporary", uid=999)
    with pytest.raises(HTTPException) as error:
        linux_accounts.create_user(payload)
    assert error.value.detail["code"] == "SYSTEM_UID_BLOCKED"


def test_linux_identity_fields_reject_unsafe_values(monkeypatch):
    with pytest.raises(HTTPException):
        linux_accounts.validate_name("../root", "user")
    with pytest.raises(HTTPException):
        linux_accounts.validate_home("/etc/alice", "alice")
    with pytest.raises(HTTPException):
        linux_accounts.validate_gecos("Alice:root")
    monkeypatch.setattr(linux_accounts, "allowed_shells", lambda: ["/bin/bash"])
    with pytest.raises(HTTPException):
        linux_accounts.validate_shell("/tmp/custom-shell")


def test_group_rename_moves_application_policy(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0), account("alice", 1001, 100)]
    groups = [group("root", 0), group("users", 100), group("ops", 1100, ["alice"]), group("support", 1101)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_group_policy(GroupPolicy(groupname="ops", allow=[Permission.SERVICES_VIEW.value]), "root")
    monkeypatch.setattr(linux_accounts, "rename_group", lambda old, new: None)
    service = IdentityService(repository)

    result = service.rename_group("ops", "support", "root")

    assert result["allow"] == [Permission.SERVICES_VIEW.value]
    assert repository.group_policy("ops") is None
    assert repository.group_policy("support") is not None


def test_proxmox_guard_is_checked_before_creating_linux_user(monkeypatch):
    payload = UserCreateRequest(username="alice", password="secret")
    monkeypatch.setattr(linux_accounts.pwd, "getpwnam", lambda username: (_ for _ in ()).throw(KeyError(username)))
    monkeypatch.setattr(linux_accounts, "assert_admin_user_allowed", lambda *args: (_ for _ in ()).throw(HTTPException(403, "Proxmox Safe Mode")))
    monkeypatch.setattr(linux_accounts, "_run", lambda *args, **kwargs: pytest.fail("no system command may run after a Proxmox denial"))

    with pytest.raises(HTTPException) as error:
        linux_accounts.create_user(payload)
    assert error.value.status_code == 403


def test_operator_cannot_modify_an_application_administrator(monkeypatch, tmp_path: Path):
    users = [account("admin", 1001, 100), account("operator", 1002, 100)]
    groups = [group("users", 100)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="admin", role=Role.admin), "bootstrap")
    repository.save_user_policy(UserPolicy(username="operator", role=Role.operator), "bootstrap")
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.set_user_lock("admin", "operator", current_username="operator", locked=True)
    assert error.value.detail["code"] == "ADMIN_TARGET_PROTECTED"


def test_failed_linux_user_delete_restores_application_policy(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0), account("alice", 1001, 100)]
    fake_accounts(monkeypatch, users, [group("root", 0), group("users", 100)])
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.operator, allow=[Permission.DNS_VIEW.value]), "root")
    monkeypatch.setattr(linux_accounts, "delete_user", lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(400, "userdel failed")))
    service = IdentityService(repository)

    with pytest.raises(HTTPException):
        service.delete_user("alice", "root", current_username="root", remove_home=False)

    restored = repository.user_policy("alice")
    assert restored and restored.role == Role.operator
    assert restored.allow == [Permission.DNS_VIEW.value]


def test_new_and_legacy_identity_routes_are_registered():
    from app.identity.router import router as identity_router
    from app.rbac import router as rbac_router

    # FastAPI 0.139 keeps included routers as lazy wrappers on the application,
    # so route registration is asserted on the source routers themselves.
    routes = {(route.path, method) for router in (identity_router, rbac_router) for route in router.routes for method in getattr(route, "methods", set())}
    assert ("/api/identity/users", "GET") in routes
    assert ("/api/identity/groups/{groupname}/policy", "PUT") in routes
    assert ("/api/admin/users", "GET") in routes
    assert ("/api/admin/groups/{groupname}/members/{username}", "DELETE") in routes
    assert ("/api/rbac/assignments/{username}", "PUT") in routes
